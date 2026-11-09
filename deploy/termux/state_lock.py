#!/usr/bin/env python3
"""Take, or prove ownership of, the HG runtime state writer lock on a descriptor the CALLER holds.

    state_lock.py acquire FD LOCK   flock(FD, LOCK_EX|LOCK_NB) on the caller's open descriptor
    state_lock.py verify  FD LOCK   prove FD's open file description owns that flock
    state_lock.py free    LOCK      exit 0 if no process holds LOCK, 3 if one does

switch_service.sh opens LOCK on its own descriptor (`command exec 9< LOCK`) and runs `acquire` as
a short child that inherits it. flock(2) locks belong to the open file description, not to the
process that called flock, so the lock stays with the switch shell after this program exits and
lasts exactly as long as the shell keeps the descriptor open. There is no separate holder process
whose death could release the lock while the switch carries on (PR #87 review F-01).

`verify` never takes a lock (review A-05): ownership is read from /proc/self/fdinfo/FD, where the
kernel lists the flock held by that open file description and no other. An independent probe must
then be refused, as a consistency check. Without /proc/self/fdinfo lock lines ownership cannot be
proven without re-taking the lock, so `acquire` and `verify` refuse (fail closed).

Exit codes: 0 locked/owned/free, 2 usage, 3 another description holds the lock, 4 refused (not a
private regular file, path does not name FD's file, bad descriptor, no fdinfo), 5 not held by FD.
Same-UID processes can still bypass an advisory flock; this is the documented v1 limit.
"""
from __future__ import annotations

import fcntl
import os
import re
import stat
import sys

_FLOCK_WRITE = re.compile(r"^lock:\s+\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s")


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


def _owns_exclusive_flock(fd: int) -> bool:
    """Whether the kernel lists an exclusive flock owned by fd's open file description."""
    try:
        with open(f"/proc/self/fdinfo/{fd}", encoding="ascii", errors="replace") as stream:
            lines = stream.read().splitlines()
    except OSError as exc:
        raise LockRefused(f"cannot read /proc/self/fdinfo/{fd}: lock ownership cannot be proven") from exc
    return any(_FLOCK_WRITE.match(line) for line in lines)


def _held_by_anyone(path: str) -> bool:
    """Probe with a fresh, independent description; never touches the caller's descriptor."""
    probe = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        if not stat.S_ISREG(os.fstat(probe).st_mode):
            raise LockRefused("writer lock path is not a regular file")
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False
    finally:
        os.close(probe)


def verify_held(fd: int, path: str) -> None:
    """Raise unless the open file description behind fd owns the exclusive flock on path."""
    _same_file(fd, path)
    if not _owns_exclusive_flock(fd):
        raise LockNotHeld("another process holds the state writer lock" if _held_by_anyone(path)
                          else "nobody holds the state writer lock")
    if not _held_by_anyone(path):                            # consistency: fdinfo and flock must agree
        raise LockNotHeld("fdinfo lists a lock that an independent probe could take")


def acquire(fd: int, path: str) -> None:
    _same_file(fd, path)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)          # BlockingIOError: someone else has it
    try:
        verify_held(fd, path)                                # also proves fdinfo can show ownership
    except BaseException:
        fcntl.flock(fd, fcntl.LOCK_UN)
        raise


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[1] == "free":
            return 3 if _held_by_anyone(argv[2]) else 0
        if len(argv) != 4 or argv[1] not in ("acquire", "verify") or not argv[2].isdigit():
            print("usage: state_lock.py acquire|verify FD LOCK | state_lock.py free LOCK", file=sys.stderr)
            return 2
        fd, path = int(argv[2]), argv[3]
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
