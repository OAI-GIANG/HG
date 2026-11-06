"""Standalone read-only verification worker.

This file intentionally imports only the Python standard library so it can run as
python -I -B worker.py in a separate process. The process boundary reduces accidental
coupling; it is NOT OS isolation because the worker has the same UID and filesystem access.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
import time
from pathlib import Path
from urllib.parse import quote


MAX_REQUEST_BYTES = 16 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_DATABASE_BYTES = 64 * 1024 * 1024


def _target(root_text, relative, limit):
    root = Path(root_text)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError("root must be an absolute real directory")
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or Path(relative).is_absolute()):
        raise ValueError("path must be a non-empty relative POSIX path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("path traversal or empty path component")
    current = root
    for part in parts[:-1]:
        current = current / part
        st = current.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise ValueError("path parent is not a real directory")
    target = current / parts[-1]
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(target, flags)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        raise ValueError("target must be an owner-owned regular file")
    if st.st_size > limit:
        os.close(fd)
        raise ValueError("target exceeds validation size limit")
    return target, fd, st.st_size


def _read(fd, size, limit):
    chunks, total = [], 0
    while True:
        chunk = os.read(fd, min(65536, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError("target grew beyond validation size limit")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if len(raw) != size:
        raise ValueError("target changed while being read")
    return raw


def _python_syntax(root, path):
    target, fd, size = _target(root, path, MAX_SOURCE_BYTES)
    try:
        raw = _read(fd, size, MAX_SOURCE_BYTES)
    finally:
        os.close(fd)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        source = raw.decode("utf-8")
        compile(source, str(target), "exec", dont_inherit=True)
    except UnicodeDecodeError as exc:
        return {"check": "PYTHON_SYNTAX", "status": "FAIL", "sha256": digest,
                "bytes": len(raw), "reason": "source is not valid UTF-8", "offset": exc.start}
    except SyntaxError as exc:
        return {"check": "PYTHON_SYNTAX", "status": "FAIL", "sha256": digest,
                "bytes": len(raw), "reason": (exc.msg or "SyntaxError")[:240],
                "line": exc.lineno, "offset": exc.offset}
    return {"check": "PYTHON_SYNTAX", "status": "PASS", "sha256": digest, "bytes": len(raw),
            "reason": "source compiled in memory; no bytecode cache written"}


def _sqlite_integrity(root, path):
    target, fd, size = _target(root, path, MAX_DATABASE_BYTES)
    opened_stat = os.fstat(fd)
    db = None
    try:
        # Only verify a closed, standalone snapshot. A live/WAL-backed database must be
        # copied consistently before this worker is used.
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(target) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise ValueError("SQLite snapshot has journal sidecars; capture a closed consistent copy first")
        uri = "file:" + quote(str(target), safe="/") + "?mode=ro"
        deadline = time.monotonic() + 5.0
        db = sqlite3.connect(uri, uri=True, timeout=1.0, isolation_level=None)
        # Verify SQLite opened the same inode that passed O_NOFOLLOW/fstat. Keep that
        # descriptor open for the entire check so pathname replacement cannot swap
        # the attested file between validation and database open.
        path_stat = target.lstat()
        if (stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_dev != opened_stat.st_dev or path_stat.st_ino != opened_stat.st_ino):
            raise ValueError("SQLite path changed between safe open and read-only database open")
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        row = db.execute("PRAGMA integrity_check(1)").fetchone()
        result = row[0] if row else "no result"
        return {"check": "SQLITE_INTEGRITY", "status": "PASS" if result == "ok" else "FAIL",
                "bytes": size, "integrity_result": str(result)[:240],
                "reason": "read-only SQLite integrity_check on the opened snapshot inode"}
    finally:
        if db is not None:
            db.close()
        os.close(fd)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds size limit")
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict) or set(request) != {"operation", "root", "path"}:
            raise ValueError("request schema is invalid")
        operation = request["operation"]
        if operation == "python_syntax":
            result = _python_syntax(request["root"], request["path"])
        elif operation == "sqlite_integrity":
            result = _sqlite_integrity(request["root"], request["path"])
        else:
            raise ValueError("unsupported verification operation")
        result["worker"] = "hg-s03-verification-worker-v1"
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"check": "WORKER", "status": "BLOCKED",
                          "reason": f"{type(exc).__name__}: {str(exc)[:240]}"},
                         sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
