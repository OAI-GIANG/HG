"""Arm a one-shot Android job, then interrupt only an isolated HG service tree."""
import hashlib
import http.client
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

from termux_jobscheduler_fixture import call, child, verify, wait_for

RELEASE = "95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153"
SOURCE = "40254e60802bc59e40cd739d6ae4081241af4acd"
PORT = 18873


def ready(token):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
    try:
        conn.request("GET", "/v1/health/ready", headers={"Authorization": "Bearer " + token})
        response = conn.getresponse()
        payload = json.loads(response.read())
        if response.status == 200 and payload.get("status") == "READY" and payload.get("release_id") == RELEASE:
            return {key: payload.get(key) for key in ("status","release_id","integrity","trust","idempotency")}
    except (OSError, http.client.HTTPException, ValueError):
        pass
    finally:
        conn.close()
    return None


def port_closed():
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(("127.0.0.1", PORT)) != 0


def result_file(folder, result):
    data = json.dumps(result, indent=2) + "\n"
    (folder / "result.json").write_text(data)
    print(data, flush=True)
    return 0 if result.get("recovered_ready") and result.get("production_pids_unchanged") and result.get("port_closed_after_cleanup") else 1


def main():
    home = Path.home().resolve()
    area = home / "hg-evidence/HG-PHASE2-20261124"
    folder = area / "actual-staging-recovery"
    release_home = home / "hg-staging-phase2-seal-20261124/home"
    root = release_home / "hg-releases" / RELEASE
    manifest = release_home / f".config/hg/releases/{RELEASE}.json"
    assert root.is_dir() and manifest.is_file() and port_closed()
    assert json.loads(manifest.read_bytes())["commit"] == SOURCE
    folder.mkdir(mode=0o700)
    svdir = folder / "services"
    service = svdir / "phase2-hg"
    service.mkdir(parents=True, mode=0o700)
    state = folder / "state"
    state.mkdir(mode=0o700)
    assistant = folder / "assistant"
    assistant.mkdir(mode=0o700)
    token = secrets.token_hex(24)
    token_path = folder / "stage.token"
    token_path.write_text(token + "\n")
    token_path.chmod(0o600)
    config = folder / "stage.json"
    config.write_text(json.dumps({
        "schema": "hg-runtime-service-config-v1", "host": "127.0.0.1", "port": PORT,
        "state_dir": str(state), "token_file": str(token_path), "release_id": RELEASE,
        "release_root": str(root), "release_manifest": str(manifest), "max_body_bytes": 262144,
    }))
    config.chmod(0o600)
    q = shlex.quote
    sh = shutil.which("sh")
    python = sys.executable
    runsvdir = shutil.which("runsvdir")
    daemon = shutil.which("start-stop-daemon")
    assert all((sh, python, runsvdir, daemon))
    run = service / "run"
    run.write_text(f"#!{sh}\nset -eu\numask 077\nexport HG_HOME={q(str(assistant))}\n"
                   f"cd {q(str(root))}\nexec {q(python)} -B -u -m hg serve --config {q(str(config))}\n")
    run.chmod(0o700)
    result = {"candidate": SOURCE, "release": RELEASE, "initial_state": "new isolated state",
              "production_scope": "read-only checks", "full_android_app_stop": "not exercised"}
    existing = call("termux-job-scheduler", "-p")
    if existing.returncode or (existing.stdout + existing.stderr).strip() != "No jobs found":
        result["blocked"] = "existing job list could not be validated"
        return result_file(folder, result)

    services = Path(os.environ["PREFIX"]) / "var/service"

    def sample():
        return {n: child(services / n) for n in ("hg-runtime", "ollama", "desktop-commander-watchdog")}

    prod_before = sample()
    job_id = str(30000 + secrets.randbelow(20000))
    result["job_id"] = job_id
    scheduled = False
    pidfile = folder / "replacement.pid"
    marker = folder / "job-entered-utc"
    restarted = folder / "loss-observed-utc"
    with (folder / "supervisor.log").open("w") as log:
        original = subprocess.Popen([runsvdir, str(svdir)], start_new_session=True, cwd=folder,
                                    stdout=log, stderr=log)
        try:
            initial = wait_for(lambda: ready(token), 40)
            assert initial is not None, "isolated HG did not become READY"
            result["initial_ready"] = initial
            old_child = child(service)
            assert old_child and os.getpgid(old_child) == original.pid == os.getpgid(original.pid)
            verify(original.pid, svdir)
            job = folder / "recover.sh"
            job.write_text(
                f"#!{sh}\nset -eu\numask 077\n"
                f"date -u +%FT%TZ > {q(str(marker))}\n"
                f"i=0\nwhile [ -r /proc/{original.pid}/cmdline ] && [ \"$i\" -lt 45 ]; do\n"
                "  sleep 1\n  i=$((i+1))\ndone\n"
                f"[ ! -r /proc/{original.pid}/cmdline ]\n"
                f"date -u +%FT%TZ > {q(str(restarted))}\n"
                f"exec {q(daemon)} -S -b -m -p {q(str(pidfile))} -x {q(runsvdir)}"
                f" -d {q(str(folder))} -- {q(str(svdir))}\n"
            )
            job.chmod(0o700)
            scheduled = True
            sched = call("termux-job-scheduler", "-s", str(job), "--job-id", job_id, "--period-ms", "0",
                         "--network", "none", "--battery-not-low", "false")
            result["schedule_exit"] = sched.returncode
            assert sched.returncode == 0
            assert wait_for(marker.is_file, 30), "Android did not dispatch job"
            result["job_entered_utc"] = marker.read_text().strip()
            assert original.poll() is None and not restarted.exists()
            verify(original.pid, svdir)
            assert os.getpgid(original.pid) == original.pid != os.getpgrp()
            os.killpg(original.pid, signal.SIGKILL)
            original.wait(timeout=5)
            assert original.returncode == -signal.SIGKILL
            result["isolated_tree_stopped"] = True
            recovered = wait_for(lambda: ready(token) if restarted.is_file() and pidfile.is_file() else None, 45)
            assert recovered is not None, "staging READY did not return after Android job"
            new = int(pidfile.read_text())
            verify(new, svdir)
            assert new != original.pid and child(service) != old_child
            result["job_observed_loss_utc"] = restarted.read_text().strip()
            result["recovered_ready"] = recovered
            result["new_supervisor"] = new
        except (AssertionError, OSError, subprocess.SubprocessError) as exc:
            result["blocked"] = str(exc) or type(exc).__name__
        finally:
            if scheduled:
                with suppress(subprocess.TimeoutExpired):
                    result["cancel_exit"] = call("termux-job-scheduler", "--cancel", "--job-id", job_id).returncode
                    last = call("termux-job-scheduler", "-p")
                    result["final_jobs"] = (last.stdout + last.stderr).strip()
            if original.poll() is None:
                verify(original.pid, svdir)
                assert os.getpgid(original.pid) == original.pid
                os.killpg(original.pid, signal.SIGKILL)
                original.wait(timeout=5)
            if pidfile.is_file():
                replacement = int(pidfile.read_text())
                if (Path("/proc") / str(replacement) / "cmdline").exists():
                    verify(replacement, svdir)
                    call("sv", "-w", "10", "down", str(service))
                    os.kill(replacement, signal.SIGTERM)
                    call("sv", "exit", str(service))
    result["port_closed_after_cleanup"] = bool(wait_for(port_closed, 10))
    result["production_pids_unchanged"] = prod_before == sample()
    result["release_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return result_file(folder, result)


if __name__ == "__main__":
    raise SystemExit(main())
