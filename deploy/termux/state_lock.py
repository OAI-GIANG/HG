#!/usr/bin/env python3
"""Take, or prove ownership of, the HG runtime state writer lock on a descriptor the CALLER holds.

    state_lock.py acquire FD LOCK   flock(FD, LOCK_EX|LOCK_NB) on the caller's open descriptor
    state_lock.py verify  FD LOCK   prove FD's open file description still owns that flock

switch_service.sh opens LOCK on its own descriptor (`exec 9< LOCK`) and runs `acquire` as a short
child that inherits it. flock(2) locks belong to the open file description, not to the process
that called flock, so the lock stays with the switch shell after this program exits and lasts
exactly as long as the shell keeps the descriptor open. There is no separate holder process whose
death could release the lock while the switch carries on (PR #87 review F-01).

`verify` never takes a lock it did not already own: a fresh, independent description first tries
the lock (success means nobody held it -> refused); only then is FD re-locked, which is a no-op
for the owning description and fails for any other.

Exit codes: 0 locked/owned, 2 usage, 3 another description holds the lock, 4 refused (not a
private regular file, path does not name FD's file, bad descriptor), 5 not held by FD.
Same-UID processes can still bypass an advisory flock; this is the documented v1 limit.
"""
from __future__ import annotations

import fcntl
import os
import stat
import sys


class LockRefused(Exception):
    """The descriptor or path is not an acceptable state writer lock."""


class LockNotHeld(Exception):
    """The descriptor's open file description does not own the exclusive flock."""


def _same_file(fd: int, path: str) -> os.stat_result:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise LockRefused("writer lock must be an owner-owned private regular file")
    named = os.lstat(path)
    if stat.S_ISLNK(named.st_mode) or not stat.S_ISREG(named.st_mode):
        raise LockRefused("writer lock path is not a regular non-symlink file")
    if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
        raise LockRefused("writer lock path no longer names the locked file")
    return info


def verify_held(fd: int, path: str) -> None:
    """Raise unless the open file description behind fd owns the exclusive flock on path."""
    info = _same_file(fd, path)
    probe = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        seen = os.fstat(probe)
        if (seen.st_dev, seen.st_ino) != (info.st_dev, info.st_ino):
            raise LockRefused("writer lock path changed while it was checked")
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass                                    # some description owns it; is it fd's?
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise LockNotHeld("nobody holds the state writer lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # no-op for the owner, fails for others
        except BlockingIOError:
            raise LockNotHeld("another process holds the state writer lock") from None
    finally:
        os.close(probe)


def acquire(fd: int, path: str) -> None:
    _same_file(fd, path)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)          # BlockingIOError: someone else has it
    try:
        _same_file(fd, path)                                 # not renamed or replaced meanwhile
        verify_held(fd, path)
    except BaseException:
        fcntl.flock(fd, fcntl.LOCK_UN)
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in ("acquire", "verify") or not argv[2].isdigit():
        print("usage: state_lock.py acquire|verify FD LOCK", file=sys.stderr)
        return 2
    fd, path = int(argv[2]), argv[3]
    try:
        (acquire if argv[1] == "acquire" else verify_held)(fd, path)
    except BlockingIOError:
        print("writer lock is already held", file=sys.stderr)
        return 3
    except LockNotHeld as exc:
        print(f"writer lock not held: {exc}", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"writer lock refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
