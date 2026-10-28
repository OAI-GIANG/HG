"""Fail-closed SQLite opener for HG ledgers on Linux/Android.

Python's sqlite3 module cannot open a database from a file descriptor or with a
custom VFS: SQLite always resolves and opens the database, ``-journal``,
``-wal`` and ``-shm`` files by absolute pathname, and opens the sidecars lazily.
A descriptor alias (``/proc/self/fd/N``) is no protection: SQLite readlinks it
and opens the resulting name (``"<path> (deleted)"`` after an unlink). Opening
and closing a private descriptor on the database is also unsafe while another
connection in this process uses it, because close() drops every POSIX lock this
process holds on that inode.

Path binding. This opener enforces, and re-verifies at open and at every commit:

* every path component is walked with openat(O_PATH|O_NOFOLLOW|O_DIRECTORY):
  no symlink anywhere in the path;
* no directory on the path is writable by an untrusted user (ancestors may be
  sticky, the database directory may not), so other users cannot swap the
  database or plant sidecars;
* the database and any existing sidecar are regular files owned by this user,
  with one link and no group/other write permission;
* SQLite's own resolved filename equals the canonical path, and the canonical
  name still names the inode that was validated.

Recovery-record binding. SQLite pairs ``-wal``/``-journal`` with a database by
NAME only, and skips the close-time checkpoint of a database that was moved
while open. After a swap or restore, the original's committed WAL frames (or
hot journal) therefore stay at the path and SQLite replays (rolls back) them
into whatever database is now there, while ``PRAGMA integrity_check`` reports
``ok``. Invariant enforced here: a transaction or recovery record is applied
only to the database it belongs to.

* Identity lives in the database content: every database opened here carries a
  random non-zero ``application_id`` in page 1, assigned and changed only
  inside SQLite transactions (crash-atomic), and every ``commit()`` (also via
  the context manager) rewrites page 1, so each committed WAL transaction and
  each hot journal carries the identity of the database that wrote it.
* Admission, before SQLite reads the database: the ``-wal`` is decoded with
  SQLite's own validity rules (header, salts, cumulative checksums, commit
  frames) and a ``-journal`` is treated as hot exactly when SQLite would.
  Committed WAL frames or a hot journal are accepted only when every page-1
  image they contain names the identity found in the database file; anything
  unattributable is refused (UnsafeSQLitePath) and left untouched for
  ``adopt_sidecars`` or an operator. After open, SQLite's own view of page 1
  must name the same identity, else the connection closes without a checkpoint.
* Completion through the open descriptor: when the path stops naming the bound
  database (detected at commit or close), committed WAL frames are checkpointed
  with ``wal_checkpoint(TRUNCATE)``, which writes through SQLite's descriptor
  into the database they belong to and empties the WAL at the path.

Threat model and residual limits (stdlib sqlite3 has no VFS hook):

* A. Other UIDs: blocked by the directory and file ownership/permission checks.
* C. Untrusted processes that can write the directory: refused at open unless
  they run as this UID (then see B).
* D. Crash or power loss at any point: identity updates are SQLite
  transactions; recovery records are applied only after admission.
* B. Same-UID processes are NOT contained: they can copy an identity, rewrite
  the database or swap files inside the check/open window. Containing them
  requires a separate UID (Android app sandbox or service account) owning the
  database directory. A replacement that is an older copy of the SAME database
  (same identity) is not distinguished from the original. Concurrent processes
  are not cross-checked while the WAL holds no committed frames.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import struct
import sys
import threading
from typing import Any
from urllib.parse import quote
import weakref

__all__ = ["UnsafeSQLitePath", "adopt_sidecars", "connect_nofollow", "verify_binding"]

_SIDECARS = ("-journal", "-wal", "-shm")
_ANDROID = sys.platform == "android" or hasattr(sys, "getandroidapilevel")
_AID_APP_START = 10000  # Android UIDs/GIDs below this belong to the platform.
# Serialises open/create/admission so a just-created inode is closed before any
# other in-process SQLite connection can take POSIX locks on it. Reentrant: a
# failed open closes its connection while holding it.
_OPEN_LOCK = threading.RLock()
_FACTORIES: dict[type, type] = {}
# Live bound connections per canonical path: {canonical: {(st_dev, st_ino): [count, app_id]}}.
# Guarded by _OPEN_LOCK; garbage-collected connections are queued in _RELEASED.
_LIVE: dict[str, dict[tuple[int, int], list[int]]] = {}
_RELEASED: list[tuple[str, tuple[int, int]]] = []

_SQLITE_HEADER = b"SQLite format 3\x00"
_APP_ID_OFFSET = 68
_WAL_MAGIC = 0x377F0682
_WAL_VERSION = 3007000
_JOURNAL_MAGIC = b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7"
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


class UnsafeSQLitePath(OSError):
    """The database cannot be bound to its path safely; callers must fail closed."""


class _Binding:
    __slots__ = ("canonical", "dirs", "name", "identity", "private", "app_id")

    def __init__(self, canonical, dirs, name, identity, private):
        self.canonical, self.dirs, self.name = canonical, dirs, name
        self.identity, self.private = identity, private
        self.app_id = 0


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


# --- recovery-record admission ---------------------------------------------------------

def _open_member(dirfd: int, name: str, identity: tuple[int, int] | None = None) -> int | None:
    """Open a regular file in the bound directory read-only, without following links."""
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or (identity is not None and (st.st_dev, st.st_ino) != identity):
        os.close(fd)
        raise UnsafeSQLitePath(f"SQLite file changed during admission: {name}")
    return fd


def _page_app_id(page: bytes) -> int | None:
    if len(page) < 100 or page[:16] != _SQLITE_HEADER:
        return None
    return struct.unpack(">I", page[_APP_ID_OFFSET:_APP_ID_OFFSET + 4])[0]


def _wal_checksum(data: bytes, s0: int, s1: int, big_endian: bool) -> tuple[int, int]:
    words = struct.unpack((">" if big_endian else "<") + "%dI" % (len(data) // 4), data)
    for i in range(0, len(words), 2):
        s0 = (s0 + words[i] + s1) & 0xFFFFFFFF
        s1 = (s1 + words[i + 1] + s0) & 0xFFFFFFFF
    return s0, s1


def _wal_committed(fd: int) -> tuple[int, int, list[int | None]]:
    """Decode a WAL as SQLite recovery does.

    Returns (committed frames, committed transactions, page-1 identities in the
    committed region). Frames past the last valid commit frame are ignored by
    SQLite and here alike.
    """
    size = os.fstat(fd).st_size
    head = os.pread(fd, 32, 0)
    if len(head) < 32:
        return 0, 0, []
    magic, version, page_size, _seq, salt1, salt2, c1, c2 = struct.unpack(">8I", head)
    if (magic & 0xFFFFFFFE) != _WAL_MAGIC or version != _WAL_VERSION or not 512 <= page_size <= 65536 \
            or page_size & (page_size - 1):
        return 0, 0, []
    big = bool(magic & 1)
    s0, s1 = _wal_checksum(head[:24], 0, 0, big)
    if (s0, s1) != (c1, c2):
        return 0, 0, []
    frame_size = 24 + page_size
    frames = committed = txns = 0
    pending: list[int | None] = []
    ids: list[int | None] = []
    offset = 32
    while offset + frame_size <= size:
        frame = os.pread(fd, frame_size, offset)
        if len(frame) < frame_size:
            break
        pgno, commit_size, fsalt1, fsalt2, fc1, fc2 = struct.unpack(">6I", frame[:24])
        if pgno == 0 or (fsalt1, fsalt2) != (salt1, salt2):
            break
        s0, s1 = _wal_checksum(frame[:8], s0, s1, big)
        s0, s1 = _wal_checksum(frame[24:], s0, s1, big)
        if (s0, s1) != (fc1, fc2):
            break
        frames += 1
        if pgno == 1:
            pending.append(_page_app_id(frame[24:]))
        if commit_size:
            committed, txns = frames, txns + 1
            ids.extend(pending)
            pending = []
        offset += frame_size
    return committed, txns, ids


def _journal_hot(fd: int) -> tuple[bool, list[int | None]]:
    """(hot, page-1 identities) for a rollback journal, using SQLite's hot test.

    SQLite plays back a journal only when its first byte is non-zero and its
    header magic is valid; an unsynced journal starts with a zeroed magic.
    """
    size = os.fstat(fd).st_size
    head = os.pread(fd, 28, 0)
    if size == 0 or not head or head[0] == 0 or head[:8] != _JOURNAL_MAGIC:
        return False, []
    ids: list[int | None] = []
    offset = 0
    while offset + 28 <= size:
        head = os.pread(fd, 28, offset)
        if head[:8] != _JOURNAL_MAGIC:
            break
        n_rec, _nonce, _initial, sector, page_size = struct.unpack(">5I", head[8:28])
        if not (32 <= sector <= 65536 and 512 <= page_size <= 65536) or sector & (sector - 1) \
                or page_size & (page_size - 1):
            ids.append(None)  # SQLite reports corruption; never attributable
            break
        record = page_size + 8
        pos = offset + sector
        unbounded = n_rec in (0, 0xFFFFFFFF)
        count = (size - pos) // record if unbounded else n_rec
        for _ in range(count):
            if pos + record > size:
                break
            if struct.unpack(">I", os.pread(fd, 4, pos))[0] == 1:
                ids.append(_page_app_id(os.pread(fd, page_size, pos + 4)))
            pos += record
        if unbounded:
            break
        offset = -(-pos // sector) * sector
    return True, ids


def _admit(dirfd: int, name: str, st: os.stat_result | None, *, canonical: str) -> int | None:
    """Refuse recovery records that cannot be attributed to the database at the path.

    Must run before SQLite opens the database (SQLite applies a hot journal on
    first read). Returns the identity SQLite must report after open: the
    database file's application_id, or None when a live connection in this
    process already holds this database.
    """
    live = _LIVE.get(canonical)
    identity = None if st is None else (st.st_dev, st.st_ino)
    if live:
        if set(live) != {identity}:
            raise UnsafeSQLitePath("SQLite database path no longer names the database of a live connection")
        return None  # sidecars belong to the live connection; never open a private fd on its inode
    app_id = None
    if st is not None and st.st_size:
        fd = _open_member(dirfd, name, identity)
        if fd is not None:
            try:
                app_id = _page_app_id(os.pread(fd, 100, 0))
            finally:
                os.close(fd)
    records: list[int | None] = []
    wal = _open_member(dirfd, name + "-wal")
    if wal is not None:
        try:
            committed, _txns, ids = _wal_committed(wal)
        finally:
            os.close(wal)
        if committed:
            records += ids or [None]
    journal = _open_member(dirfd, name + "-journal")
    if journal is not None:
        try:
            hot, ids = _journal_hot(journal)
        finally:
            os.close(journal)
        if hot:
            records += ids or [None]
    if records and (not app_id or set(records) != {app_id}):
        raise UnsafeSQLitePath("SQLite -wal/-journal recovery records are not bound to this database; "
                               "refusing to apply them (see adopt_sidecars)")
    return app_id or 0


# --- live registry ---------------------------------------------------------------------

def _drain_released() -> None:
    while _RELEASED:
        canonical, identity = _RELEASED.pop()
        counts = _LIVE.get(canonical, {})
        entry = counts.get(identity)
        if entry and entry[0] > 1:
            entry[0] -= 1
        else:
            counts.pop(identity, None)
            if not counts:
                _LIVE.pop(canonical, None)


def _register(conn: Any, binding: _Binding) -> None:
    counts = _LIVE.setdefault(binding.canonical, {})
    entry = counts.setdefault(binding.identity, [0, 0])
    entry[0] += 1
    finalizer = weakref.finalize(conn, _RELEASED.append, (binding.canonical, binding.identity))
    finalizer.atexit = False
    conn._hg_finalizer = finalizer


def _release(conn: Any) -> None:
    finalizer = conn.__dict__.get("_hg_finalizer")
    if finalizer is None or finalizer.detach() is None:
        return
    binding = conn._hg_binding
    with _OPEN_LOCK:
        _RELEASED.append((binding.canonical, binding.identity))
        _drain_released()


# --- connection behaviour --------------------------------------------------------------

def _complete_through_descriptor(conn: Any) -> None:
    """Checkpoint committed WAL frames into the database SQLite holds open.

    The checkpoint writes through SQLite's descriptor, i.e. into the database
    the frames belong to even after the path was swapped, and TRUNCATE empties
    the WAL at the path so nothing is left to replay into a replacement.
    """
    try:
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except Exception:  # noqa: BLE001 - best effort; admission still refuses leftovers
        pass


def _abandon(conn: Any, sqlite3_module: Any) -> None:
    """Close a connection whose view may hold foreign records, without checkpointing them.

    Python < 3.12 cannot disable SQLite's close-time checkpoint; there the
    pre-open admission is the only guard.
    """
    conn.__dict__["_hg_abandoned"] = True
    flag = getattr(sqlite3_module, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
    try:
        if flag is not None:
            conn.setconfig(flag, True)
    finally:
        conn.close()


def _assign_identity(conn: Any, base: type) -> int:
    """Give a database without an identity one, atomically, and persist it in the file."""
    began = not conn.in_transaction
    if began:
        conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("PRAGMA application_id").fetchone()[0]
        if current == 0:
            current = secrets.randbelow(0x7FFFFFFF) + 1
            conn.execute(f"PRAGMA application_id = {current}")
        base.commit(conn)
    except BaseException:
        base.rollback(conn)
        raise
    _complete_through_descriptor(conn)  # identity reaches the database file, not just the WAL
    return int(current)


def _factory(base: type) -> type:
    cls = _FACTORIES.get(base)
    if cls is None:
        class BoundConnection(base):  # type: ignore[misc, valid-type]
            _hg_binding = None

            def verify_binding(self) -> None:
                verify_binding(self)

            def commit(self) -> None:
                binding = self._hg_binding
                # Never commit into a database that is no longer at the canonical path,
                # and report (never hide) a swap that raced the COMMIT itself.
                if binding is not None and self.in_transaction:
                    _check_binding(binding)
                    if binding.app_id:
                        # Page 1 in every transaction: its WAL frames / journal carry the identity.
                        self.execute(f"PRAGMA application_id = {binding.app_id}")
                super().commit()
                if binding is not None:
                    try:
                        _check_binding(binding)
                    except OSError:
                        _complete_through_descriptor(self)
                        raise

            def __exit__(self, exc_type, exc, tb):
                # sqlite3's C __exit__ commits without calling an overridden commit().
                if exc_type is None:
                    self.commit()
                    return False
                return super().__exit__(exc_type, exc, tb)

            def close(self) -> None:
                binding = self._hg_binding
                if binding is not None and not self.__dict__.get("_hg_abandoned"):
                    try:
                        _check_binding(binding)
                    except OSError:
                        # SQLite skips the close-time checkpoint of a moved database: finish
                        # the committed frames into it (close() discards an open transaction).
                        try:
                            if self.in_transaction:
                                base.rollback(self)
                            _complete_through_descriptor(self)
                        except Exception:  # noqa: BLE001 - connection already closed
                            pass
                try:
                    super().close()
                finally:
                    _release(self)

        cls = _FACTORIES.setdefault(base, BoundConnection)
    return cls


def connect_nofollow(sqlite3_module: Any, path: str | Path, *, private: bool = False, **kwargs: Any):
    """Open ``path`` with SQLite, failing closed unless it is bound safely.

    ``private`` requires (and creates) a 0600 database and sidecars. Commit with
    the returned connection's ``commit()`` (or its context manager) so the
    binding is re-verified and the transaction carries the database identity.
    The database's ``application_id`` is owned by this opener.
    """
    if "uri" in kwargs or "factory" in kwargs:
        raise TypeError("connect_nofollow controls 'uri' and 'factory'")
    _require_platform()
    canonical, dirs, name = _split(path)
    with _OPEN_LOCK:
        _drain_released()
        dirfd = _open_parent(dirs)
        try:
            st = _check_entries(dirfd, name, private=private)
            if st is None:
                _admit(dirfd, name, None, canonical=canonical)  # orphaned records: refuse before creating
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
            expected = _admit(dirfd, name, st, canonical=canonical)
        finally:
            os.close(dirfd)
        binding = _Binding(canonical, dirs, name, (st.st_dev, st.st_ino), bool(private))
        conn = sqlite3_module.connect("file:" + quote(canonical, safe="/") + "?mode=rw", uri=True,
                                      factory=_factory(sqlite3_module.Connection), **kwargs)
        conn._hg_binding = binding
        _register(conn, binding)
        try:
            main = [row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"]
            if main != [canonical]:
                raise UnsafeSQLitePath("SQLite resolved the database to a different path")
            _check_binding(binding)
            entry = _LIVE[canonical][binding.identity]
            if expected is None:
                expected = entry[1]
            seen = conn.execute("PRAGMA application_id").fetchone()[0]
            if seen != expected:
                raise UnsafeSQLitePath("SQLite applied recovery records of a different database")
            binding.app_id = seen or _assign_identity(conn, sqlite3_module.Connection)
            entry[1] = binding.app_id
        except BaseException:
            _abandon(conn, sqlite3_module)
            raise
    return conn


def adopt_sidecars(sqlite3_module: Any, path: str | Path, *, backup_dir: str | Path,
                   private: bool = False, **kwargs: Any) -> dict:
    """Operator recovery for recovery records the opener refuses as unattributable.

    For an operator who has established that the ``-wal``/``-journal`` at
    ``path`` belong to the database there (e.g. a crash before identities
    existed). Run only while nothing else uses the database. Copies the
    database and every sidecar into ``backup_dir`` (created, must not exist,
    with a SHA-256 manifest), then lets SQLite apply the records, requires
    ``PRAGMA integrity_check`` = ok, assigns an identity and checkpoints. A
    failure leaves the backup for restore. Never use it on sidecars left by a
    replaced database: move those beside the original database instead.
    """
    if "uri" in kwargs or "factory" in kwargs:
        raise TypeError("adopt_sidecars controls 'uri' and 'factory'")
    _require_platform()
    canonical, dirs, name = _split(path)
    backup = Path(os.fspath(backup_dir))
    if not backup.is_absolute():
        raise UnsafeSQLitePath("backup_dir must be absolute")
    with _OPEN_LOCK:
        _drain_released()
        if canonical in _LIVE:
            raise UnsafeSQLitePath("database is open in this process")
        os.mkdir(backup, 0o700)
        manifest: dict[str, Any] = {"database": canonical, "files": {}}
        dirfd = _open_parent(dirs)
        try:
            st = _check_entries(dirfd, name, private=private)
            if st is None:
                raise UnsafeSQLitePath("database does not exist")
            identity = (st.st_dev, st.st_ino)
            for suffix in ("",) + _SIDECARS:
                src = _open_member(dirfd, name + suffix, identity if not suffix else None)
                if src is None:
                    continue
                digest = hashlib.sha256()
                dst = os.open(backup / (name + suffix), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                              | os.O_CLOEXEC, 0o600)
                try:
                    while chunk := os.read(src, 1 << 20):
                        digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            view = view[os.write(dst, view):]
                    os.fsync(dst)
                finally:
                    os.close(dst)
                    os.close(src)
                manifest["files"][name + suffix] = digest.hexdigest()
        finally:
            os.close(dirfd)
        with open(backup / "MANIFEST.json", "x", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        bfd = os.open(backup, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(bfd)
        finally:
            os.close(bfd)
        binding = _Binding(canonical, dirs, name, identity, bool(private))
        conn = sqlite3_module.connect("file:" + quote(canonical, safe="/") + "?mode=rw", uri=True,
                                      factory=_factory(sqlite3_module.Connection), **kwargs)
        conn._hg_binding = binding
        _register(conn, binding)
        try:
            _check_binding(binding)
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise UnsafeSQLitePath(f"integrity_check failed after recovery: {result}; restore from {backup}")
            manifest["application_id"] = binding.app_id = _assign_identity(conn, sqlite3_module.Connection)
            manifest["integrity_check"] = result
        except BaseException:
            _abandon(conn, sqlite3_module)
            raise
        conn.close()
    manifest["backup_dir"] = str(backup)
    return manifest
