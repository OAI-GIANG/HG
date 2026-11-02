"""Runtime state writer admission bound to the lifetime service lock.

This is an application-level capability for the trusted interpreter, not a sandbox against
hostile Python code in that same interpreter. The service process holds the OS flock for life.
"""
from pathlib import Path
import threading

from .core import MAEPError

_GUARD = threading.RLock()
_SESSIONS = {}


class RuntimeWriterSession:
    def __init__(self, state_dir, lock_fd):
        self.root = Path(state_dir).resolve()
        self._fd = lock_fd
        self._active = True
        with _GUARD:
            if str(self.root) in _SESSIONS:
                raise MAEPError("runtime state already has a registered writer session")
            _SESSIONS[str(self.root)] = self

    def authorizes(self, root):
        root = Path(root).resolve()
        with _GUARD:
            return self._active and root == self.root and _SESSIONS.get(str(root)) is self

    def close(self):
        with _GUARD:
            if not self._active:
                return
            self._active = False
            _SESSIONS.pop(str(self.root), None)
            fd, self._fd = self._fd, None
        if fd is not None:
            import os
            os.close(fd)


def require_writer_session(path, session=None):
    """Deny direct construction of writer stores below a protected runtime state root."""
    target = Path(path).resolve()
    for root in (target.parent, *target.parents):
        try:
            marker = root / ".writer.lock"
            if marker.is_file():
                if not isinstance(session, RuntimeWriterSession) or not session.authorizes(root):
                    raise MAEPError("runtime state writer admission requires the active lifetime session")
                return session
        except OSError as exc:
            raise MAEPError("cannot verify runtime state writer admission") from exc
    return None
