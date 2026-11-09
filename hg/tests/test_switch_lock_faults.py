"""Fault injection through the real Termux switch script (PR #87 review findings F-01 and F-04).

Each test runs deploy/termux/switch_service.sh end to end in a disposable HOME and PREFIX, with
stub `sv`, `curl`, `date` and `sleep` commands and a fake loopback readiness endpoint. Only the
temporary directory is touched: no runit service, no live state, no network.

The `date` stub is the barrier. The script calls it from `say` at each phase boundary of its
critical section, so a test can stop the switch there while the state writer lock is held, break
the lock the way a dying holder would, let a competing process take the exclusive flock, and then
check what the switch does next. F-01: once the lock is gone, no backup, precheck, rename, run
script swap or start of an unverified pair may follow. F-04: after an automatic rollback, the
previous release must be shown READY (authenticated, stable pid) before the rollback is reported
as verified.
"""
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "termux"
FIXTURE = REPO / "hg" / "tests" / "fixtures" / "state_f3dac34"
OLD, NEW = "rel-old", "rel-new"
RUN_PREFIX = 'exec python3 -B -u -m hg serve --config "'

STUB = r'''
import fcntl, glob, hashlib, json, os, sys, time
from pathlib import Path

CTL = Path(os.environ["HG_FI_CTL"])
CFG = json.loads((CTL / "env.json").read_text())
RUN_PREFIX = 'exec python3 -B -u -m hg serve --config "'


def current_release():
    try:
        lines = (Path(CFG["svc"]) / "run").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith(RUN_PREFIX) and line.endswith('"'):
            try:
                return json.loads(Path(line[len(RUN_PREFIX):-1]).read_text())["release_id"]
            except (OSError, ValueError, KeyError):
                return None
    return None


def state_digest():
    root = Path(CFG["state"])
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return {"ino": root.stat().st_ino, "sha256": h.hexdigest()}


def sv(argv):
    path = CTL / "sv.json"
    st = json.loads(path.read_text())
    entry = {"argv": argv}
    if argv[:1] == ["status"]:
        if st["up"]:
            if current_release() in st["restart_loop"]:
                st["pid"] += 1                       # a restart loop: every look shows a new pid
            print(f"run: hg-runtime: (pid {st['pid']}) 3s")
        else:
            print("down: hg-runtime: 3s, normally up")
        entry = None
    elif "down" in argv:
        st["up"] = False
    elif argv[:1] == ["up"]:
        st["up"] = True
        st["pid"] += 1
        entry.update(run_sha256=hashlib.sha256((Path(CFG["svc"]) / "run").read_bytes()).hexdigest(),
                     state=state_digest(), release=current_release(),
                     after_fault=(CTL / "barrier.fired").exists())
    else:
        print("sv stub: unsupported " + " ".join(argv), file=sys.stderr)
        return 1
    path.write_text(json.dumps(st))
    if entry is not None:
        with (CTL / "sv-log.jsonl").open("a") as stream:
            stream.write(json.dumps(entry) + "\n")
    return 0


def held(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def lock_paths():
    state = CFG["state"]
    return sorted(set(glob.glob(state + "/.writer.lock") + glob.glob(state + ".*/.writer.lock")))


def phase_matches(phase):
    found = sorted(glob.glob(CFG["evidence"] + "/switch-*") + glob.glob(CFG["evidence"] + "/restore-*"))
    if not found:
        return False
    bk, state = Path(found[-1]), Path(CFG["state"])
    incoming = [p for p in glob.glob(str(state) + ".incoming-*") if not p.endswith(".precheck")]
    report = (bk / "state-precheck.json").exists()
    if phase == "before-backup":
        return not (bk / "state").exists()
    if phase == "after-backup":
        return (bk / "state").exists() and not report and not incoming
    if phase == "after-precheck":
        return report and not (bk / "state.precheck").exists() and not incoming
    if phase == "after-incoming-precheck":
        return bool(incoming) and report and not any(held(p + "/.writer.lock") for p in incoming)
    if phase == "incoming-locked":
        return bool(incoming) and state.is_dir() and any(held(p + "/.writer.lock") for p in incoming)
    if phase == "after-first-rename":
        return bool(glob.glob(str(state) + ".prev-*")) and not state.exists()
    raise SystemExit("unknown barrier phase " + phase)


def barrier():
    phase = os.environ.get("HG_FI_BARRIER", "")
    if not phase or (CTL / "barrier.fired").exists():
        return 0
    if not any(held(p) for p in lock_paths()) or not phase_matches(phase):
        return 0
    released = []
    if os.environ.get("HG_FI_FAULT") == "release":
        # The only way a lock owned by an open file description can vanish while its owner runs:
        # some process sharing that description unlocks it. This stub shares whatever the switch
        # let its children inherit.
        for name in os.listdir("/proc/self/fd"):
            fd = int(name)
            try:
                target = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                continue
            if fd > 2 and target.endswith("/.writer.lock"):
                fcntl.flock(fd, fcntl.LOCK_UN)
                released.append([fd, target])
    tmp = CTL / "barrier.fired.tmp"
    tmp.write_text(json.dumps({"phase": phase, "pid": os.getpid(), "released": released}))
    os.replace(tmp, CTL / "barrier.fired")
    deadline = time.monotonic() + 60
    while not (CTL / "barrier.go").exists():
        if time.monotonic() > deadline:
            return 97
        time.sleep(0.01)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sv":
        sys.exit(sv(sys.argv[2:]))
    if cmd == "barrier":
        sys.exit(barrier())
    sys.exit(2)
'''


def _render_run(root, conf):
    template = (DEPLOY / "hg-runtime.run.in").read_text(encoding="utf-8")
    return template.replace("@ROOT@", str(root)).replace("@CONF@", str(conf))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_digest(root):
    root = Path(root)
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return {"ino": root.stat().st_ino, "sha256": h.hexdigest()}


def _private_copy(src, dst):
    shutil.copytree(src, dst)
    for path in [dst, *dst.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


class _ReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        env = self.server.switch_env
        if self.path != "/v1/health/ready" or self.headers.get("Authorization") != f"Bearer {env.token}":
            status, body = 401, {"error": "unauthorized"}
        else:
            sv_state = json.loads((env.ctl / "sv.json").read_text())
            release = env.current_release()
            ready = sv_state["up"] and release in json.loads((env.ctl / "ready.json").read_text())
            status = 200 if ready else 503
            body = {"status": "READY" if ready else "STARTING", "release_id": release,
                    "integrity": "VERIFIED", "trust": "LOADED", "trust_commit": "fixture-only"}
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class SwitchEnv:
    """A disposable HOME/PREFIX in which switch_service.sh can run end to end."""

    def __init__(self, case, template, *, running):
        self.case = case
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-switch-fi-"))
        case.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home, self.prefix = self.tmp / "home", self.tmp / "prefix"
        self.bin, self.ctl = self.tmp / "bin", self.tmp / "ctl"
        self.svc = self.prefix / "var" / "service" / "hg-runtime"
        self.confdir = self.home / ".config" / "hg"
        self.evidence = self.home / "hg-v1-evidence"
        self.state = self.home / ".local" / "share" / "hg" / "runtime-service-state"
        for d in (self.bin, self.ctl, self.svc, self.confdir / "releases", self.evidence,
                  self.state.parent, self.home / ".local" / "state" / "hg"):
            d.mkdir(parents=True, mode=0o700)
        os.chmod(self.home, 0o700)
        _private_copy(FIXTURE, self.state)
        lock = self.state / ".writer.lock"
        lock.touch(mode=0o600)
        os.chmod(lock, 0o600)
        self.token = "fixture-token-" + self.tmp.name
        (self.confdir / "token").write_text(self.token + "\n", encoding="utf-8")
        os.chmod(self.confdir / "token", 0o600)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ReadyHandler)
        self.server.switch_env = self
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        case.addCleanup(self.server.server_close)
        case.addCleanup(self.server.shutdown)

        base = {"state_dir": str(self.state), "port": self.server.server_address[1],
                "token_file": str(self.confdir / "token"), "host": "127.0.0.1", "max_body_bytes": 65536}
        for rid in (OLD, NEW):
            root = self.home / "hg-releases" / rid
            shutil.copytree(template, root, copy_function=os.link)
            (self.confdir / "releases" / f"{rid}.json").write_text("{}", encoding="utf-8")
        self.shared_conf = self.confdir / "runtime-service.json"
        self._write_conf(self.shared_conf, base, OLD)
        self.conf = {}
        for rid in (OLD, NEW):
            self.conf[rid] = self.confdir / f"runtime-service-{rid}.json"
            self._write_conf(self.conf[rid], base, rid)
        (self.svc / "run").write_text(_render_run(self.home / "hg-releases" / running, self.conf[running]),
                                      encoding="utf-8")
        os.chmod(self.svc / "run", 0o700)
        shutil.copy(DEPLOY / "hg-runtime.finish", self.svc / "finish")

        (self.ctl / "stub.py").write_text(STUB, encoding="utf-8")
        (self.ctl / "env.json").write_text(json.dumps({"svc": str(self.svc), "state": str(self.state),
                                                       "evidence": str(self.evidence)}), encoding="utf-8")
        (self.ctl / "sv.json").write_text(json.dumps({"up": True, "pid": 4000, "restart_loop": []}),
                                          encoding="utf-8")
        (self.ctl / "ready.json").write_text(json.dumps([OLD, NEW]), encoding="utf-8")
        sh, py = shutil.which("sh"), sys.executable
        real_date, real_sleep = shutil.which("date"), shutil.which("sleep")
        stubs = {
            "python3": f'exec "{py}" "$@"\n',
            "sv": f'exec "{py}" -I "{self.ctl / "stub.py"}" sv "$@"\n',
            "curl": "echo '{\"resources\": {\"core\": {\"remaining\": 5000}}}'\n",
            "sleep": f'exec "{real_sleep}" 0.05\n',
            "date": (f'if [ -n "${{HG_FI_BARRIER:-}}" ]; then "{py}" -I "{self.ctl / "stub.py"}" barrier '
                     f'|| echo "barrier failed" >&2; fi\nexec "{real_date}" "$@"\n'),
        }
        for name, body in stubs.items():
            path = self.bin / name
            path.write_text(f"#!{sh}\n{body}", encoding="utf-8")
            os.chmod(path, 0o755)
        self.original_run_sha = _sha(self.svc / "run")
        self.original_state = _tree_digest(self.state)
        self.competitor = []
        case.addCleanup(self._release_competitor)

    @staticmethod
    def _write_conf(path, base, rid):
        home = Path(base["token_file"]).parents[2]
        data = dict(base, release_id=rid, release_root=str(home / "hg-releases" / rid),
                    release_manifest=str(home / ".config" / "hg" / "releases" / f"{rid}.json"))
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)

    def current_release(self):
        for line in (self.svc / "run").read_text(encoding="utf-8").splitlines():
            if line.startswith(RUN_PREFIX) and line.endswith('"'):
                return json.loads(Path(line[len(RUN_PREFIX):-1]).read_text(encoding="utf-8"))["release_id"]
        return None

    def set_sv(self, **fields):
        st = json.loads((self.ctl / "sv.json").read_text())
        st.update(fields)
        (self.ctl / "sv.json").write_text(json.dumps(st))

    def previous_switch_dir(self):
        """A recovery dir as the forward switch OLD -> NEW would have left it (input to --restore*)."""
        src = self.evidence / "previous-switch"
        src.mkdir(mode=0o700)
        (src / "run.old").write_text(_render_run(self.home / "hg-releases" / OLD, self.conf[OLD]), encoding="utf-8")
        (src / "hashes.before").write_text(f"{_sha(src / 'run.old')}  run\n{_sha(self.shared_conf)}  conf\n",
                                           encoding="utf-8")
        _private_copy(FIXTURE, src / "state")
        (src / "state" / ".writer.lock").touch(mode=0o600)
        lines, inventory = [], []
        for p in sorted((src / "state").rglob("*")):
            if p.is_file():
                rel, raw = p.relative_to(src / "state").as_posix(), p.read_bytes()
                lines.append(f"{hashlib.sha256(raw).hexdigest()}  {rel}\n")
                inventory.append({"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        (src / "state.sha256").write_text("".join(lines), encoding="utf-8")
        (src / "state" / ".hg-state-copy.json").write_text(json.dumps({
            "schema": "hg-state-copy-attestation-v1", "copy_id": "fixture-previous-switch",
            "source_ref": "synthetic-fixture/state_f3dac34", "created_at": "2026-11-09T00:00:00+00:00",
            "assurance": "OPERATIONAL_INTEGRITY_UNAUTHENTICATED", "inventory": inventory}), encoding="utf-8")
        os.chmod(src / "state" / ".hg-state-copy.json", 0o600)
        return src

    def start(self, *args, barrier="", fault=""):
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
               "HOME": str(self.home), "PREFIX": str(self.prefix), "LANG": "C.UTF-8",
               "HG_FINISH_STATE_DIR": str(self.home / ".local" / "state" / "hg"),
               "HG_FI_CTL": str(self.ctl), "HG_FI_BARRIER": barrier, "HG_FI_FAULT": fault}
        if "TMPDIR" in os.environ:
            env["TMPDIR"] = os.environ["TMPDIR"]
        proc = subprocess.Popen([shutil.which("sh"), str(DEPLOY / "switch_service.sh"), *map(str, args)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                cwd=str(self.tmp))

        def stop():
            if proc.poll() is None:
                (self.ctl / "barrier.go").touch()
                proc.kill()
                proc.communicate(timeout=10)
        self.case.addCleanup(stop)
        return proc

    def wait_barrier(self, proc, timeout=90):
        deadline = time.monotonic() + timeout
        fired = self.ctl / "barrier.fired"
        while not fired.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                out = proc.communicate(timeout=10)[0] if proc.poll() is not None else ""
                self.case.fail(f"barrier never fired (rc={proc.poll()}):\n{out}")
            time.sleep(0.01)
        return json.loads(fired.read_text())

    def kill_lock_holder_helpers(self):
        """SIGKILL every process running state_lock.py for this environment (the 'helper')."""
        killed = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            text = b" ".join(argv).decode("utf-8", "replace")
            if "state_lock.py" in text and str(self.tmp) in text:
                try:
                    os.kill(int(entry.name), signal.SIGKILL)
                    killed.append(int(entry.name))
                except ProcessLookupError:
                    pass
        time.sleep(0.2)          # let the kernel tear the killed holders down
        return killed

    def compete(self):
        """Try to take every state writer lock exclusively; keep the ones obtained."""
        obtained, refused = [], []
        for path in sorted({*self.state.parent.glob(self.state.name + "/.writer.lock"),
                            *self.state.parent.glob(self.state.name + ".*/.writer.lock")}):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                refused.append(str(path))
            else:
                self.competitor.append(fd)
                obtained.append(str(path))
        return obtained, refused

    def competitor_still_holds(self):
        return bool(self.competitor) and all(self._held_elsewhere(fd) for fd in self.competitor)

    @staticmethod
    def _held_elsewhere(fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # no-op while this description owns it
            return True
        except BlockingIOError:
            return False

    def _release_competitor(self):
        while self.competitor:
            os.close(self.competitor.pop())

    def go(self):
        (self.ctl / "barrier.go").touch()

    def sv_log(self):
        path = self.ctl / "sv-log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def bk(self):
        found = sorted([*self.evidence.glob("switch-*"), *self.evidence.glob("restore-*")])
        return found[-1] if found else None


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("sh") and Path("/proc/self/fd").is_dir(),
                     "needs a POSIX sh and Linux /proc (Termux or Linux CI)")
class SwitchLockFaultInjectionTests(unittest.TestCase):
    """F-01: the switch may only back up, precheck, rename or swap while it provably owns the lock."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="hg-switch-fi-release-"))
        cls.template = cls._tmp / "release"
        ignore = shutil.ignore_patterns("__pycache__", "tests", "*.pyc")
        shutil.copytree(REPO / "hg", cls.template / "hg", ignore=ignore)
        shutil.copytree(REPO / "maep", cls.template / "maep", ignore=ignore)
        # Release verification and preflight are covered elsewhere; here they only have to pass.
        (cls.template / "hg" / "release.py").write_text("def main(argv):\n    return 0\n", encoding="utf-8")
        (cls.template / "hg" / "__main__.py").write_text(
            "import sys\nprint('PREFLIGHT_PASS' if '--check' in sys.argv else 'fixture release')\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def env(self, running=OLD):
        return SwitchEnv(self, self.template, running=running)

    def finish(self, proc):
        out = proc.communicate(timeout=120)[0]
        return proc.returncode, out

    # ---- positive controls: the harness can complete both paths --------------------------------

    def test_control_forward_switch_completes_and_starts_the_new_pair(self):
        env = self.env()
        rc, out = self.finish(env.start(NEW))
        self.assertEqual(rc, 0, out)
        self.assertIn("SWITCH_OK", out)
        self.assertEqual(env.current_release(), NEW)
        self.assertTrue((env.bk() / "state" / ".hg-state-copy.json").is_file())
        ups = [e for e in env.sv_log() if e["argv"][:1] == ["up"]]
        self.assertEqual([e["release"] for e in ups], [NEW], out)

    def test_control_restore_state_completes_and_starts_the_old_pair(self):
        env = self.env(running=NEW)
        src = env.previous_switch_dir()
        rc, out = self.finish(env.start("--restore-state", src))
        self.assertEqual(rc, 0, out)
        self.assertIn("RESTORED", out)
        self.assertEqual(env.current_release(), OLD)
        self.assertNotEqual(_tree_digest(env.state)["ino"], env.original_state["ino"])     # state was swapped in
        self.assertFalse((env.state / ".hg-state-copy.json").exists())

    # ---- the lock cannot be lost by killing a holder --------------------------------------------

    def _kill_holder_after_ready(self, *args):
        env = self.env(running=NEW if args[0] == "--restore-state" else OLD)
        if args[0] == "--restore-state":
            args = (args[0], env.previous_switch_dir())
        proc = env.start(*args, barrier="before-backup", fault="")
        env.wait_barrier(proc)
        killed = env.kill_lock_holder_helpers()
        obtained, refused = env.compete()
        env._release_competitor()
        env.go()
        rc, out = self.finish(proc)
        return env, killed, obtained, refused, rc, out

    def test_killing_lock_processes_after_ready_does_not_free_the_lock_forward(self):
        env, killed, obtained, refused, rc, out = self._kill_holder_after_ready(NEW)
        self.assertEqual(obtained, [], f"a competing process took the state lock after SIGKILL of {killed}")
        self.assertEqual(refused, [str(env.state / ".writer.lock")])
        self.assertEqual(killed, [], "the lock must be owned by the switch itself, not a separate holder")
        self.assertEqual(rc, 0, out)
        self.assertIn("SWITCH_OK", out)

    def test_killing_lock_processes_after_ready_does_not_free_the_lock_restore_state(self):
        env, killed, obtained, refused, rc, out = self._kill_holder_after_ready("--restore-state")
        self.assertEqual(obtained, [], f"a competing process took the state lock after SIGKILL of {killed}")
        self.assertEqual(killed, [], "the lock must be owned by the switch itself, not a separate holder")
        self.assertEqual(rc, 0, out)
        self.assertIn("RESTORED", out)

    # ---- once the lock is lost, nothing further may change ---------------------------------------

    def _lose_lock_at(self, phase, *args):
        restore = args[0] in ("--restore", "--restore-state")
        env = self.env(running=NEW if restore else OLD)
        if restore:
            args = (args[0], env.previous_switch_dir())
        proc = env.start(*args, barrier=phase, fault="release")
        fired = env.wait_barrier(proc)
        killed = env.kill_lock_holder_helpers()
        bk = env.bk()
        snap = {
            "run": _sha(env.svc / "run"),
            "state": _tree_digest(env.state) if env.state.is_dir() else None,
            "backup": (bk / "state").exists(),
            "report": (bk / "state-precheck.json").exists(),
            "incoming": sorted(p.name for p in env.state.parent.glob(env.state.name + ".incoming-*")),
            "prev": sorted(p.name for p in env.state.parent.glob(env.state.name + ".prev-*")),
        }
        obtained, refused = env.compete()
        self.assertTrue(obtained, f"fault did not free the lock (killed={killed}, fired={fired}, refused={refused})")
        env.go()
        rc, out = self.finish(proc)
        self.assertTrue(env.competitor_still_holds(), "the switch took the lock back from the competitor")
        self.assertNotEqual(rc, 0, out)
        for marker in ("SWITCH_OK", "RESTORED"):
            self.assertNotIn(marker, out.splitlines())
        self.assertEqual(_sha(env.svc / "run"), env.original_run_sha, "run script swapped or not put back")
        if not snap["backup"]:
            self.assertFalse((bk / "state").exists(), "backup continued after the lock was lost:\n" + out)
        if not snap["report"]:
            self.assertFalse((bk / "state-precheck.json").exists(), "precheck continued after the lock was lost")
        now_incoming = sorted(p.name for p in env.state.parent.glob(env.state.name + ".incoming-*"))
        if not snap["incoming"]:
            self.assertEqual(now_incoming, [], "an incoming state copy was made after the lock was lost")
        if snap["state"] is not None:
            self.assertEqual(_tree_digest(env.state), snap["state"], "live state renamed or changed after loss")
        for entry in env.sv_log():
            if entry["argv"][:1] == ["up"] and entry["after_fault"]:
                self.assertEqual(entry["run_sha256"], env.original_run_sha, entry)
                self.assertEqual(entry["state"], env.original_state, f"started against an unverified pair: {entry}")
        return env, snap, rc, out

    def test_lock_lost_before_backup_stops_forward_switch(self):
        self._lose_lock_at("before-backup", NEW)

    def test_lock_lost_after_backup_stops_forward_switch_before_precheck(self):
        self._lose_lock_at("after-backup", NEW)

    def test_lock_lost_after_precheck_stops_forward_switch_before_run_swap(self):
        self._lose_lock_at("after-precheck", NEW)

    def test_lock_lost_before_backup_stops_restore_state(self):
        self._lose_lock_at("before-backup", "--restore-state")

    def test_lock_lost_after_backup_stops_restore_state_before_incoming_copy(self):
        self._lose_lock_at("after-backup", "--restore-state")

    def test_lock_lost_after_incoming_precheck_stops_restore_state_before_rename(self):
        env, snap, rc, out = self._lose_lock_at("after-incoming-precheck", "--restore-state")
        self.assertEqual(sorted(env.state.parent.glob(env.state.name + ".prev-*")), [])

    def test_lock_lost_with_incoming_locked_stops_restore_state_before_rename(self):
        env, snap, rc, out = self._lose_lock_at("incoming-locked", "--restore-state")
        self.assertEqual(sorted(env.state.parent.glob(env.state.name + ".prev-*")), [])

    def test_lock_lost_between_renames_leaves_state_untouched_and_service_down(self):
        env, snap, rc, out = self._lose_lock_at("after-first-rename", "--restore-state")
        self.assertIsNone(snap["state"])
        self.assertFalse(env.state.exists(), "second rename or an unlocked rollback rename ran:\n" + out)
        self.assertEqual(len(snap["prev"]), 1)
        self.assertTrue((env.state.parent / snap["prev"][0]).is_dir())
        self.assertEqual(sorted(p.name for p in env.state.parent.glob(env.state.name + ".incoming-*")),
                         snap["incoming"])
        self.assertEqual([e for e in env.sv_log() if e["argv"][:1] == ["up"] and e["after_fault"]], [])
        self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", out)

    def test_lock_lost_after_precheck_stops_plain_restore_before_run_swap(self):
        self._lose_lock_at("after-precheck", "--restore")

    def test_contended_lock_aborts_before_backup(self):
        env = self.env()
        fd = os.open(env.state / ".writer.lock", os.O_RDONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # e.g. a writer that did not go away
        rc, out = self.finish(env.start(NEW))
        self.assertNotEqual(rc, 0, out)
        self.assertFalse((env.bk() / "state").exists(), out)
        self.assertEqual(_sha(env.svc / "run"), env.original_run_sha)


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("sh"), "needs a POSIX sh")
class SwitchRollbackReadyTests(unittest.TestCase):
    """F-04: an automatic rollback is reported verified only after authenticated READY + stable pid."""

    setUpClass = classmethod(SwitchLockFaultInjectionTests.setUpClass.__func__)
    tearDownClass = classmethod(SwitchLockFaultInjectionTests.tearDownClass.__func__)

    def env(self, running=OLD):
        return SwitchEnv(self, self.template, running=running)

    def test_rollback_after_failed_start_waits_for_the_previous_release_ready(self):
        env = self.env()
        env.set_sv(restart_loop=[NEW])                      # the new release never keeps a pid
        proc = env.start(NEW)
        out = proc.communicate(timeout=120)[0]
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn(f"ROLLBACK_READY_VERIFIED release={OLD}", out)
        self.assertEqual(_sha(env.svc / "run"), env.original_run_sha)
        ups = [e for e in env.sv_log() if e["argv"][:1] == ["up"]]
        self.assertEqual([e["release"] for e in ups], [NEW, OLD])
        self.assertEqual((ups[-1]["run_sha256"], ups[-1]["state"]), (env.original_run_sha, env.original_state))

    def test_rollback_is_not_reported_verified_when_the_previous_release_is_not_ready(self):
        env = self.env()
        env.set_sv(restart_loop=[NEW, OLD])
        proc = env.start(NEW)
        out = proc.communicate(timeout=120)[0]
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertNotIn("ROLLBACK_READY_VERIFIED", out)
        self.assertIn(f"ROLLBACK_READY_UNVERIFIED release={OLD}", out)

    def test_restore_state_rollback_relocks_puts_state_back_and_proves_the_previous_release_ready(self):
        """The old release cannot keep a pid after --restore-state swapped the state and released
        the locks: the trap must take the locks again (the service is down), rename the state back
        and prove the release that was running READY."""
        env = self.env(running=NEW)
        src = env.previous_switch_dir()
        env.set_sv(restart_loop=[OLD])
        proc = env.start("--restore-state", src)
        out = proc.communicate(timeout=120)[0]
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertIn(f"ROLLBACK_READY_VERIFIED release={NEW}", out)
        self.assertEqual(_tree_digest(env.state), env.original_state, "live state was not put back:\n" + out)
        self.assertEqual(len(list(env.state.parent.glob(env.state.name + ".failed-*"))), 1)
        self.assertEqual(_sha(env.svc / "run"), env.original_run_sha)
        ups = [e for e in env.sv_log() if e["argv"][:1] == ["up"]]
        self.assertEqual([e["release"] for e in ups], [OLD, NEW])
        self.assertEqual((ups[-1]["run_sha256"], ups[-1]["state"]), (env.original_run_sha, env.original_state))
        probe = os.open(env.state / ".writer.lock", os.O_RDONLY)
        try:                                                  # the switch released every lock it took
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)

    def test_switch_refuses_before_stopping_when_the_rollback_target_is_unknown(self):
        env = self.env()
        (env.svc / "run").write_text("#!/bin/sh\nexec python3 -m something_else\n", encoding="utf-8")
        proc = env.start(NEW)
        out = proc.communicate(timeout=120)[0]
        self.assertNotEqual(proc.returncode, 0, out)
        self.assertEqual(env.sv_log(), [], "the service was touched although rollback could not be verified")
        self.assertIn("rollback", out)


if __name__ == "__main__":
    unittest.main()
