"""Fail-closed SQLite opener for HG ledgers on Linux/Android.

Python's sqlite3 module cannot open a database from a file descriptor or with a
custom VFS: SQLite always resolves and opens the database, ``-journal``,
``-wal`` and ``-shm`` files by absolute pathname, and opens the sidecars lazily.
A descriptor alias (``/proc/self/fd/N``) is no protection: SQLite readlinks it
and opens the resulting name (``"<path> (deleted)"`` after an unlink). Opening
and closing a private descriptor on the database is also unsafe, because
close() drops every POSIX lock this process holds on that inode, including the
locks of other live SQLite connections.

This opener therefore never holds a descriptor on the database or ``-shm``
file. It enforces, and re-verifies at open and at every commit:

* every path component is walked with openat(O_PATH|O_NOFOLLOW|O_DIRECTORY):
  no symlink anywhere in the path;
* no directory on the path is writable by an untrusted user (ancestors may be
  sticky, the database directory may not), so other users cannot swap the
  database or plant sidecars;
* the database and any existing sidecar are regular files owned by this user,
  with one link and no group/other write permission;
* SQLite's own resolved filename equals the canonical path, and the canonical
  name still names the inode that was validated.

Residual limit (cannot be closed with stdlib sqlite3): a process running as the
same user can swap a regular file at the canonical name and restore it within
the window between a check and SQLite's internal name-based open/commit. Such a
process can also rewrite the database directly; isolating it requires a
separate UID or a VFS that opens relative to a pinned directory descriptor.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import threading
from typing import Any
from urllib.parse import quote

__all__ = ["UnsafeSQLitePath", "connect_nofollow", "verify_binding"]

_SIDECARS = ("-journal", "-wal", "-shm")
_ANDROID = sys.platform == "android" or hasattr(sys, "getandroidapilevel")
_AID_APP_START = 10000  # Android UIDs/GIDs below this belong to the platform.
# Serialises open/create so a just-created inode is closed before any other
# in-process SQLite connection can take POSIX locks on it.
_OPEN_LOCK = threading.Lock()
_FACTORIES: dict[type, type] = {}


class UnsafeSQLitePath(OSError):
    """The database cannot be bound to its path safely; callers must fail closed."""


class _Binding:
    __slots__ = ("canonical", "dirs", "name", "identity", "private")

    def __init__(self, canonical, dirs, name, identity, private):
        self.canonical, self.dirs, self.name = canonical, dirs, name
        self.identity, self.private = identity, private


def _require_platform() -> None:
    if (os.name != "posix" or not all(hasattr(os, f) for f in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC"))
            or os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd
            or os.stat not in os.supports_follow_symlinks):
        raise UnsafeSQLitePath("safe SQLite open unavailable: openat/fstatat with O_NOFOLLOW required")


def _split(path: str | Path) -> tuple[str, tuple[str, ...], str]:
    raw = os.fspath(path)
    if not isinstance(raw, str) or "\x00" in raw:
        raise UnsafeSQLitePath("SQLite database path must be a text path")
    canonical = str(Path(raw).expanduser().absolute())
    try:
        canonical.encode("utf-8")  # SQLite URIs are UTF-8; undecodable names cannot be bound
    except UnicodeEncodeError as exc:
        raise UnsafeSQLitePath("SQLite database path must be valid UTF-8") from exc
    parts = canonical.split("/")[1:]
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise UnsafeSQLitePath("SQLite database path must be absolute and normalized")
    return canonical, tuple(parts[:-1]), parts[-1]


def _trusted_id(value: int, *, own: int) -> bool:
    return value == 0 or value == own or (_ANDROID and value < _AID_APP_START)


def _check_dir(st: os.stat_result, where: str, *, parent: bool) -> None:
    euid = os.geteuid()
    if not stat.S_ISDIR(st.st_mode):
        raise UnsafeSQLitePath(f"SQLite path component is not a directory: {where}")
    if parent and st.st_uid != euid:
        raise UnsafeSQLitePath(f"SQLite database directory must be owned by the current user: {where}")
    if not _trusted_id(st.st_uid, own=euid):
        raise UnsafeSQLitePath(f"SQLite path directory has an untrusted owner: {where}")
    sticky = bool(st.st_mode & stat.S_ISVTX) and not parent
    own_group = os.getegid() if _ANDROID else 0  # Android app GID == app UID group.
    if (st.st_mode & stat.S_IWOTH and not sticky) or (
            st.st_mode & stat.S_IWGRP and not sticky and not _trusted_id(st.st_gid, own=own_group)):
        raise UnsafeSQLitePath(f"SQLite path directory is writable by untrusted users: {where}")


def _open_parent(dirs: tuple[str, ...]) -> int:
    flags = getattr(os, "O_PATH", 0) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        where = ""
        _check_dir(os.fstat(fd), "/", parent=not dirs)
        for index, name in enumerate(dirs):
            where += "/" + name
            try:
                child = os.open(name, flags, dir_fd=fd)
            except OSError as exc:
                raise UnsafeSQLitePath(f"SQLite path component missing or a symlink: {where}") from exc
            os.close(fd)
            fd = child
            _check_dir(os.fstat(fd), where, parent=index == len(dirs) - 1)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _entry(dirfd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _check_file(st: os.stat_result, label: str, *, private: bool) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise UnsafeSQLitePath(f"{label} must be a regular non-symlink file")
    if st.st_uid != os.geteuid() or st.st_nlink != 1:
        raise UnsafeSQLitePath(f"{label} must be owned by the current user and have exactly one link")
    if stat.S_IMODE(st.st_mode) & (0o077 if private else 0o022):
        raise UnsafeSQLitePath(f"{label} permissions are too broad")


def _check_entries(dirfd: int, binding_name: str, *, private: bool) -> os.stat_result | None:
    st = _entry(dirfd, binding_name)
    if st is not None:
        _check_file(st, "SQLite database", private=private)
    for suffix in _SIDECARS:
        side = _entry(dirfd, binding_name + suffix)
        if side is not None:
            _check_file(side, "SQLite " + suffix[1:] + " file", private=private)
    return st


def _check_binding(binding: _Binding) -> None:
    """Re-walk the path and confirm it still names the validated database inode."""
    dirfd = _open_parent(binding.dirs)
    try:
        st = _check_entries(dirfd, binding.name, private=binding.private)
    finally:
        os.close(dirfd)
    if st is None or (st.st_dev, st.st_ino) != binding.identity:
        raise UnsafeSQLitePath("SQLite database path no longer names the opened database")


def verify_binding(connection: Any) -> None:
    binding = getattr(connection, "_hg_binding", None)
    if not isinstance(binding, _Binding):
        raise UnsafeSQLitePath("connection was not opened by connect_nofollow")
    _check_binding(binding)


def _factory(base: type) -> type:
    cls = _FACTORIES.get(base)
    if cls is None:
        class BoundConnection(base):  # type: ignore[misc, valid-type]
            _hg_binding = None

            def verify_binding(self) -> None:
                verify_binding(self)

            def commit(self) -> None:
                # Never commit into a database that is no longer at the canonical path,
                # and report (never hide) a swap that raced the COMMIT itself.
                if self._hg_binding is not None and self.in_transaction:
                    _check_binding(self._hg_binding)
                super().commit()
                if self._hg_binding is not None:
                    _check_binding(self._hg_binding)

        cls = _FACTORIES.setdefault(base, BoundConnection)
    return cls


def connect_nofollow(sqlite3_module: Any, path: str | Path, *, private: bool = False, **kwargs: Any):
    """Open ``path`` with SQLite, failing closed unless it is bound safely.

    ``private`` requires (and creates) a 0600 database and sidecars. Use the
    returned connection's ``commit()`` to commit, so the binding is re-verified.
    """
    if "uri" in kwargs or "factory" in kwargs:
        raise TypeError("connect_nofollow controls 'uri' and 'factory'")
    _require_platform()
    canonical, dirs, name = _split(path)
    with _OPEN_LOCK:
        dirfd = _open_parent(dirs)
        try:
            st = _check_entries(dirfd, name, private=private)
            if st is None:
                try:
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=dirfd)
                except FileExistsError:
                    pass
                else:
                    os.close(fd)  # brand-new inode: no SQLite connection holds locks on it
                st = _check_entries(dirfd, name, private=private)
                if st is None:
                    raise UnsafeSQLitePath("SQLite database disappeared during safe open")
        finally:
            os.close(dirfd)
        binding = _Binding(canonical, dirs, name, (st.st_dev, st.st_ino), bool(private))
        conn = sqlite3_module.connect("file:" + quote(canonical, safe="/") + "?mode=rw", uri=True,
                                      factory=_factory(sqlite3_module.Connection), **kwargs)
    try:
        conn._hg_binding = binding
        main = [row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"]
        if main != [canonical]:
            raise UnsafeSQLitePath("SQLite resolved the database to a different path")
        _check_binding(binding)
    except BaseException:
        conn.close()
        raise
    return conn
