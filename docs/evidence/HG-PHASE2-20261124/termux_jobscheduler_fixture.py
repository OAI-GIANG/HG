"""One-shot Termux:API probe. Only the new staging service may be started or stopped."""
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def call(*args, timeout=10):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def child(service):
    status = call("sv", "status", str(service)).stdout
    found = re.match(r"^run: .*? \(pid (\d+)\)", status)
    return int(found[1]) if found else None


def wait_for(check, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.3)
    return None


def verify(pid, svdir):
    args = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    assert Path(os.fsdecode(args[0])).name == "runsvdir"
    assert os.fsencode(svdir) in args


def main(folder):
    stage = Path(folder).resolve()
    assert stage.parent == Path.home() / "hg-evidence/HG-PHASE2-20261124"
    stage.mkdir(mode=0o700)
    svdir = stage / "services"
    service = svdir / "phase2-dummy"
    service.mkdir(parents=True)
    quoted = shlex.quote
    sh = shutil.which("sh")
    runsvdir = shutil.which("runsvdir")
    daemon = shutil.which("start-stop-daemon")
    sleep = shutil.which("sleep")
    assert all((sh, runsvdir, daemon, sleep))
    (service / "run").write_text(f"#!{sh}\nexec {quoted(sleep)} 120\n")
    (service / "run").chmod(0o700)

    fired = stage / "dispatch"
    pidfile = stage / "job-staging.pid"
    job = stage / "staging-job.sh"
    job.write_text(
        f"#!{sh}\nset -eu\numask 077\n"
        f"mkdir {quoted(str(fired))}\n"
        f"date -u +%FT%TZ > {quoted(str(fired / 'started-utc'))}\n"
        f"exec {quoted(daemon)} -S -b -m -p {quoted(str(pidfile))} -x {quoted(runsvdir)}"
        f" -d {quoted(str(stage))} -- {quoted(str(svdir))}\n"
    )
    job.chmod(0o700)
    job_id = str(30000 + secrets.randbelow(20000))
    result = {"job_id": job_id, "attempt": "one-shot fixture only",
              "android_app_wide_recovery_proven": False}
    scheduled = False
    before = call("termux-job-scheduler", "-p")
    result["initial_jobs"] = before.stdout.strip() or before.stderr.strip()
    if before.returncode or result["initial_jobs"] != "No jobs found":
        result["status"] = "STOPPED: baseline jobs could not be ruled out"
        return write_result(stage, result)

    runtime = Path(os.environ["PREFIX"]) / "var/service"
    names = ("hg-runtime", "ollama", "desktop-commander-watchdog")

    def prod():
        return {name: child(runtime / name) for name in names}

    prod_before = prod()
    with (stage / "first-supervisor.log").open("w") as log:
        original = subprocess.Popen([runsvdir, str(svdir)], start_new_session=True,
                                    stdout=log, stderr=log, cwd=stage)
        try:
            old = wait_for(lambda: child(service), 12)
            assert old
            verify(original.pid, svdir)
            assert os.getpgid(original.pid) == original.pid == os.getpgid(old)
            assert os.getpgrp() != original.pid
            os.killpg(original.pid, signal.SIGKILL)
            original.wait(timeout=5)
            wait_for(lambda: not child(service), 6)
            assert not child(service) and not fired.exists()
            result["isolated_tree_stopped_before_schedule"] = True
            try:
                schedule = call("termux-job-scheduler", "-s", str(job), "--job-id", job_id,
                                "--period-ms", "0", "--network", "none",
                                "--battery-not-low", "false")
            except subprocess.TimeoutExpired:
                scheduled = True
                result["schedule_exit"] = "TIMEOUT"
            else:
                scheduled = True
                result["schedule_exit"] = schedule.returncode
                result["schedule_message"] = (schedule.stdout + schedule.stderr).strip()[:300]
                if not schedule.returncode:
                    restored = wait_for(lambda: child(service) if fired.is_dir() and pidfile.is_file() else None, 55)
                    if restored:
                        replacement = int(pidfile.read_text())
                        verify(replacement, svdir)
                        assert replacement != original.pid and restored != old
                        result["fixture_restarted_by_job"] = True
                        result["new_supervisor"] = replacement
                        result["new_child"] = restored
            if not result.get("fixture_restarted_by_job"):
                result["fixture_restarted_by_job"] = False
                result["dispatch_marker_seen"] = fired.is_dir()
        finally:
            if scheduled:
                cancel = call("termux-job-scheduler", "--cancel", "--job-id", job_id)
                result["cancel_request_exit"] = cancel.returncode
                pending = call("termux-job-scheduler", "-p")
                result["final_jobs"] = (pending.stdout + pending.stderr).strip()[:300]
            if original.poll() is None:
                verify(original.pid, svdir)
                assert os.getpgid(original.pid) == original.pid
                os.killpg(original.pid, signal.SIGKILL)
                original.wait(timeout=5)
            if pidfile.is_file():
                replacement = int(pidfile.read_text())
                if (Path("/proc") / str(replacement) / "cmdline").exists():
                    verify(replacement, svdir)
                    call("sv", "-w", "5", "down", str(service))
                    os.kill(replacement, signal.SIGTERM)
                    call("sv", "exit", str(service))
    result["production_and_watchdog_pids_match"] = prod() == prod_before
    result["staging_service_down_after_probe"] = child(service) is None
    return write_result(stage, result)


def write_result(stage, result):
    data = json.dumps(result, indent=2) + "\n"
    (stage / "job-result.json").write_text(data)
    print(data, flush=True)
    return 0 if result.get("fixture_restarted_by_job") and result.get("production_and_watchdog_pids_match") and result.get("staging_service_down_after_probe") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
