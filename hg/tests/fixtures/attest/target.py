"""Attestation test target: a real process that holds (or does not hold) sockets.

Run by a copy of the interpreter named `ollama`, so /proc/PID/exe carries that name.
argv: MODE READY_FILE. Environment: TARGET_PORT (0 = ephemeral), TARGET_USR1 (close|exec|reuse).
Only loopback addresses are ever bound; the port is ephemeral unless the test fixes it.
"""
import json
import os
import signal
import socket
import sys
import time

mode, ready = sys.argv[1], sys.argv[2]
port = int(os.environ.get("TARGET_PORT", "0"))
socks, children = [], []
if os.environ.get("TARGET_PTRACER_ANY") == "1":
    # Yama (ptrace_scope=1) lets only ancestors attach; this exception lets a non-ancestor attester in.
    import ctypes
    try:
        ctypes.CDLL(None, use_errno=True).prctl(0x59616D61, ctypes.c_ulong(2 ** 64 - 1), 0, 0, 0)
    except (OSError, AttributeError):
        pass


def tcp(addr="127.0.0.1", port=0, listen=True, reuseport=False):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if reuseport:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind((addr, port))
    if listen:
        s.listen(16)
    socks.append(s)
    return s


main = None
if mode == "listen":
    main = tcp(port=port)
elif mode == "bound":
    main = tcp(port=port, listen=False)
elif mode == "udp":
    main = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    main.bind(("127.0.0.1", port))
    socks.append(main)
elif mode == "wildcard":
    main = tcp("0.0.0.0", port)
elif mode == "reuseport1":
    main = tcp(port=port, reuseport=True)
elif mode == "reuseport2":
    main = tcp(port=port, reuseport=True)
    tcp(port=main.getsockname()[1], reuseport=True)
elif mode == "two-loopback":
    main = tcp(port=port)
    tcp("127.0.0.2", main.getsockname()[1])
elif mode == "shared":
    main = tcp(port=port)
    child = os.fork()
    if child == 0:                      # keeps the inherited listening socket open
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        time.sleep(3600)
        os._exit(0)
    children.append(child)
elif mode != "none":
    raise SystemExit(f"unknown mode {mode}")


def on_usr1(*_):
    action = os.environ.get("TARGET_USR1", "")
    if action == "close":
        for s in socks:
            s.close()
    elif action == "exec":
        for path in ("/bin/sleep", "/usr/bin/sleep"):
            if os.path.exists(path):
                os.execv(path, [path, "3600"])
    elif action == "reuse" and main is not None:
        fd = main.fileno()
        other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        other.bind(("127.0.0.1", 0))
        os.dup2(other.fileno(), fd)     # same descriptor number, different socket
        other.close()


def on_term(*_):
    for child in children:
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
    os._exit(0)


signal.signal(signal.SIGUSR1, on_usr1)
signal.signal(signal.SIGTERM, on_term)
doc = {"pid": os.getpid(), "port": main.getsockname()[1] if main is not None else 0,
       "fd": main.fileno() if main is not None else -1, "children": children}
with open(ready + ".tmp", "w", encoding="utf-8") as stream:
    json.dump(doc, stream)
os.replace(ready + ".tmp", ready)
while True:
    signal.pause()
