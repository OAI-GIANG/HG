"""Append-only JSONL ledger with path-scoped thread/process serialization.

The lock protects the complete read/validate/append sequence. It is advisory: every
writer using this API cooperates; direct filesystem writes remain outside this boundary.
"""
import errno
import fcntl
import json
import os
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .core import MAEPError

_LOCKS_GUARD = threading.Lock()
_LOCKS = {}
_HELD = threading.local()      # per-thread {resolved ledger path: (fd, exclusive)}


def _thread_lock(path):
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _held():
    held = getattr(_HELD, "map", None)
    if held is None:
        held = _HELD.map = {}
    return held


@contextmanager
def ledger_lock(path, *, exclusive=True, create=False, wait_s=5.0, poll_s=0.02):
    """Lock the ledger inode itself across threads/processes without creating sidecar files.

    A nested call in the thread that already holds the lock reuses that descriptor: a second
    descriptor would wait on this thread's own flock until the timeout. Upgrading a shared
    hold to exclusive is refused at once instead of deadlocking.
    """
    target = Path(path)
    if create:
        target.parent.mkdir(parents=True, exist_ok=True)
    key = str(target.resolve())
    held = _held()
    if key in held:
        fd, held_exclusive = held[key]
        if exclusive and not held_exclusive:
            raise MAEPError("cannot upgrade a shared ledger lock to exclusive in the same thread")
        yield fd
        return
    local = _thread_lock(target)
    if not local.acquire(timeout=max(0.0, wait_s)):
        raise MAEPError("ledger is busy; admission timed out")
    fd = None
    try:
        flags = (os.O_RDWR | os.O_CREAT | os.O_APPEND) if create else os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError as exc:
            raise MAEPError("cannot safely open ledger for admission") from exc
        st = os.fstat(fd)
        # Integrity, not secrecy: refuse a file another user could write. New ledgers are
        # created 0600 above; confidentiality is enforced by the private state/home directory.
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o022:
            raise MAEPError("ledger must be an owner-owned regular file that no other user can write")
        mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        deadline = time.monotonic() + max(0.0, wait_s)
        while True:
            try:
                fcntl.flock(fd, mode)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise MAEPError("ledger admission lock failed") from exc
                if time.monotonic() >= deadline:
                    raise MAEPError("ledger is busy; admission timed out") from exc
                time.sleep(poll_s)
        held[key] = (fd, exclusive)
        try:
            yield fd
        finally:
            held.pop(key, None)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        local.release()


def _read_events_unlocked(path, fd=None):
    path = Path(path)
    if fd is None and not path.exists():
        return []
    events = []
    seen = set()
    if fd is None:
        stream_context = path.open("r", encoding="utf-8")
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        stream_context = os.fdopen(os.dup(fd), "r", encoding="utf-8")
    with stream_context as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise MAEPError(f"blank ledger line at {line_number}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MAEPError(f"invalid ledger JSON at line {line_number}") from exc
            if not line.endswith("\n"):
                # A record is committed only with its terminator (C1). A parseable final line
                # without one is a torn write: refuse it, never repair or truncate here.
                raise MAEPError(f"torn ledger tail at line {line_number}: missing record terminator")
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
                raise MAEPError(f"invalid event record at line {line_number}")
            if event["event_id"] in seen:
                raise MAEPError(f"duplicate event_id at line {line_number}")
            seen.add(event["event_id"])
            events.append(event)
    return events


def read_events(path):
    """Read a consistent ledger view; missing ledgers remain absent."""
    path = Path(path)
    if not path.exists():
        return []
    with ledger_lock(path, exclusive=False, create=False) as fd:
        return _read_events_unlocked(path, fd)


def _require_terminated_tail(fd):
    """Refuse to append onto a ledger whose last byte is not a record terminator."""
    size = os.fstat(fd).st_size
    if size == 0:
        return
    if os.pread(fd, 1, size - 1) != b"\n":
        raise MAEPError("torn ledger tail: missing record terminator; refusing to append")


def _append_unlocked(fd, event):
    payload = (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short append write")
        view = view[written:]
    os.fsync(fd)


def append_event(path, event):
    """Append a unique event under the canonical cross-instance/process ledger lock."""
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise MAEPError("event must have a non-empty event_id")
    path = Path(path)
    with ledger_lock(path, exclusive=True, create=True) as fd:
        current = _read_events_unlocked(path, fd)
        _require_terminated_tail(fd)
        if any(existing["event_id"] == event["event_id"] for existing in current):
            raise MAEPError("event_id already exists; append an amendment with a new ID")
        _append_unlocked(fd, event)
    return event["event_id"]


def append_generated(path, factory):
    """Atomically allocate data from the latest ledger view and append the result."""
    path = Path(path)
    with ledger_lock(path, exclusive=True, create=True) as fd:
        current = _read_events_unlocked(path, fd)
        _require_terminated_tail(fd)
        event = factory(current)
        if (not isinstance(event, dict) or not isinstance(event.get("event_id"), str)
                or not event["event_id"]):
            raise MAEPError("event factory must return an event with a non-empty event_id")
        if any(existing["event_id"] == event["event_id"] for existing in current):
            raise MAEPError("event_id already exists; append an amendment with a new ID")
        _append_unlocked(fd, event)
    return event
