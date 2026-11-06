"""Stand-in for runit's runsv where runit is not installed (tests only; CI runs the real runsv).

Run by a copy of the interpreter named `runsv`. It reproduces only what HG's L1 relies on:
working directory = the service directory, the service process is its direct child (exec'd
argv), supervise/ is 0700, supervise/pid is written as "PID\\n" by rename (0644) and emptied
when the child is down, and the child is restarted after it exits. SIGTERM stops both.
argv: SERVICE_DIR PROGRAM [ARGS...]
"""
import os
import signal
import sys
import time

service, argv = sys.argv[1], sys.argv[2:]
os.chdir(service)
os.makedirs("supervise", mode=0o700, exist_ok=True)
state = {"stop": False, "child": 0}


def write_pid(text):
    with open("supervise/pid.new", "w", encoding="ascii") as stream:
        stream.write(text)
    os.chmod("supervise/pid.new", 0o644)
    os.replace("supervise/pid.new", "supervise/pid")


def on_term(*_):
    state["stop"] = True
    if state["child"]:
        try:
            os.kill(state["child"], signal.SIGTERM)
        except ProcessLookupError:
            pass


signal.signal(signal.SIGTERM, on_term)
while not state["stop"]:
    child = os.fork()
    if child == 0:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.execv(argv[0], argv)
    state["child"] = child
    write_pid(f"{child}\n")
    os.waitpid(child, 0)
    state["child"] = 0
    write_pid("")
    if not state["stop"]:
        time.sleep(0.3)
