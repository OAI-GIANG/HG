#!/usr/bin/env python3
"""Hold one HG runtime state writer lock until the owning switch process releases it."""
from __future__ import annotations

import fcntl
import os
import stat
import sys
import time


def hold(lock_path: str, ready_path: str, release_path: str, parent_pid: int) -> int:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise RuntimeError("writer lock must be an owner-owned private regular file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ready_fd = os.open(ready_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(ready_fd, "w", encoding="ascii") as stream:
            stream.write(f"{os.getpid()}\n")
            stream.flush()
            os.fsync(stream.fileno())
        while not os.path.exists(release_path):
            if os.getppid() != parent_pid:
                break
            time.sleep(0.05)
        return 0
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    if len(argv) != 6 or argv[1] != "hold":
        print("usage: state_lock.py hold LOCK READY RELEASE PARENT_PID", file=sys.stderr)
        return 2
    try:
        return hold(argv[2], argv[3], argv[4], int(argv[5]))
    except BlockingIOError:
        print("writer lock is already held", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"writer lock refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
