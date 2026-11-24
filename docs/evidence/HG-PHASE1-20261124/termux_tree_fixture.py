"""Exercise runit tree loss and manual recovery without signalling live services."""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def sv(path):
    out = subprocess.run(["sv", "status", str(path)], capture_output=True, text=True).stdout
    return out.strip()


def child_pid(service):
    match = re.match(r"^run: .*? \(pid (\d+)\)", sv(service))
    return int(match.group(1)) if match else None


def wait_for(check, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise RuntimeError("staging state did not become observable")


def fenced_signal(proc, directory, sig, pid=None):
    raw = (Path("/proc") / str(proc.pid) / "cmdline").read_bytes().split(b"\0")
    assert Path(os.fsdecode(raw[0])).name == "runsvdir" and os.fsencode(directory) in raw
    assert os.getpgid(proc.pid) == proc.pid and os.getpgrp() != proc.pid
    if pid is not None:
        assert os.getpgid(pid) == proc.pid
        os.kill(pid, sig)
    else:
        os.killpg(proc.pid, sig)


def run(target, report):
    stage = Path(target).resolve()
    home = Path.home().resolve()
    assert stage.parent == home / "hg-evidence" / "HG-PHASE1-20261124"
    stage.mkdir(mode=0o700)
    svdir = stage / "service"
    service = svdir / "phase1-dummy"
    service.mkdir(parents=True)
    proc_run = service / "run"
    shell = shutil.which("sh")
    sleep = shutil.which("sleep")
    proc_run.write_text(f"#!{shell}\nexec {sleep} 120\n")
    proc_run.chmod(0o700)
    prod = Path(os.environ["PREFIX"]) / "var/service"
    production_before = {name: sv(prod / name).split("s;")[0].split(")")[0]
                         for name in ("hg-runtime", "ollama", "desktop-commander-watchdog")}
    log = (stage / "fixture.log").open("w")
    procs = []

    def start():
        proc = subprocess.Popen(["runsvdir", str(svdir)], cwd=stage, stdout=log, stderr=log,
                                start_new_session=True)
        procs.append(proc)
        return proc

    result = {}
    try:
        first = start()
        old = wait_for(lambda: child_pid(service))
        fenced_signal(first, svdir, signal.SIGKILL, old)
        new = wait_for(lambda: (pid if (pid := child_pid(service)) != old else None))
        assert first.poll() is None
        result["isolated_child_restarted"] = {"supervisor": first.pid, "before": old, "after": new}
        fenced_signal(first, svdir, signal.SIGKILL)
        first.wait(timeout=5)
        elapsed = 12
        time.sleep(elapsed)
        assert child_pid(service) is None
        result["isolated_tree_without_trigger"] = {"seconds_without_service": elapsed, "restarted": False}
        replacement = start()
        restored = wait_for(lambda: child_pid(service))
        result["manual_external_fixture_start"] = {"supervisor": replacement.pid, "child": restored}
    finally:
        for proc in procs:
            if proc.poll() is None:
                fenced_signal(proc, svdir, signal.SIGKILL)
                proc.wait(timeout=5)
        log.close()
    production_after = {name: sv(prod / name).split("s;")[0].split(")")[0]
                        for name in production_before}
    result["sampled_production_and_watchdog_pids_unchanged"] = production_before == production_after
    result["staging_service_torn_down"] = child_pid(service) is None
    result["android_wide_recovery"] = "UNVERIFIED; fixture process group only"
    print(json.dumps(result))
    Path(report).write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["sampled_production_and_watchdog_pids_unchanged"] and result["staging_service_torn_down"] else 1


if __name__ == "__main__":
    raise SystemExit(run(*sys.argv[1:]))
