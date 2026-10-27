"""Fail-closed SQLite opener for Linux/Android path-swap resistance.

Python's sqlite3.connect() does not expose SQLITE_OPEN_NOFOLLOW. Open the
canonical database inode with O_NOFOLLOW first, then pass its procfs fd path
to SQLite. SQLite resolves that fd to the already-open inode; if the canonical
name is unlinked/replaced during the boundary, opening fails or post-open
identity validation rejects the connection before callers can issue SQL.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any


def connect_nofollow(sqlite3_module: Any, path: str | Path, **kwargs: Any):
    target = Path(path).expanduser().absolute()
    if not hasattr(os, "O_NOFOLLOW") or not Path("/proc/self/fd").is_dir():
        raise OSError("safe SQLite open unavailable: O_NOFOLLOW/procfs fd path required")
    flags = os.O_RDWR | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(str(target), flags)
    except FileNotFoundError:
        try:
            fd = os.open(str(target), flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = os.open(str(target), flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("SQLite database must be a regular non-symlink file")
        # Use a URI so the descriptor-backed path is interpreted as a database
        # filename. Never fall back to the attacker-controlled canonical path.
        conn = sqlite3_module.connect(
            f"file:/proc/self/fd/{fd}?mode=rw", uri=True, **kwargs
        )
        try:
            named = os.lstat(str(target))
            current = os.fstat(fd)
            if (stat.S_ISLNK(named.st_mode) or not stat.S_ISREG(named.st_mode)
                    or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                    or (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino)):
                raise OSError("SQLite database path changed during safe open")
        except BaseException:
            conn.close()
            raise
        return conn
    finally:
        os.close(fd)
