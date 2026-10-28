"""The assistant's private home directory and its single-writer lock.

Layout (all private to the owner's Unix user):
    $HG_HOME/                     mode 0700, default ~/.local/share/hg/assistant
        .lock                     flock: writers LOCK_EX, readers LOCK_SH
        notes.jsonl               the owner's notes (hg.memory.store.MemoryStore ledger)
        asks-YYYY-MM.jsonl        one receipt per `hg ask` / `hg summarize` (monthly files)
        config.json               optional settings (see hg.assistant.config)

Why the lock is taken BEFORE a ledger is loaded: EventLog numbers events from its
in-memory count, so two processes that each loaded the file and then appended would write
the same sequence number and leave a ledger that no longer loads. Readers take a shared
lock so they never observe a half-written line. The lock is never held while a model
answers: `ask` reads notes under LOCK_SH, releases it, calls the model, then takes
LOCK_EX only to append its receipt.

Android shared storage (/sdcard, /storage) ignores Unix modes, so a home there is refused.
"""
import errno
import fcntl
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

SHARED_STORAGE = ("/sdcard", "/storage", "/mnt/sdcard")


class HomeError(Exception):
    """The home directory is unsafe or unusable (exit 78)."""


class Busy(Exception):
    """Another HG process holds the lock (exit 75)."""


def default_home(env=None):
    env = os.environ if env is None else env
    if env.get("HG_HOME"):
        return Path(env["HG_HOME"])
    base = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")
    return Path(base) / "hg" / "assistant"


def ensure_home(path, *, create=True):
    path = Path(path)
    if not path.is_absolute():
        raise HomeError("HG_HOME must be an absolute path")
    text = str(path)
    if any(text == p or text.startswith(p + "/") for p in SHARED_STORAGE):
        raise HomeError("HG_HOME must not be on Android shared storage (permissions are not enforced there)")
    if not path.exists() and create:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        st = path.lstat()
    except OSError as exc:
        raise HomeError(f"HG_HOME {path} does not exist") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise HomeError("HG_HOME must be a real directory, not a symlink")
    if path.resolve() != path:
        raise HomeError("HG_HOME must not have symlinked parents")
    if st.st_uid != os.getuid():
        raise HomeError("HG_HOME must be owned by the current user")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise HomeError("HG_HOME must not grant group/other access (chmod 700)")
    return path


def _open_lock(home):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(home / ".lock", flags, 0o600)
    except OSError as exc:
        raise HomeError("cannot safely open the lock file") from exc
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        os.close(fd)
        raise HomeError("lock file must be a private regular file owned by this user")
    return fd


@contextmanager
def locked(home, *, exclusive, wait_s=5.0, poll_s=0.05, monotonic=time.monotonic, sleep=time.sleep):
    """Hold the home lock; raise Busy if it cannot be had within wait_s."""
    fd = _open_lock(Path(home))
    mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
    deadline = monotonic() + wait_s
    try:
        while True:
            try:
                fcntl.flock(fd, mode)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK) or monotonic() >= deadline:
                    raise Busy("another HG process is using HG_HOME; try again") from exc
                sleep(poll_s)
        yield
    finally:
        os.close(fd)      # closing the descriptor releases the flock


def private_file(path):
    """Create (if needed) a 0600 file and refuse anything else: symlink, other owner, wider mode."""
    path = Path(path)
    flags = os.O_CREAT | os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise HomeError(f"cannot safely open {path.name}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise HomeError(f"{path.name} must be a private regular file (chmod 600)")
    finally:
        os.close(fd)
    return path
