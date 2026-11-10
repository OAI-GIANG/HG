"""Re-entrant process lock with final-component symlink resistance for memory outcomes."""
import errno
import fcntl
import os
import stat
import threading
from contextlib import contextmanager
from pathlib import Path

_registry_guard = threading.Lock()
_path_locks = {}
_held = threading.local()


def _thread_lock(key):
    with _registry_guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _path_locks[key] = lock
        return lock


@contextmanager
def outcome_file_lock(path):
    """Serialize memory writers across threads/processes; allow same-thread re-entry.

    Notebook and MemoryStore intentionally share this lock. flock() on a second
    independently-opened descriptor can self-deadlock even in one process, so a
    thread-local depth counter reuses the outer descriptor while the RLock
    serializes other local threads. Other processes still contend on kernel flock.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(target) + ".outcome.lock")
    key = os.path.abspath(os.fspath(lock_path))
    local_lock = _thread_lock(key)
    local_lock.acquire()
    held = getattr(_held, "entries", None)
    if held is None:
        held = {}
        _held.entries = held
    state = held.get(key)
    outermost = state is None
    try:
        if outermost:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                raise OSError(errno.ENOTSUP, "O_NOFOLLOW is required for the memory outcome lock")
            flags = os.O_CREAT | os.O_RDWR | nofollow | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(lock_path, flags, 0o600)
            try:
                st = os.fstat(fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                        or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) & 0o077):
                    raise OSError(errno.EPERM,
                                  "memory outcome lock must be an owner-only regular single-link file")
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
            state = {"fd": fd, "depth": 1}
            held[key] = state
        else:
            state["depth"] += 1
        try:
            yield
        finally:
            state["depth"] -= 1
            if outermost:
                try:
                    fcntl.flock(state["fd"], fcntl.LOCK_UN)
                finally:
                    os.close(state["fd"])
                    held.pop(key, None)
    finally:
        local_lock.release()
