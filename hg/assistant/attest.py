"""Listener attestation for the local Ollama service (HG-LA-2).

Specification: docs/architecture/HG_LISTENER_ATTESTATION_V2.md. Five layers; each ends PASS, FAIL
(evidence of a mismatch), BLOCKED (the platform does not let HG collect the evidence) or UNVERIFIED
(no trust anchor to compare with). The overall status is VERIFIED_LISTENER only when every layer is
PASS; anything else is fail-closed for a caller that requires attestation.

  L1 supervision  runit's supervise/pid read through directory descriptors (the pid file opened with
                  O_NOFOLLOW and checked with fstat on that descriptor), process start time read
                  before and after pidfd_open (PID reuse), same PID namespace, parent is a runsv
                  process owned by this user whose working directory is this service directory.
  L2 identity     /proc/PID/exe opened once as a descriptor (never re-opened from a readlink path),
                  fstat'd, hashed through that descriptor, re-checked afterwards (content change,
                  execve during attestation, PID reuse, exit).
  L3 integrity    the SHA-256 of that content is listed in the release-tracked trust anchor
                  hg/assistant/trusted_runtimes.json (covered by the release manifest; never read
                  from HG_HOME or config.json).
  L4 credentials  /proc/PID/status against /proc/self/status under CREDENTIAL_POLICY.
  L5 listener     every socket in the process's descriptor table is duplicated with pidfd_getfd(2)
                  and inspected read-only (fstat inode, SO_DOMAIN/SO_TYPE/SO_PROTOCOL,
                  SO_ACCEPTCONN, SO_REUSEPORT, getsockname): exactly one TCP socket LISTENing on
                  host:port, no other bind on that port, SO_REUSEPORT off, same network namespace,
                  and no other visible process holds that socket.

Attestation.reverify() repeats the cheap checks after the caller's HTTP exchange: if the same
process still holds the same listening socket (same inode, still LISTEN), that socket existed for
the whole interval, and with SO_REUSEPORT off Linux lets no other socket bind host:port meanwhile.

Not proved (spec section 8): continuous execution integrity between two checks, integrity of
libraries or helper processes the binary loads, anything against root or a same-UID attacker (Q3).
The duplicated socket is never accepted on, shut down or written to; only our own reference is
closed, which does not affect the service.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import select
import socket
import stat
import subprocess
import sys
import time
from ipaddress import ip_address
from pathlib import Path

PASS, FAIL, BLOCKED, UNVERIFIED = "PASS", "FAIL", "BLOCKED", "UNVERIFIED"
VERIFIED_LISTENER = "VERIFIED_LISTENER"
LAYERS = ("L1_supervision", "L2_identity", "L3_integrity", "L4_credentials", "L5_listener")
# pidfd_getfd is in the unified syscall table (asm-generic numbers >= 424): 438 on arm64 and x86_64.
SYS_PIDFD_GETFD = 438
PID_MAX = 4194304
ANCHOR_PATH = Path(__file__).with_name("trusted_runtimes.json")
ANCHOR_SCHEMA = "hg-trusted-runtimes-v1"
_PID_RE = re.compile(rb"[1-9][0-9]{0,6}\n?")
_SOCKET_RE = re.compile(r"socket:\[([0-9]+)\]")
_HEX64 = re.compile(r"[0-9a-f]{64}")

CREDENTIAL_POLICY = {
    "uids": "real, effective, saved and filesystem UID all equal HG's real UID",
    "gids": "real, effective, saved and filesystem GID all equal HG's real GID",
    "groups": "supplementary groups are exactly HG's supplementary groups",
    "capabilities": "CapInh, CapPrm, CapEff, CapAmb and CapBnd hold no bit HG's own set lacks",
    "seccomp": "same seccomp mode as HG (an app process inherits the platform filter)",
    "no_new_privs": "NoNewPrivs at least HG's value",
    "selinux": "same SELinux context as HG when HG's own context is readable",
}


def _result(status, code, **evidence):
    return {"status": status, "code": code, **evidence}


def _errname(exc):
    return errno.errorcode.get(getattr(exc, "errno", None) or 0, exc.__class__.__name__)


class _Hooks:
    """Test seam for race injection; every hook is a no-op in production."""

    def __init__(self, **callbacks):
        self._callbacks = callbacks

    def __call__(self, name, *args):
        callback = self._callbacks.get(name)
        if callback:
            callback(*args)


# ---------------------------------------------------------------- /proc readers

class ProcStat:
    __slots__ = ("pid", "comm", "state", "ppid", "starttime")

    def __init__(self, pid, comm, state, ppid, starttime):
        self.pid, self.comm, self.state, self.ppid, self.starttime = pid, comm, state, ppid, starttime


def _read_small(path, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        chunks, total = [], 0
        while total <= limit:
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def parse_stat(raw, pid=None):
    """Parse /proc/PID/stat; comm is everything between the first '(' and the LAST ')'."""
    text = raw.decode("latin-1")
    first, last = text.find("("), text.rfind(")")
    if first < 0 or last < first:
        raise ValueError("malformed /proc stat line")
    head = text[:first].strip()
    rest = text[last + 1:].split()
    if len(rest) < 20 or (pid is not None and head != str(pid)):
        raise ValueError("malformed /proc stat line")
    return ProcStat(int(head), text[first + 1:last], rest[0], int(rest[1]), int(rest[19]))


def read_stat(pid, *, proc="/proc"):
    return parse_stat(_read_small(f"{proc}/{pid}/stat"), pid)


def parse_status(raw):
    fields = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def read_status(pid, *, proc="/proc"):
    return parse_status(_read_small(f"{proc}/{pid}/status"))


def _selinux_context(pid, proc="/proc"):
    raw = _read_small(f"{proc}/{pid}/attr/current", 4096)
    return raw.rstrip(b"\0\n").decode("utf-8", "replace")


def _same_ns(kind, pid, proc="/proc"):
    mine, theirs = os.stat(f"{proc}/self/ns/{kind}"), os.stat(f"{proc}/{pid}/ns/{kind}")
    return (mine.st_dev, mine.st_ino) == (theirs.st_dev, theirs.st_ino)


def _exited(pidfd):
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(0))


# ---------------------------------------------------------------- pidfd_getfd

_LIBC = None
_CAPABILITY = None
_CAPABILITY_CODE = r"""
import ctypes, os, sys
try:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    pidfd = os.pidfd_open(os.getpid())
except AttributeError:
    print("NO_PIDFD_OPEN"); sys.exit(4)
except OSError as exc:
    print(exc.errno); sys.exit(4)
fd = libc.syscall(ctypes.c_long(%d), ctypes.c_long(pidfd), ctypes.c_long(0), ctypes.c_long(0))
if fd < 0:
    print(ctypes.get_errno()); sys.exit(3)
print(0)
""" % SYS_PIDFD_GETFD


def _libc():
    global _LIBC
    if _LIBC is None:
        for name in (None, "libc.so", "libc.so.6"):
            try:
                lib = ctypes.CDLL(name, use_errno=True)
                lib.syscall.restype = ctypes.c_long
                _LIBC = lib
                break
            except (OSError, AttributeError):
                continue
        else:
            raise OSError(errno.ENOSYS, "no libc syscall() entry point")
    return _LIBC


def pidfd_getfd(pidfd, targetfd):
    """Duplicate descriptor `targetfd` of the process behind `pidfd` (Linux 5.6+, CLOEXEC set)."""
    fd = _libc().syscall(ctypes.c_long(SYS_PIDFD_GETFD), ctypes.c_long(pidfd), ctypes.c_long(targetfd),
                         ctypes.c_long(0))
    if fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(fd)


def capability(*, refresh=False, runner=subprocess.run):
    """Whether pidfd_open + pidfd_getfd can be called here, probed in a child process.

    A seccomp filter that traps the syscall kills the caller with SIGSYS (Android's app filter does
    that for disallowed calls), so the first call is made in a throwaway interpreter. The child only
    duplicates its own descriptor: cross-process permission (ptrace rules, SELinux) is judged per
    target, at the real call.
    """
    global _CAPABILITY
    if _CAPABILITY is not None and not refresh:
        return _CAPABILITY
    if not hasattr(os, "pidfd_open"):
        _CAPABILITY = _result(BLOCKED, "PIDFD_OPEN_UNSUPPORTED_BY_PYTHON")
        return _CAPABILITY
    try:
        done = runner([sys.executable, "-I", "-S", "-c", _CAPABILITY_CODE], stdin=subprocess.DEVNULL,
                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        _CAPABILITY = _result(BLOCKED, "CAPABILITY_PROBE_FAILED", error=exc.__class__.__name__)
        return _CAPABILITY
    out = (done.stdout or b"").decode("ascii", "replace").strip()
    if done.returncode == 0:
        _CAPABILITY = _result(PASS, "AVAILABLE")
    elif done.returncode == -31:     # SIGSYS
        _CAPABILITY = _result(BLOCKED, "SECCOMP_SIGSYS")
    elif done.returncode in (3, 4) and out.isdigit():
        _CAPABILITY = _result(BLOCKED, ("PIDFD_GETFD_" if done.returncode == 3 else "PIDFD_OPEN_")
                              + errno.errorcode.get(int(out), out))
    else:
        _CAPABILITY = _result(BLOCKED, "CAPABILITY_PROBE_FAILED", returncode=done.returncode, output=out[:80])
    return _CAPABILITY


# ---------------------------------------------------------------- trust anchor

class AnchorError(ValueError):
    pass


def load_trust_anchor(path=ANCHOR_PATH):
    """Strictly parse the release-tracked anchor file; any defect raises AnchorError."""
    path = Path(path)
    try:
        st = path.lstat()
    except OSError as exc:
        raise AnchorError(f"trust anchor unreadable ({_errname(exc)})") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_size > 262144:
        raise AnchorError("trust anchor must be a regular file of at most 256 KiB")
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AnchorError("trust anchor is not valid UTF-8 JSON") from exc
    if not isinstance(doc, dict) or doc.get("schema") != ANCHOR_SCHEMA or not isinstance(doc.get("runtimes"), list):
        raise AnchorError(f"trust anchor must be an object with schema {ANCHOR_SCHEMA} and a runtimes list")
    entries = []
    for entry in doc["runtimes"]:
        if not isinstance(entry, dict) or set(entry) != {"name", "version", "sha256", "source", "provenance"}:
            raise AnchorError("each runtime needs exactly: name, version, sha256, source, provenance")
        if not isinstance(entry["name"], str) or not _HEX64.fullmatch(str(entry["sha256"])):
            raise AnchorError("runtime name must be a string and sha256 64 lowercase hex digits")
        if not isinstance(entry["provenance"], dict) or not entry["provenance"]:
            raise AnchorError("runtime provenance must be a non-empty object")
        entries.append(entry)
    return entries


# ---------------------------------------------------------------- L1

def _owned_not_shared(st, euid):
    return st.st_uid == euid and not st.st_mode & 0o022


def read_supervised_pid(service_dir):
    """Return (pid, service_dir_stat) from SERVICE/supervise/pid; raises _LayerFail on any defect."""
    euid = os.geteuid()
    try:
        dfd = os.open(service_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise _LayerFail("SERVICE_DIR_UNUSABLE", error=_errname(exc)) from exc
    try:
        dst = os.fstat(dfd)
        if not _owned_not_shared(dst, euid):
            raise _LayerFail("SERVICE_DIR_OWNER_OR_MODE")
        try:
            # `supervise` may be a symlink into a run directory (common runit layout); what matters is
            # the directory it resolves to, checked on the opened descriptor.
            sfd = os.open("supervise", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=dfd)
        except OSError as exc:
            raise _LayerFail("SUPERVISE_DIR_UNUSABLE", error=_errname(exc)) from exc
        try:
            if not _owned_not_shared(os.fstat(sfd), euid):
                raise _LayerFail("SUPERVISE_DIR_OWNER_OR_MODE")
            try:
                pfd = os.open("pid", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=sfd)
            except OSError as exc:
                raise _LayerFail("PID_FILE_SYMLINK" if exc.errno == errno.ELOOP else "PID_FILE_UNUSABLE",
                                 error=_errname(exc)) from exc
            try:
                pst = os.fstat(pfd)
                if not stat.S_ISREG(pst.st_mode):
                    raise _LayerFail("PID_FILE_NOT_REGULAR")
                if not _owned_not_shared(pst, euid):
                    raise _LayerFail("PID_FILE_OWNER_OR_MODE")
                data = os.read(pfd, 33)
            finally:
                os.close(pfd)
        finally:
            os.close(sfd)
    finally:
        os.close(dfd)
    if not data:
        raise _LayerFail("PID_FILE_EMPTY")
    if not _PID_RE.fullmatch(data) or int(data) > PID_MAX:
        raise _LayerFail("PID_FILE_MALFORMED")
    return int(data), dst


class _LayerFail(Exception):
    def __init__(self, code, status=FAIL, **evidence):
        super().__init__(code)
        self.code, self.status, self.evidence = code, status, evidence


def _supervision(service_dir, proc, hooks):
    pid, dst = read_supervised_pid(service_dir)
    hooks("after_pidfile", pid)
    try:
        first = read_stat(pid, proc=proc)
    except (OSError, ValueError) as exc:
        raise _LayerFail("STALE_PID", pid=pid, error=_errname(exc)) from exc
    if first.state in ("Z", "X", "x"):
        raise _LayerFail("PROCESS_DEAD", pid=pid, state=first.state)
    if not hasattr(os, "pidfd_open"):
        raise _LayerFail("PIDFD_OPEN_UNSUPPORTED_BY_PYTHON", status=BLOCKED, pid=pid)
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            raise _LayerFail("STALE_PID", pid=pid) from exc
        raise _LayerFail("PIDFD_OPEN_" + _errname(exc), status=BLOCKED, pid=pid) from exc
    try:
        hooks("after_pidfd", pid)
        try:
            second = read_stat(pid, proc=proc)
        except (OSError, ValueError) as exc:
            raise _LayerFail("PROCESS_EXITED", pid=pid) from exc
        if (second.starttime, second.comm) != (first.starttime, first.comm) or _exited(pidfd):
            raise _LayerFail("PID_REUSED_OR_EXITED", pid=pid)
        try:
            if not _same_ns("pid", pid, proc):
                raise _LayerFail("PIDNS_MISMATCH", pid=pid)
            parent = read_stat(second.ppid, proc=proc)
            parent_exe = os.path.basename(os.readlink(f"{proc}/{second.ppid}/exe"))
            parent_cwd = os.stat(f"{proc}/{second.ppid}/cwd")
            parent_owner = os.stat(f"{proc}/{second.ppid}").st_uid
        except _LayerFail:
            raise
        except (OSError, ValueError) as exc:
            raise _LayerFail("PARENT_UNREADABLE", pid=pid, ppid=second.ppid, error=_errname(exc)) from exc
        if parent.comm != "runsv" or parent_exe != "runsv":
            raise _LayerFail("PARENT_NOT_RUNSV", pid=pid, ppid=second.ppid, parent_comm=parent.comm)
        if (parent_cwd.st_dev, parent_cwd.st_ino) != (dst.st_dev, dst.st_ino):
            raise _LayerFail("RUNSV_OF_ANOTHER_SERVICE", pid=pid, ppid=second.ppid)
        if parent_owner != os.geteuid() or parent.starttime > second.starttime:
            raise _LayerFail("RUNSV_OWNER_OR_AGE", pid=pid, ppid=second.ppid)
        again, _ = read_supervised_pid(service_dir)
        if again != pid:
            raise _LayerFail("SERVICE_RESTARTED", pid=pid, now=again)
    except BaseException:
        os.close(pidfd)
        raise
    return pidfd, second, _result(PASS, "SUPERVISED", pid=pid, starttime=second.starttime, runsv_pid=second.ppid)


# ---------------------------------------------------------------- L2 / L3

def _hash_fd(fd):
    digest, offset = hashlib.sha256(), 0
    while True:
        chunk = os.pread(fd, 1 << 20, offset)
        if not chunk:
            return digest.hexdigest(), offset
        digest.update(chunk)
        offset += len(chunk)


def _stat_key(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _identity(pid, pidfd, ref, expected_name, proc, hooks):
    try:
        efd = os.open(f"{proc}/{pid}/exe", os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise _LayerFail("EXE_UNREADABLE", error=_errname(exc)) from exc
    try:
        before = os.fstat(efd)
        if not stat.S_ISREG(before.st_mode):
            raise _LayerFail("EXE_NOT_REGULAR")
        if before.st_nlink == 0:
            raise _LayerFail("EXE_DELETED")
        if before.st_uid not in (os.geteuid(), 0) or before.st_mode & 0o022:
            raise _LayerFail("EXE_OWNER_OR_MODE")
        try:
            name = os.path.basename(os.readlink(f"{proc}/{pid}/exe"))
        except OSError as exc:
            raise _LayerFail("EXE_UNREADABLE", error=_errname(exc)) from exc
        if name != expected_name:
            raise _LayerFail("EXE_NAME_MISMATCH", name=name[:64])
        digest, size = _hash_fd(efd)
        hooks("after_hash", pid)
        after = os.fstat(efd)
        if _stat_key(after) != _stat_key(before) or size != before.st_size:
            raise _LayerFail("EXE_CHANGED_DURING_HASH")
    finally:
        os.close(efd)
    try:
        again = os.stat(f"{proc}/{pid}/exe")
        now = read_stat(pid, proc=proc)
    except (OSError, ValueError) as exc:
        raise _LayerFail("PROCESS_EXITED", error=_errname(exc)) from exc
    if (again.st_dev, again.st_ino) != (before.st_dev, before.st_ino):
        raise _LayerFail("EXEC_DURING_ATTESTATION")
    if now.starttime != ref.starttime or _exited(pidfd):
        raise _LayerFail("PID_REUSED_OR_EXITED")
    return (before.st_dev, before.st_ino), digest, _result(
        PASS, "EXECUTABLE_IDENTIFIED", name=name, dev=before.st_dev, ino=before.st_ino, size=size, sha256=digest,
        scope="snapshot of the running image at two points; not continuous execution integrity")


def _integrity(name, digest, anchors):
    entries = [e for e in anchors if e["name"] == name]
    if not entries:
        return _result(UNVERIFIED, "NO_TRUST_ANCHOR", name=name)
    match = next((e for e in entries if e["sha256"] == digest), None)
    if match is None:
        return _result(FAIL, "DIGEST_NOT_ANCHORED", sha256=digest, anchored_versions=[e["version"] for e in entries])
    return _result(PASS, "DIGEST_ANCHORED", version=match["version"], source=match["source"])


# ---------------------------------------------------------------- L4

_CAP_KEYS = ("CapInh", "CapPrm", "CapEff", "CapAmb", "CapBnd")


def check_credentials(mine, theirs, *, my_context=None, their_context=None):
    """Pure policy check (CREDENTIAL_POLICY) of two parsed /proc status maps."""
    try:
        my_uids = [int(v) for v in mine["Uid"].split()]
        my_gids = [int(v) for v in mine["Gid"].split()]
        uids = [int(v) for v in theirs["Uid"].split()]
        gids = [int(v) for v in theirs["Gid"].split()]
        my_groups = {int(v) for v in mine["Groups"].split()}
        groups = {int(v) for v in theirs["Groups"].split()}
        caps = {k: (int(mine[k], 16), int(theirs[k], 16)) for k in _CAP_KEYS}
        seccomp = (int(mine["Seccomp"]), int(theirs["Seccomp"]))
        nnp = (int(mine["NoNewPrivs"]), int(theirs["NoNewPrivs"]))
    except (KeyError, ValueError) as exc:
        return _result(FAIL, "STATUS_INCOMPLETE", missing=str(exc)[:40])
    if len(uids) != 4 or len(gids) != 4 or len(my_uids) != 4 or len(my_gids) != 4:
        return _result(FAIL, "STATUS_INCOMPLETE", missing="uid/gid quadruple")
    if set(uids) != {my_uids[0]}:
        return _result(FAIL, "UID_MISMATCH", uids=uids, expected=my_uids[0])
    if set(gids) != {my_gids[0]}:
        return _result(FAIL, "GID_MISMATCH", gids=gids, expected=my_gids[0])
    if groups != my_groups:
        return _result(FAIL, "GROUPS_MISMATCH", extra=sorted(groups - my_groups), missing_groups=sorted(my_groups - groups))
    for key, (own, other) in caps.items():
        if other & ~own:
            return _result(FAIL, "CAPABILITY_EXCEEDS_POLICY", set=key, extra=hex(other & ~own))
    if seccomp[1] != seccomp[0]:
        return _result(FAIL, "SECCOMP_MISMATCH", seccomp=seccomp[1], expected=seccomp[0])
    if nnp[1] < nnp[0]:
        return _result(FAIL, "NO_NEW_PRIVS_DROPPED")
    if my_context:
        if not their_context:
            return _result(FAIL, "SELINUX_CONTEXT_UNREADABLE")
        if their_context != my_context:
            return _result(FAIL, "SELINUX_CONTEXT_MISMATCH", context=their_context[:120])
    return _result(PASS, "CREDENTIALS_MATCH_POLICY", uid=uids[0], gid=gids[0],
                   selinux=my_context or "NOT_APPLICABLE", seccomp=seccomp[1])


def _credentials(pid, proc):
    try:
        mine, theirs = read_status("self", proc=proc), read_status(pid, proc=proc)
    except OSError as exc:
        raise _LayerFail("STATUS_UNREADABLE", error=_errname(exc)) from exc
    try:
        my_context = _selinux_context("self", proc)
    except OSError:
        my_context = None       # no readable LSM context for HG itself: rule not applicable
    their_context = None
    if my_context:
        try:
            their_context = _selinux_context(pid, proc)
        except OSError:
            their_context = None
    return check_credentials(mine, theirs, my_context=my_context, their_context=their_context)


# ---------------------------------------------------------------- L5

def socket_info(fd):
    """Read-only description of a socket descriptor; the descriptor is not consumed."""
    sock = socket.socket(fileno=fd)
    try:
        info = {"family": int(sock.family), "type": int(sock.type),
                "proto": sock.getsockopt(socket.SOL_SOCKET, socket.SO_PROTOCOL),
                "listening": bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)),
                "reuseport": bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT))}
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            name = sock.getsockname()
            info["address"], info["port"] = name[0], name[1]
        return info
    finally:
        sock.detach()


def _is_tcp_listener(info):
    return (info.get("family") in (socket.AF_INET, socket.AF_INET6) and info["type"] == socket.SOCK_STREAM
            and info["proto"] == socket.IPPROTO_TCP and info["listening"])


SHARING_BASIS = ("exclusive among the processes HG could inspect; an uninspected process could hold this socket "
                 "only if Ollama, a same-UID process or root passed it the descriptor (same-UID and root: out of "
                 "scope, owner decision Q3)")


def proc_hidepid(proc="/proc"):
    """The hidepid option of the proc mount (None if absent, "UNKNOWN" if unreadable). With hidepid set,
    other users' processes are not even listed, so no scan of /proc can count them."""
    try:
        with open(f"{proc}/self/mountinfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                left, sep, right = line.partition(" - ")
                fields, tail = left.split(), right.split()
                if sep and len(fields) > 5 and fields[4] == "/proc" and tail[:1] == ["proc"]:
                    options = fields[5].split(",") + (tail[2].split(",") if len(tail) > 2 else [])
                    return next((o.split("=", 1)[1] for o in options if o.startswith("hidepid=")), None)
    except OSError:
        return "UNKNOWN"
    return "UNKNOWN"


def _uid_class(pid, euid, proc):
    # /proc/PID is owned by root when the process is not dumpable (e.g. the Termux app process itself),
    # so the owner of the directory is not the process's UID; the status line is.
    try:
        uid = int(read_status(pid, proc=proc)["Uid"].split()[1])
    except (OSError, KeyError, ValueError, IndexError):
        return "unknown"
    return "same_uid" if uid == euid else "root" if uid == 0 else "other_uid"


def socket_holders(inode, *, exclude=(), proc="/proc"):
    """Which listed processes hold socket `inode`, and how complete that observation is.

    Returns holders (PIDs), uninspectable processes by UID class, descriptors whose link could not be
    read, the proc mount's hidepid option, and scope: ALL_PROCESSES_INSPECTED only when nothing was
    hidden or unreadable and hidepid is off; otherwise PARTIAL. PARTIAL never means "shared"; it means
    exclusivity is shown only among inspected processes (SHARING_BASIS)."""
    target, euid = f"socket:[{inode}]", os.geteuid()
    holders, unreadable = [], 0
    uninspectable = {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 0}
    for name in os.listdir(proc):
        if not name.isdigit() or int(name) in exclude:
            continue
        try:
            entries = os.listdir(f"{proc}/{name}/fd")
        except FileNotFoundError:
            continue
        except PermissionError:
            uninspectable[_uid_class(name, euid, proc)] += 1
            continue
        for entry in entries:
            try:
                link = os.readlink(f"{proc}/{name}/fd/{entry}")
            except FileNotFoundError:
                continue                     # closed while scanning
            except OSError:
                unreadable += 1
                continue
            if link == target:
                holders.append(int(name))
                break
    hidepid = proc_hidepid(proc)
    complete = not any(uninspectable.values()) and not unreadable and hidepid is None
    return {"holders": holders, "uninspectable": uninspectable, "unreadable_descriptors": unreadable,
            "proc_hidepid": hidepid, "scope": "ALL_PROCESSES_INSPECTED" if complete else "PARTIAL"}


def _listener(pid, pidfd, ref, host, port, proc, getfd, hooks, check_capability):
    want = ip_address(host)
    try:
        if not _same_ns("net", pid, proc):
            raise _LayerFail("NETNS_MISMATCH")
    except OSError as exc:
        raise _LayerFail("NETNS_UNREADABLE", error=_errname(exc)) from exc
    if check_capability:
        cap = capability()
        if cap["status"] != PASS:
            raise _LayerFail(cap["code"], status=BLOCKED)
    try:
        fds = sorted(int(n) for n in os.listdir(f"{proc}/{pid}/fd") if n.isdigit())
    except OSError as exc:
        raise _LayerFail("FD_TABLE_UNREADABLE", error=_errname(exc)) from exc
    matches, unexpected, raced = [], [], 0
    for number in fds:
        try:
            link = os.readlink(f"{proc}/{pid}/fd/{number}")
        except FileNotFoundError:
            raced += 1
            continue
        except OSError as exc:
            raise _LayerFail("FD_TABLE_UNREADABLE", error=_errname(exc)) from exc
        found = _SOCKET_RE.fullmatch(link)
        if not found:
            continue
        inode = int(found.group(1))
        hooks("before_getfd", number)
        try:
            dup = getfd(pidfd, number)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                raced += 1
                continue
            if exc.errno == errno.ESRCH:
                raise _LayerFail("PROCESS_EXITED") from exc
            if exc.errno in (errno.EPERM, errno.EACCES, errno.ENOSYS):
                raise _LayerFail("PIDFD_GETFD_" + _errname(exc), status=BLOCKED) from exc
            raise _LayerFail("PIDFD_GETFD_" + _errname(exc)) from exc
        try:
            dst = os.fstat(dup)
            if not stat.S_ISSOCK(dst.st_mode) or dst.st_ino != inode:
                raced += 1                    # descriptor closed and reused between listing and getfd
                continue
            try:
                info = socket_info(dup)
            except OSError:
                continue                      # a socket family Python cannot describe: not TCP
        finally:
            os.close(dup)
        if not _is_tcp_listener(info) or info.get("port") != port:
            continue
        record = {"fd": number, "inode": inode, "address": info["address"], "port": port,
                  "reuseport": info["reuseport"]}
        if ip_address(info["address"]) == want:
            matches.append(record)
        else:
            unexpected.append(record)
    if unexpected:
        raise _LayerFail("UNEXPECTED_BIND_ON_PORT", binds=sorted({u["address"] for u in unexpected}))
    # Listeners are sockets, not descriptors: dup() gives one socket several descriptors (same inode).
    sockets = {}
    for record in matches:
        sockets.setdefault(record["inode"], []).append(record)
    if not sockets:
        raise _LayerFail("NO_LISTENER", inspected_fds=len(fds), raced=raced)
    if len(sockets) > 1:
        raise _LayerFail("MULTIPLE_LISTENERS", count=len(sockets))
    (inode, records), = sockets.items()
    numbers = sorted(r["fd"] for r in records)
    match = {"fd": numbers[0], "fds": numbers, "inode": inode, "address": records[0]["address"], "port": port}
    if any(r["reuseport"] for r in records):
        raise _LayerFail("REUSEPORT_SET")
    try:
        sharing = socket_holders(inode, exclude={pid, os.getpid()}, proc=proc)
    except OSError as exc:
        raise _LayerFail("PROC_SCAN_FAILED", error=_errname(exc)) from exc
    if sharing["holders"]:
        raise _LayerFail("LISTENER_SHARED", holders=sharing["holders"][:8])
    try:
        now = read_stat(pid, proc=proc)
    except (OSError, ValueError) as exc:
        raise _LayerFail("PROCESS_EXITED") from exc
    if now.starttime != ref.starttime or _exited(pidfd):
        raise _LayerFail("PID_REUSED_OR_EXITED")
    sharing.pop("holders")
    sharing["basis"] = SHARING_BASIS
    return match, _result(PASS, "LISTENER_OWNED", fd=match["fd"], fds=numbers, inode=inode, address=match["address"],
                          port=port, sharing=sharing, raced_descriptors=raced)


# ---------------------------------------------------------------- orchestration

class Attestation:
    """Result of attest(); keeps the pidfd open so reverify() can bracket a model call."""

    def __init__(self, service_dir, host, port, proc, getfd, expected_name):
        self.service_dir, self.host, self.port, self.proc = service_dir, host, port, proc
        self._getfd, self.expected_name = getfd, expected_name
        self.layers = {name: _result(UNVERIFIED, "NOT_REACHED") for name in LAYERS}
        self.pid = self.starttime = self.exe = self.listener = self.pidfd = None
        self.started_at = time.time()

    @property
    def status(self):
        states = [layer["status"] for layer in self.layers.values()]
        if all(s == PASS for s in states):
            return VERIFIED_LISTENER
        for status in (FAIL, BLOCKED):
            if status in states:
                return status
        return UNVERIFIED

    @property
    def verified(self):
        return self.status == VERIFIED_LISTENER

    def report(self):
        return {"status": self.status, "pid": self.pid, "host": self.host, "port": self.port,
                "layers": self.layers, "attested_at": self.started_at}

    def reverify(self):
        """Re-check after the caller's exchange; True only if nothing observable changed."""
        if not self.verified or self.pidfd is None:
            return _result(FAIL, "NOT_VERIFIED")
        try:
            pid, _ = read_supervised_pid(self.service_dir)
            if pid != self.pid:
                return _result(FAIL, "SERVICE_RESTARTED")
            if _exited(self.pidfd) or read_stat(pid, proc=self.proc).starttime != self.starttime:
                return _result(FAIL, "PROCESS_EXITED")
            exe = os.stat(f"{self.proc}/{pid}/exe")
            if (exe.st_dev, exe.st_ino) != self.exe:
                return _result(FAIL, "EXEC_SINCE_ATTESTATION")
            info, replaced = None, False
            for number in self.listener["fds"]:      # any descriptor of the recorded socket will do
                try:
                    dup = self._getfd(self.pidfd, number)
                except OSError as exc:
                    if exc.errno == errno.EBADF:
                        continue
                    raise
                try:
                    if os.fstat(dup).st_ino != self.listener["inode"]:
                        replaced = True
                        continue
                    info = socket_info(dup)
                    break
                finally:
                    os.close(dup)
            if info is None:
                return _result(FAIL, "LISTENER_REPLACED" if replaced else "LISTENER_GONE")
            if not _is_tcp_listener(info) or (info.get("address"), info.get("port")) != (
                    self.listener["address"], self.port):
                return _result(FAIL, "LISTENER_GONE")
        except _LayerFail as exc:
            return _result(FAIL, exc.code)
        except (OSError, ValueError) as exc:
            return _result(FAIL, "REVERIFY_ERROR", error=_errname(exc))
        return _result(PASS, "SAME_PROCESS_SAME_LISTENER")

    def close(self):
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def attest(service_dir, *, host="127.0.0.1", port=11434, expected_name="ollama", anchors=None, proc="/proc",
           getfd=pidfd_getfd, check_capability=True, _hooks=None):
    """Run L1..L5. L1 or L2 not passing stops the run (there is no trustworthy process to look at);
    L3 and L4 are recorded and L5 still runs, so one read-only run yields evidence for every layer.
    The overall status stays fail-closed: VERIFIED_LISTENER only if all five PASS.

    `anchors` and `_hooks` are test seams; production callers leave them unset so the anchor comes
    from the release file."""
    hooks = _hooks or _Hooks()
    att = Attestation(str(service_dir), host, int(port), proc, getfd, expected_name)
    try:
        ip_address(host)
    except ValueError:
        att.layers["L1_supervision"] = _result(FAIL, "HOST_NOT_NUMERIC_IP")
        return att

    def run(layer, step):
        try:
            return step()
        except _LayerFail as exc:
            att.layers[layer] = _result(exc.status, exc.code, **exc.evidence)
            return None

    def supervision():
        att.pidfd, ref, att.layers["L1_supervision"] = _supervision(att.service_dir, proc, hooks)
        att.pid, att.starttime = ref.pid, ref.starttime
        return ref

    ref = run("L1_supervision", supervision)
    if ref is None:
        return att
    identity = run("L2_identity", lambda: _identity(att.pid, att.pidfd, ref, expected_name, proc, hooks))
    if identity is None:
        return att
    att.exe, digest, att.layers["L2_identity"] = identity

    def integrity():
        try:
            entries = load_trust_anchor() if anchors is None else anchors
        except AnchorError as exc:
            raise _LayerFail("TRUST_ANCHOR_INVALID", detail=str(exc)) from exc
        att.layers["L3_integrity"] = _integrity(expected_name, digest, entries)
        return True

    def credentials():
        att.layers["L4_credentials"] = _credentials(att.pid, proc)
        return True

    def listener():
        att.listener, att.layers["L5_listener"] = _listener(att.pid, att.pidfd, ref, host, att.port, proc, getfd,
                                                            hooks, check_capability)
        return True

    run("L3_integrity", integrity)
    run("L4_credentials", credentials)
    run("L5_listener", listener)
    return att


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hg.assistant.attest",
                                     description="Attest the runit-supervised Ollama listener (read-only).")
    parser.add_argument("--service-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--reverify-after", type=float, default=None, metavar="SECONDS",
                        help="hold the attestation, wait, then run the post-check")
    args = parser.parse_args(argv)
    with attest(args.service_dir, host=args.host, port=args.port) as att:
        report = att.report()
        report["capability"] = capability()
        if args.reverify_after is not None and att.verified:
            time.sleep(max(0.0, args.reverify_after))
            report["reverify"] = att.reverify()
        print(json.dumps(report, sort_keys=True, default=str))
        ok = att.verified and report.get("reverify", {"status": PASS})["status"] == PASS
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
