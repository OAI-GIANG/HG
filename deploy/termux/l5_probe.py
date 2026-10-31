#!/usr/bin/env python3
"""HG L5 capability probe: can this device prove which process owns a listening socket?

Standalone (Python 3.9+, standard library only, imports nothing from HG). Read-only towards every
process it did not start itself. Spec: docs/architecture/HG_LISTENER_ATTESTATION_V2.md section 6.

  python3 -I -S l5_probe.py                       # self-test with a private child (ephemeral port)
  python3 -I -S l5_probe.py --target-pid PID      # inspect a running process, e.g. Ollama
            [--expect 127.0.0.1:11434]
  [--timeout SECONDS] [--out FILE]                # FILE gets the same JSON plus its SHA-256 on stderr

Self-test: a child started from this file binds only loopback sockets on ephemeral ports (TCP
LISTEN, TCP bound-not-listening, UDP, a socketpair). The parent duplicates each one with
pidfd_getfd(2) and checks inode, SO_DOMAIN/SO_TYPE/SO_PROTOCOL, SO_ACCEPTCONN, SO_REUSEPORT and
getsockname; then a descriptor swap race, a closed descriptor and an exited child.
Target mode never signals, writes to, accepts on or shuts down anything: duplicated descriptors are
only inspected and closed (closing our duplicate does not affect the target's socket).
Every syscall is first tried in a throwaway child, because a seccomp filter that traps it kills the
caller with SIGSYS.

Exit: 0 every check passed / expected listener found; 2 the platform blocks the capability;
1 an expectation failed; 3 usage or environment error.
"""
import ctypes
import errno
import hashlib
import json
import os
import platform
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time

SYS_PIDFD_GETFD = 438            # unified syscall table: same number on arm64 and x86_64
PROBE_VERSION = "hg-l5-probe-1"
SOCKET_LINK = re.compile(r"socket:\[([0-9]+)\]")


def errname(err):
    return errno.errorcode.get(err, str(err))


def libc():
    for name in (None, "libc.so", "libc.so.6"):
        try:
            lib = ctypes.CDLL(name, use_errno=True)
            lib.syscall.restype = ctypes.c_long
            return lib
        except (OSError, AttributeError):
            continue
    raise OSError(errno.ENOSYS, "no libc syscall()")


def pidfd_getfd(pidfd, fd):
    res = libc().syscall(ctypes.c_long(SYS_PIDFD_GETFD), ctypes.c_long(pidfd), ctypes.c_long(fd), ctypes.c_long(0))
    if res < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(res)


def read_text(path, limit=65536):
    try:
        with open(path, "rb") as stream:
            return stream.read(limit).decode("utf-8", "replace")
    except OSError as exc:
        return {"error": errname(exc.errno)}


def starttime(pid):
    raw = read_text(f"/proc/{pid}/stat")
    if isinstance(raw, dict):
        return None
    return int(raw[raw.rfind(")") + 1:].split()[19])


def status_fields(pid):
    raw = read_text(f"/proc/{pid}/status")
    if isinstance(raw, dict):
        return raw
    keep = ("Uid", "Gid", "Groups", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs", "Seccomp")
    return {k: v.strip() for k, _, v in (line.partition(":") for line in raw.splitlines()) if k in keep}


def getprop(name):
    try:
        done = subprocess.run(["getprop", name], capture_output=True, timeout=5, check=False)
        return done.stdout.decode("utf-8", "replace").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def environment():
    selinux = read_text("/proc/self/attr/current", 4096)
    proc_net = {}
    for name in ("tcp", "tcp6"):
        got = read_text(f"/proc/net/{name}", 4096)
        proc_net[name] = "unreadable:" + got["error"] if isinstance(got, dict) else "readable"
    return {"probe": PROBE_VERSION, "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kernel": platform.release(), "machine": platform.machine(), "python": platform.python_version(),
            "uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(), "groups": os.getgroups(),
            "selinux": selinux.rstrip("\0\n") if isinstance(selinux, str) else selinux,
            "status": status_fields("self"),
            "yama_ptrace_scope": (read_text("/proc/sys/kernel/yama/ptrace_scope") if
                                  os.path.exists("/proc/sys/kernel/yama/ptrace_scope") else "absent"),
            "android": {"release": getprop("ro.build.version.release"), "sdk": getprop("ro.build.version.sdk"),
                        "abi": getprop("ro.product.cpu.abi"), "security_patch": getprop("ro.build.version.security_patch")},
            "termux": "com.termux" in os.environ.get("PREFIX", ""),
            "proc_net": proc_net, "python_has_pidfd_open": hasattr(os, "pidfd_open")}


SYSCALL_CHILD = r"""
import ctypes, os, sys
lib = ctypes.CDLL(None, use_errno=True); lib.syscall.restype = ctypes.c_long
try:
    pidfd = os.pidfd_open(os.getpid())
except AttributeError:
    print("pidfd_open:NO_PYTHON_SUPPORT"); sys.exit(4)
except OSError as exc:
    print("pidfd_open:%d" % exc.errno); sys.exit(4)
fd = lib.syscall(ctypes.c_long(438), ctypes.c_long(pidfd), ctypes.c_long(0), ctypes.c_long(0))
if fd < 0:
    print("pidfd_getfd:%d" % ctypes.get_errno()); sys.exit(3)
print("ok")
"""


def syscall_check():
    done = subprocess.run([sys.executable, "-I", "-S", "-c", SYSCALL_CHILD], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20, check=False)
    out = done.stdout.decode("ascii", "replace").strip()
    if done.returncode == 0:
        return {"status": "AVAILABLE"}
    if done.returncode == -signal.SIGSYS:
        return {"status": "BLOCKED", "code": "SECCOMP_SIGSYS"}
    call, _, num = out.partition(":")
    if num.isdigit():
        return {"status": "BLOCKED", "code": f"{call.upper()}_{errname(int(num))}"}
    return {"status": "BLOCKED", "code": "UNEXPECTED", "returncode": done.returncode, "output": out[:200]}


def describe(fd):
    sock = socket.socket(fileno=fd)
    try:
        info = {"family": sock.family.name if hasattr(sock.family, "name") else int(sock.family),
                "type": sock.type.name if hasattr(sock.type, "name") else int(sock.type),
                "proto": sock.getsockopt(socket.SOL_SOCKET, socket.SO_PROTOCOL),
                "listening": bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)),
                "reuseport": bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT))}
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            name = sock.getsockname()
            info.update(address=name[0], port=name[1], port_hex=f"{name[1]:04X}")
        return info
    finally:
        sock.detach()


def inspect(pid, pidfd, before_getfd=None):
    """Duplicate and describe every socket descriptor of `pid`. Read-only."""
    rows, errors = [], []
    for name in sorted(os.listdir(f"/proc/{pid}/fd"), key=lambda n: int(n) if n.isdigit() else -1):
        if not name.isdigit():
            continue
        try:
            link = os.readlink(f"/proc/{pid}/fd/{name}")
        except OSError as exc:
            errors.append({"fd": int(name), "stage": "readlink", "errno": errname(exc.errno)})
            continue
        found = SOCKET_LINK.fullmatch(link)
        if not found:
            continue
        number, inode = int(name), int(found.group(1))
        if before_getfd:
            before_getfd(number)
        try:
            dup = pidfd_getfd(pidfd, number)
        except OSError as exc:
            errors.append({"fd": number, "stage": "pidfd_getfd", "errno": errname(exc.errno)})
            continue
        try:
            st = os.fstat(dup)
            row = {"fd": number, "inode_listed": inode, "inode_dup": st.st_ino,
                   "consistent": stat.S_ISSOCK(st.st_mode) and st.st_ino == inode}
            try:
                row.update(describe(dup))
            except OSError as exc:
                row["describe_error"] = errname(exc.errno)
            rows.append(row)
        finally:
            os.close(dup)
    return rows, errors


def proc_hidepid():
    """hidepid of the /proc mount: None if absent, "UNKNOWN" if unreadable (then other users' processes
    may not even be listed)."""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                left, sep, right = line.partition(" - ")
                fields, tail = left.split(), right.split()
                if sep and len(fields) > 5 and fields[4] == "/proc" and tail[:1] == ["proc"]:
                    options = fields[5].split(",") + (tail[2].split(",") if len(tail) > 2 else [])
                    return next((o.split("=", 1)[1] for o in options if o.startswith("hidepid=")), None)
    except OSError:
        return "UNKNOWN"
    return "UNKNOWN"


def holders(inode, exclude):
    """Holders of socket `inode` among listed processes, plus the limits of that observation:
    uninspectable processes by UID class (from the status Uid line: /proc/PID of a non-dumpable process
    is owned by root), unreadable descriptors, hidepid. scope PARTIAL means exclusivity is shown only
    among inspected processes."""
    euid, found, unreadable = os.geteuid(), [], 0
    uninspectable = {"same_uid": 0, "root": 0, "other_uid": 0, "unknown": 0}
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in exclude:
            continue
        try:
            entries = os.listdir(f"/proc/{name}/fd")
        except PermissionError:
            status = status_fields(name)
            try:
                uid = int(status["Uid"].split()[1])
                kind = "same_uid" if uid == euid else "root" if uid == 0 else "other_uid"
            except (KeyError, ValueError, IndexError, TypeError):
                kind = "unknown"
            uninspectable[kind] += 1
            continue
        except OSError:
            continue
        for entry in entries:
            try:
                link = os.readlink(f"/proc/{name}/fd/{entry}")
            except FileNotFoundError:
                continue
            except OSError:
                unreadable += 1
                continue
            if link == f"socket:[{inode}]":
                found.append(int(name))
                break
    hidepid = proc_hidepid()
    complete = not any(uninspectable.values()) and not unreadable and hidepid is None
    return found, {"uninspectable": uninspectable, "unreadable_descriptors": unreadable, "proc_hidepid": hidepid,
                   "scope": "ALL_PROCESSES_INSPECTED" if complete else "PARTIAL"}


def exited(pidfd):
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(0))


# ------------------------------------------------------------------ self-test

def child_main():
    """Private child: loopback sockets on ephemeral ports, commands on stdin."""
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(4)
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.bind(("127.0.0.1", 0))
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    pair = socket.socketpair()
    print(json.dumps({"pid": os.getpid(), "listener_fd": tcp.fileno(), "port": tcp.getsockname()[1],
                      "bound_fd": bound.fileno(), "udp_fd": udp.fileno(), "pair_fd": pair[0].fileno()}), flush=True)
    for line in sys.stdin:
        command = line.strip()
        if command == "swap":
            other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            other.bind(("127.0.0.1", 0))
            os.dup2(other.fileno(), tcp.fileno())
            other.close()
            print("swapped", flush=True)
        elif command == "close-bound":
            bound.close()
            print("closed", flush=True)
        elif command == "exit":
            break
    return 0


def self_test(report):
    checks = report["checks"] = {}
    child = subprocess.Popen([sys.executable, "-I", "-S", os.path.abspath(__file__), "--child"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    pidfd = None
    try:
        info = json.loads(child.stdout.readline())
        report["child"] = info
        pid = info["pid"]
        t0 = starttime(pid)
        pidfd = os.pidfd_open(pid)
        checks["pid_reuse_guard"] = t0 is not None and starttime(pid) == t0 and not exited(pidfd)
        rows, errors = inspect(pid, pidfd)
        report["sockets"], report["errors"] = rows, errors
        by_fd = {row["fd"]: row for row in rows}
        lst = by_fd.get(info["listener_fd"], {})
        checks["all_descriptors_duplicated"] = not errors and {info["listener_fd"], info["bound_fd"], info["udp_fd"],
                                                               info["pair_fd"]} <= set(by_fd)
        checks["inode_consistent"] = bool(rows) and all(row["consistent"] for row in rows)
        checks["tcp_listener_identified"] = (lst.get("family") == "AF_INET" and lst.get("type") == "SOCK_STREAM"
                                             and lst.get("proto") == socket.IPPROTO_TCP and lst.get("listening") is True
                                             and lst.get("address") == "127.0.0.1" and lst.get("port") == info["port"]
                                             and lst.get("reuseport") is False)
        checks["bound_not_listening"] = by_fd.get(info["bound_fd"], {}).get("listening") is False
        checks["udp_not_listening"] = (by_fd.get(info["udp_fd"], {}).get("type") == "SOCK_DGRAM"
                                       and by_fd.get(info["udp_fd"], {}).get("listening") is False)
        checks["exactly_one_tcp_listener"] = sum(1 for row in rows if row.get("listening")
                                                 and row.get("type") == "SOCK_STREAM") == 1
        found, sharing = holders(lst.get("inode_dup", -1), exclude={pid, os.getpid()})
        checks["listener_not_shared"] = not found
        report["sharing"] = sharing

        def swap(number):                     # close + reuse the descriptor between listing and getfd
            if number == info["listener_fd"]:
                child.stdin.write("swap\n")
                child.stdin.flush()
                child.stdout.readline()

        raced, _ = inspect(pid, pidfd, before_getfd=swap)
        swapped = next((row for row in raced if row["fd"] == info["listener_fd"]), {})
        checks["fd_reuse_race_detected"] = swapped.get("consistent") is False and not swapped.get("listening")
        child.stdin.write("close-bound\n")
        child.stdin.flush()
        child.stdout.readline()
        try:
            os.close(pidfd_getfd(pidfd, info["bound_fd"]))
            checks["closed_descriptor_ebadf"] = False
        except OSError as exc:
            checks["closed_descriptor_ebadf"] = exc.errno == errno.EBADF
        child.stdin.write("exit\n")
        child.stdin.flush()
        child.wait(10)
        checks["exit_seen_by_pidfd"] = exited(pidfd)
        try:
            os.close(pidfd_getfd(pidfd, 0))
            report["after_exit_errno"] = "none"
            checks["exited_child_refused"] = False
        except OSError as exc:
            report["after_exit_errno"] = errname(exc.errno)
            checks["exited_child_refused"] = exc.errno in (errno.ESRCH, errno.EBADF)
    finally:
        if pidfd is not None:
            os.close(pidfd)
        if child.poll() is None:
            child.kill()
            child.wait(5)
    return 0 if all(checks.values()) else 1


def target(report, pid, expect):
    host, _, port = expect.rpartition(":")
    host, port = host.strip("[]"), int(port)
    report["expect"] = {"address": host, "port": port, "port_hex": f"{port:04X}"}
    exe = None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError as exc:
        exe = {"error": errname(exc.errno)}
    report["target"] = {"pid": pid, "exe": exe, "status": status_fields(pid),
                        "selinux": read_text(f"/proc/{pid}/attr/current", 4096)}
    t0 = starttime(pid)
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as exc:
        report["result"] = {"status": "FAIL", "code": "PIDFD_OPEN_" + errname(exc.errno)}
        return 1
    try:
        if t0 is None or starttime(pid) != t0:
            report["result"] = {"status": "FAIL", "code": "PID_REUSED_OR_EXITED"}
            return 1
        try:
            rows, errors = inspect(pid, pidfd)
        except OSError as exc:
            # The fd table is hidden from us; still record what pidfd_getfd itself answers (EPERM =
            # ptrace rules, EACCES = LSM such as SELinux), duplicating descriptor 0 only to close it.
            try:
                os.close(pidfd_getfd(pidfd, 0))
                report["direct_getfd"] = "allowed"
            except OSError as direct:
                report["direct_getfd"] = errname(direct.errno)
            blocked = exc.errno in (errno.EACCES, errno.EPERM)
            report["result"] = {"status": "BLOCKED" if blocked else "FAIL", "code": "FD_TABLE_" + errname(exc.errno)}
            return 2 if blocked else 1
        report["sockets"] = [r for r in rows if r.get("family") in ("AF_INET", "AF_INET6")]
        report["errors"] = errors
        denied = [e for e in errors if e["stage"] == "pidfd_getfd" and e["errno"] in ("EPERM", "EACCES", "ENOSYS")]
        if denied and not rows:
            report["result"] = {"status": "BLOCKED", "code": "PIDFD_GETFD_" + denied[0]["errno"]}
            return 2
        matches = [r for r in rows if r.get("listening") and r.get("type") == "SOCK_STREAM" and r.get("consistent")
                   and r.get("address") == host and r.get("port") == port]
        same_port = [r for r in rows if r.get("listening") and r.get("port") == port and r.get("address") != host]
        sockets = sorted({r["inode_dup"] for r in matches})   # a listener is a socket; dup() adds descriptors
        alive = starttime(pid) == t0 and not exited(pidfd)
        if len(sockets) == 1 and not same_port and not any(r["reuseport"] for r in matches) and alive:
            found, sharing = holders(sockets[0], exclude={pid, os.getpid()})
            report["holders"], report["sharing"] = found, sharing
            if not found:
                report["result"] = {"status": "PASS", "code": "LISTENER_OWNED",
                                    "fd": min(r["fd"] for r in matches), "fds": sorted(r["fd"] for r in matches),
                                    "inode": sockets[0], "sharing_scope": sharing["scope"]}
                return 0
            report["result"] = {"status": "FAIL", "code": "LISTENER_SHARED"}
            return 1
        report["result"] = {"status": "FAIL", "code": "NO_UNIQUE_LISTENER", "listening_sockets": len(sockets),
                            "descriptors": len(matches), "other_binds_on_port": len(same_port), "alive": alive}
        return 1
    finally:
        os.close(pidfd)


def main(argv):
    if argv[:1] == ["--child"]:
        return child_main()
    args = {"--timeout": "60", "--expect": "127.0.0.1:11434"}
    it = iter(argv)
    for arg in it:
        if arg in ("--target-pid", "--expect", "--timeout", "--out"):
            args[arg] = next(it, None)
        else:
            print(__doc__, file=sys.stderr)
            return 3
    if not sys.platform.startswith("linux"):
        print(json.dumps({"result": {"status": "BLOCKED", "code": "NOT_LINUX"}}))
        return 3

    def on_alarm(*_):
        raise TimeoutError("probe timeout")

    signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(int(args["--timeout"]))
    report = {"environment": environment()}
    try:
        report["syscalls"] = syscall_check()
        if report["syscalls"]["status"] != "AVAILABLE" or not hasattr(os, "pidfd_open"):
            report["result"] = {"status": "BLOCKED", "code": report["syscalls"].get("code", "NO_PIDFD_OPEN")}
            code = 2
        elif args.get("--target-pid"):
            code = target(report, int(args["--target-pid"]), args["--expect"])
        else:
            code = self_test(report)
            report["result"] = {"status": "PASS" if code == 0 else "FAIL", "code": "SELF_TEST"}
    except TimeoutError:
        report["result"] = {"status": "FAIL", "code": "TIMEOUT"}
        code = 1
    finally:
        signal.alarm(0)
    text = json.dumps(report, sort_keys=True, default=str)
    print(text)
    if args.get("--out"):
        fd = os.open(args["--out"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
        print("sha256 " + hashlib.sha256((text + "\n").encode("utf-8")).hexdigest() + " " + args["--out"],
              file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
