"""The Termux deploy scripts parse, and the switch script keeps its safety steps in order."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"
# The switch runs as `sh switch_service.sh` (dash on Termux and Debian/Ubuntu): test its shell
# functions under that shell, not bash, whose error semantics differ (review A-06).
POSIX_SH = shutil.which("dash") or shutil.which("sh")


class DeployScriptTests(unittest.TestCase):
    def test_shell_scripts_parse(self):
        sh = shutil.which("sh")
        for script in sorted(DEPLOY.glob("*.sh")):
            proc = subprocess.run([sh, "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{script.name}: {proc.stderr}")

    def test_build_script_loads_the_release_module_under_isolated_mode(self):
        """Regression: `python3 -I -m hg.release` cannot find `hg` (-I drops the current directory)."""
        text = (DEPLOY / "build_release.sh").read_text(encoding="utf-8")
        self.assertNotIn("-m hg.release", text)
        stub = text.split("rel() { ", 1)[1].split(' "$@"; }', 1)[0]
        cmd = stub.replace("python3", "", 1).strip()
        args = cmd.split(" -c ", 1)
        code = args[1].strip().strip("'")
        repo = DEPLOY.parents[1]
        proc = subprocess.run([sys.executable, "-I", "-B", "-c", code, "--help"], cwd=repo, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("verify-root", proc.stdout)

    def test_smoke_script_compiles(self):
        path = DEPLOY / "deploy_smoke.py"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")     # no .pyc written next to the source

    def test_switch_checks_everything_before_stopping_and_rolls_back_on_failure(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index("# ---------------------------------------------------------------- switch forward"):]
        order = [text.index(marker) for marker in (
            'cp -p "$S/run" "$BK/run.old"',          # recovery point first
            'rollback_target "$BK/run.old"',         # a rollback must be provable before anything stops
            "quota_ok",                               # GitHub quota for safe restarts
            'release_ok "$NEWCONF" "$NEW"',          # verify-root, preflight, config consistency
            "finish_ok",                              # the reviewed ./finish is installed
            "space_ok",                               # room for the state backup
            'sh -n "$BK/run.new"',                   # rendered run script parses
            "stop_service",                           # only now stop (graceful sv down)
            'lock_state_dir "$STATE" live',            # exclusive lock survives the complete cutover
            'backup_state "$BK/state"',              # copy while the switch-owned lock is held
            'precheck_with "$ROOT"',                  # the new release must read that state
            "require_state_locks",                    # still the switch's own lock right before the swap
            'mv "$S/run.tmp" "$S/run"',               # then swap the run script
            "unlock_state",                            # release only when the next service can acquire it
            'start_and_wait "$NEWCONF" "$NEW"')]      # READY on the new release with a stable pid
        self.assertEqual(order, sorted(order))
        for name in ("backup_state", "precheck_with"):                 # proof before and after each step
            start = full.index(f"{name}() {{")
            after_heredoc = full.index("\nPY\n", start) if name == "backup_state" else start
            body = full[start:full.index("\n}\n", after_heredoc)]
            self.assertGreaterEqual(body.count("require_state_locks"), 2, name)
        self.assertNotIn("HG_STATE_LOCK_HELD", full)                    # a flag is never proof of a lock
        self.assertIn("trap on_exit EXIT", full)
        rollback = full[full.index("rollback_cutover() {"):full.index("\non_exit() {")]
        self.assertIn('if lock_for_state_rollback "$layout" && require_state_locks && restore_state_previous; then',
                      rollback)                                                 # proof, then rollback
        self.assertLess(rollback.index("ensure_down"), rollback.index("classify_state"))   # DOWN before any change
        on_exit = full[full.index("on_exit() {"):full.index("trap on_exit EXIT")]
        self.assertLess(on_exit.index("trap '' HUP INT TERM"), on_exit.index("rollback_cutover"))
        for flag in ("SWAPPED=1", "STATE_SWAPPED", "STOPPED=1"):          # flags are not evidence (F-05)
            self.assertNotIn(flag, full)
        for sig in ("HUP", "INT", "TERM"):
            self.assertRegex(full, rf"trap 'exit \d+' {sig}")
        stop = full[full.index("stop_service() {"):full.index("start_and_wait() {")]
        self.assertLess(stop.index("CUTOVER=1"), stop.index("sv -w 60 -v down"))   # a timed-out stop still rolls back
        self.assertNotIn("kill -9", full)
        self.assertNotIn("sv kill", full)
        self.assertNotIn("! grep", full)                                              # `!` disables set -e

    def test_restore_is_mode_aware_and_checks_the_old_release_reads_the_state(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index("# ---------------------------------------------------------------- --restore"):
                    full.index("# ---------------------------------------------------------------- switch forward")]
        self.assertIn('PREV_RUN="$BK/run.current"', text)          # failure returns to the release that was running
        self.assertIn("the shared config changed since the switch", text)
        order = [text.index(m) for m in ('rollback_target "$BK/run.current"', "quota_ok",
                                         'release_ok "$OLD_RUNCONF" "$OLD_RID"', "stop_service",
                                         'lock_state_dir "$STATE" live', 'backup_state "$BK/state"',
                                         'precheck_with "$OLD_ROOT"',
                                         'lock_state_dir "$STATE.incoming-$TS" incoming',
                                         'mv "$STATE" "$STATE.prev-$TS"',
                                         'STATE_LOCK_DIR="$STATE.prev-$TS"',
                                         'mv "$STATE.incoming-$TS" "$STATE"',
                                         'cp -p "$SRC/run.old" "$S/run.tmp"', "unlock_state",
                                         'start_and_wait "$OLD_RUNCONF" "$OLD_RID"')]
        self.assertEqual(order, sorted(order))
        # every rename and the run-script swap is preceded by a fresh proof of lock ownership
        for marker in ('mv "$STATE" "$STATE.prev-$TS"', 'mv "$STATE.incoming-$TS" "$STATE"',
                       'cp -p "$SRC/run.old" "$S/run.tmp"'):
            before = text[:text.index(marker)].rstrip().splitlines()
            self.assertEqual(before[-1].strip(), "require_state_locks", marker)
        self.assertIn('sha256sum -c --quiet "$SRC/state.sha256"', text)

    def test_restore_targets_the_release_the_recorded_run_script_started(self):
        """Finding F-W2 (phone, 2026-10-29 10:44 +07): the forward switch never edits the shared
        config, so its release_id can name an older release (f7cfd766) than the one run.old
        actually started (1cb93e5f). Restore must take the release and config from run.old,
        or it validates one release, starts another and waits for READY on the wrong id."""
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index("# ---------------------------------------------------------------- --restore"):
                    full.index("# ---------------------------------------------------------------- switch forward")]
        self.assertIn('OLD_RUNCONF="$(run_config "$SRC/run.old")"', text)
        self.assertIn('OLD_RID="$(field "$OLD_RUNCONF" release_id)"', text)
        self.assertNotIn('OLD_RID="$(field "$OLDCONF" release_id)"', text)
        self.assertLess(text.index('OLD_RUNCONF="$(run_config "$SRC/run.old")"'), text.index("stop_service"))
        self.assertIn('grep -qF "cd \\"$OLD_ROOT\\"" "$SRC/run.old"', text)

    def test_run_config_reads_the_config_of_a_rendered_run_script(self):
        if shutil.which("sh") is None:
            self.skipTest("no sh")
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        start = full.index("run_config() {")
        func = full[start:full.index("\n}\n", start) + 3]
        template = (DEPLOY / "hg-runtime.run.in").read_text(encoding="utf-8")
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / "runtime-service-1cb9.json"
            run_old = Path(td) / "run.old"
            run_old.write_text(template.replace("@ROOT@", td + "/hg-releases/1cb9").replace("@CONF@", str(conf)),
                               encoding="utf-8")
            other = Path(td) / "run.other"
            other.write_text("#!/bin/sh\nexec python3 -m something_else\n", encoding="utf-8")
            script = func + 'run_config "$1"\n'
            out = subprocess.run(["sh", "-c", script, "sh", str(run_old)], capture_output=True, text=True)
            self.assertEqual((out.returncode, out.stdout.strip()), (0, str(conf)))
            out = subprocess.run(["sh", "-c", script, "sh", str(other)], capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "")

    def test_finish_is_installed_separately_with_a_backup(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index('if [ "${1:-}" = "--install-finish" ]'):full.index("# ---------------------------------------------------------------- --restore")]
        self.assertLess(text.index('cp -p "$S/finish" "$FB/finish.old"'), text.index('mv "$S/finish.tmp" "$S/finish"'))

    def test_state_precheck_reads_the_deployed_state_and_rejects_damage(self):
        import json
        import os
        import shutil
        import tempfile
        repo = DEPLOY.parents[1]
        fixture = repo / "hg" / "tests" / "fixtures" / "state_f3dac34"
        tmp = Path(tempfile.mkdtemp(prefix="hg-precheck-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        good = tmp / "good"
        shutil.copytree(fixture, good)
        for path in [good, *good.rglob("*")]:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        def attest(state):
            import hashlib
            import time
            inventory = []
            for path in sorted(state.rglob("*")):
                if path.is_file() and path.name != ".hg-state-copy.json":
                    raw = path.read_bytes()
                    inventory.append({"path": path.relative_to(state).as_posix(), "bytes": len(raw),
                                      "sha256": hashlib.sha256(raw).hexdigest()})
            (state / ".hg-state-copy.json").write_text(json.dumps({
                "schema": "hg-state-copy-attestation-v1", "copy_id": "synthetic-" + state.name,
                "source_ref": "synthetic-fixture/state_f3dac34",
                "created_at": "2026-11-02T00:00:00+00:00",
                "assurance": "OPERATIONAL_INTEGRITY_UNAUTHENTICATED", "inventory": inventory,
            }, sort_keys=True), encoding="utf-8")

        attest(good)
        env = {k: v for k, v in os.environ.items() if k != "HG_RUNTIME_STATE_DIR"}
        env["HG_SERVICE_CONFIG"] = str(tmp / "no-service-config.json")     # never the owner's real config
        run = lambda state: subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "state_precheck.py"), str(repo),
                                            str(state)], capture_output=True, text=True, timeout=60, env=env)
        proc = run(good)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual((report["result"], sorted(report["checks"])),
                         ("PASS", ["actions", "idempotency", "memory", "tasks"]))
        self.assertEqual(report["assurance"], "OPERATIONAL_INTEGRITY_UNAUTHENTICATED")
        empty = tmp / "empty"
        empty.mkdir()
        proc = run(empty)
        self.assertEqual(proc.returncode, 1)
        self.assertNotEqual(json.loads(proc.stdout).get("result"), "PASS")
        bad = tmp / "bad"
        shutil.copytree(good, bad)
        with (bad / "tasks.jsonl").open("ab") as stream:
            stream.write(b'{"event_id": "x"')
        attest(bad)
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["checks"]["tasks"]["ok"])

    # ---- G1: copy admission, live-root protection and the real backup step ----------------

    def _state_copy(self, tmp, name, *, marker=True):
        import os
        state = tmp / name
        shutil.copytree(DEPLOY.parents[1] / "hg" / "tests" / "fixtures" / "state_f3dac34", state)
        if marker:                                  # backup_state copies the live .writer.lock too
            (state / ".writer.lock").touch()
        for path in [state, *state.rglob("*")]:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        return state

    @staticmethod
    def _attest(state):
        import hashlib
        import json
        inventory = [{"path": p.relative_to(state).as_posix(), "bytes": p.stat().st_size,
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                     for p in sorted(state.rglob("*")) if p.is_file() and p.name != ".hg-state-copy.json"]
        (state / ".hg-state-copy.json").write_text(json.dumps({
            "schema": "hg-state-copy-attestation-v1", "copy_id": "synthetic-" + state.name,
            "source_ref": "synthetic-fixture/state_f3dac34", "created_at": "2026-11-03T00:00:00+00:00",
            "assurance": "OPERATIONAL_INTEGRITY_UNAUTHENTICATED", "inventory": inventory}), encoding="utf-8")

    def _precheck(self, tmp, state, **env):
        import json
        import os
        base = {k: v for k, v in os.environ.items() if k not in ("HG_RUNTIME_STATE_DIR", "HG_SERVICE_CONFIG")}
        base["HG_SERVICE_CONFIG"] = str(tmp / "no-service-config.json")     # never the owner's real config
        base.update({k: str(v) for k, v in env.items()})
        proc = subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "state_precheck.py"), str(DEPLOY.parents[1]),
                               str(state)], capture_output=True, text=True, timeout=60, env=base)
        return proc.returncode, json.loads(proc.stdout)

    def _tmp(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="hg-g1-precheck-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp

    def test_state_precheck_loads_a_copy_that_carries_the_writer_marker(self):
        tmp = self._tmp()
        good = self._state_copy(tmp, "good")
        self._attest(good)
        rc, report = self._precheck(tmp, good)
        self.assertEqual((rc, report["result"]), (0, "PASS"), report)
        self.assertTrue(all(c["ok"] for c in report["checks"].values()), report)

    def test_state_precheck_detects_modified_missing_extra_and_symlinked_files(self):
        import os
        tmp = self._tmp()
        cases = {
            "modified": lambda s: (s / "memory.jsonl").write_bytes((s / "memory.jsonl").read_bytes() + b" "),
            "missing": lambda s: (s / "actions.jsonl").unlink(),
            "extra": lambda s: (s / "stray.bin").write_bytes(b"x"),
            "symlink": lambda s: os.symlink(s / "tasks.jsonl", s / "link.jsonl"),
        }
        for name, damage in cases.items():
            state = self._state_copy(tmp, name)
            self._attest(state)
            damage(state)
            rc, report = self._precheck(tmp, state)
            self.assertEqual((rc, report["result"]), (1, "FAIL"), name)
            self.assertIn("copy admission", report["reason"], name)
            self.assertNotIn("checks", report, name)        # nothing is loaded from a bad copy

    def test_state_precheck_refuses_custom_live_roots_from_env_and_service_config(self):
        import json
        tmp = self._tmp()
        live_env = self._state_copy(tmp, "custom-live-env")
        self._attest(live_env)
        rc, report = self._precheck(tmp, live_env, HG_RUNTIME_STATE_DIR=live_env)
        self.assertEqual(rc, 1)
        self.assertIn("overlaps the protected live runtime-state root", report["reason"])
        live_conf = self._state_copy(tmp, "custom-live-config")
        nested = self._state_copy(live_conf, "copy-inside-live")
        self._attest(nested)
        config = tmp / "runtime-service.json"
        config.write_text(json.dumps({"state_dir": str(live_conf)}), encoding="utf-8")
        rc, report = self._precheck(tmp, nested, HG_SERVICE_CONFIG=config)
        self.assertEqual(rc, 1)
        self.assertIn("overlaps the protected live runtime-state root", report["reason"])
        config.write_text(json.dumps({"port": 8765}), encoding="utf-8")     # names no state_dir
        good = self._state_copy(tmp, "good")
        self._attest(good)
        rc, report = self._precheck(tmp, good, HG_SERVICE_CONFIG=config)
        self.assertEqual(rc, 1)
        self.assertIn("names no absolute state_dir", report["reason"])

    def test_backup_state_replaces_a_stale_attestation_and_the_copy_passes_precheck(self):
        import json
        import os
        text = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        body = text.split("backup_state() {", 1)[1].split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]
        tmp = self._tmp()
        live = self._state_copy(tmp, "live")
        (live / ".hg-state-copy.json").write_text('{"copy_id": "stale-from-a-restore"}', encoding="utf-8")
        os.chmod(live / ".hg-state-copy.json", 0o600)
        (tmp / "bk").mkdir()
        dst = tmp / "bk" / "state"
        proc = subprocess.run([sys.executable, "-I", "-", str(live), str(dst)], input=body, text=True,
                              capture_output=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = json.loads((dst / ".hg-state-copy.json").read_text(encoding="utf-8"))
        self.assertNotEqual(doc.get("copy_id"), "stale-from-a-restore")
        self.assertNotIn(".hg-state-copy.json", {i["path"] for i in doc["inventory"]})
        self.assertNotIn(".hg-state-copy.json", Path(str(dst) + ".sha256").read_text(encoding="utf-8"))
        rc, report = self._precheck(tmp, dst)
        self.assertEqual((rc, report["result"]), (0, "PASS"), report)


    def _backup_body(self):
        text = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        return text.split("backup_state() {", 1)[1].split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]

    def _run_backup(self, live, dst, *, fd=None, env_extra=None):
        import os
        env = {k: v for k, v in os.environ.items() if k not in ("HG_STATE_LOCK_FD", "HG_STATE_LOCK_HELD")}
        env.update(env_extra or {})
        args = [sys.executable, "-I", "-", str(live), str(dst)]
        if fd is not None:
            env["HG_STATE_LOCK_FD"] = str(fd)
            args.append(str(DEPLOY / "state_lock.py"))
        return subprocess.run(args, input=self._backup_body(), text=True, capture_output=True, timeout=60,
                              env=env, pass_fds=() if fd is None else (fd,))

    def test_backup_state_uses_the_switch_descriptor_lock_without_releasing_it(self):
        import fcntl
        import json
        import os

        tmp = self._tmp()
        live = self._state_copy(tmp, "live-externally-locked")
        (live / ".hg-state-copy.json").write_text('{"copy_id": "stale"}', encoding="utf-8")
        os.chmod(live / ".hg-state-copy.json", 0o600)
        (tmp / "bk").mkdir()
        dst = tmp / "bk" / "state"
        lock_path = live / ".writer.lock"
        owner = os.open(lock_path, os.O_RDONLY)          # plays the switch shell's fd 9
        contender = os.open(lock_path, os.O_RDWR)
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self._run_backup(live, dst, fd=owner)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("state backed up:", result.stdout)
            self.assertTrue((dst / ".hg-state-copy.json").is_file())
            doc = json.loads((dst / ".hg-state-copy.json").read_text(encoding="utf-8"))
            self.assertNotEqual(doc.get("copy_id"), "stale")
            self.assertNotIn(".hg-state-copy.json", {i["path"] for i in doc["inventory"]})

            # backup_state must not unlock the switch owner's still-live exclusive flock.
            with self.assertRaises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.close(owner)
            owner = None
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(contender, fcntl.LOCK_UN)
        finally:
            if owner is not None:
                os.close(owner)
            os.close(contender)

    def test_backup_state_refuses_while_another_process_owns_the_lock(self):
        """Review F-01 reproduction B: the switch's holder is gone and a competing writer has the
        flock. Neither the old flag (HG_STATE_LOCK_HELD=1) nor a descriptor that does not own the
        lock may produce a backup or an attestation."""
        import fcntl
        import os

        tmp = self._tmp()
        live = self._state_copy(tmp, "live-taken-over")
        lock_path = live / ".writer.lock"
        competitor = os.open(lock_path, os.O_RDWR)
        stale = os.open(lock_path, os.O_RDONLY)            # the switch's descriptor, lock already lost
        try:
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            cases = {"legacy-flag": dict(env_extra={"HG_STATE_LOCK_HELD": "1"}),
                     "descriptor-without-lock": dict(fd=stale)}
            for name, kwargs in cases.items():
                (tmp / name).mkdir()
                dst = tmp / name / "state"
                result = self._run_backup(live, dst, **kwargs)
                self.assertNotEqual(result.returncode, 0, name)
                self.assertNotIn("state backed up:", result.stdout, name)
                self.assertFalse(dst.exists(), f"{name}: a copy was made without owning the lock")
            with self.assertRaises(BlockingIOError):         # the competitor still owns it, untouched
                fcntl.flock(stale, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(stale)
            os.close(competitor)

    def test_backup_state_refuses_a_descriptor_when_nobody_holds_the_lock(self):
        import fcntl
        import os

        tmp = self._tmp()
        live = self._state_copy(tmp, "live-unlocked")
        fd = os.open(live / ".writer.lock", os.O_RDONLY)
        try:
            (tmp / "bk").mkdir()
            result = self._run_backup(live, tmp / "bk" / "state", fd=fd)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nobody holds", result.stderr)
            self.assertFalse((tmp / "bk" / "state").exists())
            probe = os.open(live / ".writer.lock", os.O_RDONLY)
            try:                                              # the check did not take the lock itself
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
        finally:
            os.close(fd)

    def test_restore_state_rollback_restores_previous_if_incoming_rename_failed(self):
        import tempfile

        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        start = full.index("restore_state_previous() {")
        func = full[start:full.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory(prefix="hg-state-rollback-") as td:
            root = Path(td)
            state = root / "state"
            previous = root / "state.prev-T"
            previous.mkdir()
            (previous / "owner.txt").write_text("old-state", encoding="utf-8")
            script = ("say() { :; }\nSTATE=" + repr(str(state)) + "\nTS=T\n" + func
                      + "\nrestore_state_previous\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((state / "owner.txt").read_text(encoding="utf-8"), "old-state")
            self.assertFalse(previous.exists())
            shutil.rmtree(state)

            # If an incoming state did become live, preserve it as FAILED and restore old state.
            previous.mkdir()
            (previous / "owner.txt").write_text("old-state-2", encoding="utf-8")
            state.mkdir()
            (state / "incoming.txt").write_text("incomplete-new-state", encoding="utf-8")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((state / "owner.txt").read_text(encoding="utf-8"), "old-state-2")
            self.assertTrue((root / "state.failed-T" / "incoming.txt").is_file())

    def test_restore_state_rollback_refuses_to_claim_success_when_previous_is_missing(self):
        import tempfile

        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        start = full.index("restore_state_previous() {")
        func = full[start:full.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory(prefix="hg-state-rollback-missing-") as td:
            root = Path(td)
            state = root / "state"
            state.mkdir()
            (state / "incoming.txt").write_text("unverified-incoming", encoding="utf-8")
            script = ("say() { :; }\nSTATE=" + repr(str(state)) + "\nTS=T\n" + func
                      + "\nrestore_state_previous\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue((state / "incoming.txt").is_file())

    def _trap_script(self, root, *, layout, run, status_line="down: hg-runtime: 1s, normally up", stubs=""):
        """on_exit + rollback_cutover + ensure_down from the real script; classifiers and state
        operations stubbed, every external call logged to calls.txt."""
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")

        def func(name):
            start = full.index(f"{name}() {{")
            return full[start:full.index("\n}\n", start) + 3]
        calls = root / "calls.txt"
        log = lambda what: 'echo "' + what + '" >> ' + repr(str(calls))
        return calls, (
            "say() { :; }\n"
            'sv() { echo "sv $*" >> ' + repr(str(calls)) + '; [ "$1" = status ] && echo ' + repr(status_line) + '; return 0; }\n'
            f"classify_state() {{ echo {layout}; }}\nclassify_run() {{ echo {run}; }}\n"
            "lock_for_state_rollback() { return 0; }\nrequire_state_locks() { return 0; }\n"
            "restore_state_previous() { " + log("restore") + "; return 0; }\n"
            "start_and_wait() { " + log("start") + "; return 0; }\n"
            "state_matches_backup() { return 0; }\npython3() { return 0; }\n"   # content unchanged, lock free
            "unlock_state() { :; }\ncp() { :; }\nmv() { :; }\n" + stubs +
            "CUTOVER=1; BK=fixture; STATE=/missing/state; TS=T; FINISH_STATE=/missing; PREV_RUN=/missing/run.old; "
            "S=/missing/service; ROLLBACK_CONF=c; ROLLBACK_RID=r\n"
            + "DOWN_MARKER_PREEXISTED=0\n"
            + func("service_down_proven") + func("ensure_down") + func("clear_down_marker")
            + func("rollback_cutover") + func("on_exit") + "\nfalse\non_exit\n")

    def test_on_exit_keeps_service_down_when_state_rollback_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-fail-closed-") as td:
            calls, script = self._trap_script(Path(td), layout="SWAPPED", run="ORIGINAL",
                                              stubs="restore_state_previous() { return 1; }\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(),
                             ["sv -w 60 -v down hg-runtime", "sv status hg-runtime",      # proven DOWN first
                              "sv -w 60 -v down hg-runtime", "sv status hg-runtime"])     # and DOWN at the end
            self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", proc.stdout.splitlines())

    def test_on_exit_does_not_rename_state_back_without_proving_its_locks(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-lock-lost-") as td:
            calls, script = self._trap_script(Path(td), layout="MOVED_ASIDE", run="ORIGINAL",
                                              stubs="require_state_locks() { return 1; }\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            seen = calls.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("restore", seen)
            self.assertNotIn("start", seen)
            self.assertNotIn("sv up hg-runtime", seen)
            self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", proc.stdout.splitlines())

    def test_on_exit_changes_and_starts_nothing_when_down_cannot_be_proven(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-not-down-") as td:
            calls, script = self._trap_script(Path(td), layout="SWAPPED", run="NEW",
                                              status_line="run: hg-runtime: (pid 7) 9s")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(calls.read_text(encoding="utf-8").splitlines(),
                             ["sv -w 60 -v down hg-runtime", "sv status hg-runtime"])
            self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_STATE_UNKNOWN", proc.stdout.splitlines())
            self.assertNotIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", proc.stdout)

    def test_on_exit_unknown_layout_alone_blocks_the_start(self):
        """Each guard holds on its own: an UNKNOWN layout found before the rollback blocks the start
        even if a later re-read happened to look ORIGINAL."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-unknown-") as td:
            root = Path(td)
            seen = root / "classify-count"
            stub = ("classify_state() { n=$(cat " + repr(str(seen)) + " 2>/dev/null || echo 0); "
                    "echo $((n + 1)) > " + repr(str(seen)) + "; "
                    "if [ \"$n\" = 0 ]; then echo UNKNOWN; else echo ORIGINAL; fi; }\n")
            calls, script = self._trap_script(root, layout="UNKNOWN", run="ORIGINAL", stubs=stub)
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            got = calls.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("start", got)
            self.assertNotIn("restore", got)
            self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", proc.stdout.splitlines())

    def test_on_exit_starts_only_a_pair_proven_original_after_rollback(self):
        """classify_* re-read after the rollback still say SWAPPED: never start, stay DOWN."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-unproven-pair-") as td:
            calls, script = self._trap_script(Path(td), layout="SWAPPED", run="ORIGINAL")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            seen = calls.read_text(encoding="utf-8").splitlines()
            self.assertIn("restore", seen)
            self.assertNotIn("start", seen)
            self.assertIn("ROLLBACK_INCOMPLETE_SERVICE_DOWN", proc.stdout.splitlines())


    @staticmethod
    def _funcs(*names):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        out = []
        for name in names:
            start = full.index(f"{name}() {{")
            out.append(full[start:full.index("\n}\n", start) + 3])
        return "".join(out)

    def test_a04_on_exit_never_rolls_back_a_committed_switch(self):
        """After the verified start the switch is committed: a later failure or signal reports,
        it never rolls back (and never discards writes the new pair accepted)."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-on-exit-committed-") as td:
            calls, script = self._trap_script(Path(td), layout="SWAPPED", run="NEW",
                                              stubs="CUTOVER=1; COMMITTED=1\n")
            script = script.replace("CUTOVER=1; BK=fixture", "CUTOVER=1; COMMITTED=1; BK=fixture")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(calls.exists() and calls.read_text(encoding="utf-8").strip(),
                             "a committed switch was touched: " + (calls.read_text() if calls.exists() else ""))
            self.assertIn("COMMITTED", proc.stdout)
            self.assertNotIn("ROLLED_BACK_AFTER_FAILURE", proc.stdout)
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        for start_call in ('start_and_wait "$NEWCONF" "$NEW"', 'start_and_wait "$OLD_RUNCONF" "$OLD_RID"'):
            after = full[full.index(start_call):].splitlines()
            self.assertEqual(after[1].strip(), "COMMITTED=1", start_call)          # nothing in between
        fwd = full[full.index("# ---------------------------------------------------------------- switch forward"):]
        self.assertLess(fwd.index('> "$BK/hashes.after"'), fwd.index('start_and_wait "$NEWCONF" "$NEW"'))
        rst = full[full.index("# ---------------------------------------------------------------- --restore"):]
        self.assertLess(rst.index('> "$BK/run.restored.sha256"'), rst.index('start_and_wait "$OLD_RUNCONF"'))

    def test_a06_dash_exec_redirection_semantics_pin(self):
        """Pins the dash behaviour the lock code depends on: a failed plain `exec 9< file` kills
        the shell even inside `|| return 1`; `command exec` fails like a normal command."""
        if not shutil.which("dash"):
            self.skipTest("no dash on this host")
        for form, survives in (("exec", False), ("command exec", True)):
            script = ("f() { " + form + " 9< /nonexistent/hg-lock || return 1; }\n"
                      "f || echo HANDLED\necho END\n")
            proc = subprocess.run(["dash", "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual("END" in proc.stdout, survives, (form, proc.stdout, proc.stderr))

    def test_a06_every_lock_descriptor_is_opened_with_command_exec(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        import re
        opens = re.findall(r"(\S*\s*)exec [789]<\s*\"", full)
        self.assertTrue(opens, "no lock descriptor opens found")
        for prefix in opens:
            self.assertEqual(prefix.strip(), "command", f"bare exec for a lock descriptor: {prefix!r}")

    def test_a06_unopenable_lock_fails_inside_the_trap_without_killing_it(self):
        import os
        import tempfile
        if os.geteuid() == 0:
            self.skipTest("root bypasses file permissions, so the open cannot be made to fail here")
        with tempfile.TemporaryDirectory(prefix="hg-lock-unopenable-") as td:
            root = Path(td)
            lock = root / ".writer.lock"
            lock.touch(mode=0o000)
            os.chmod(lock, 0o000)
            script = ("say() { echo \"$*\"; }\nHERE=/nonexistent\nSTATE_LOCK_HELD=0; INCOMING_LOCK_HELD=0\n"
                      + self._funcs("lock_state_dir")
                      + "on_exit() { lock_state_dir " + repr(str(root)) + " live || echo HANDLED; echo TRAP_END; }\n"
                      + "trap on_exit EXIT\nfalse\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertIn("HANDLED", proc.stdout, proc.stderr)
            self.assertIn("TRAP_END", proc.stdout, proc.stderr)

    def test_a10_space_check_counts_the_incoming_copies_of_restore_state(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-space-") as td:
            root = Path(td)
            stub = ('du() { case "$2" in */src-state) echo "4000\t$2";; *) echo "1000\t$2";; esac; }\n'
                    'df() { printf "Filesystem 1K-blocks Used Available Use%% Mounted\\nfs 1 1 %s 1%% /\\n" "$AVAIL"; }\n'
                    "say() { echo \"$*\"; }\n")
            base = stub + "STATE=" + repr(str(root / "live")) + "\nHOME=" + repr(str(root)) + "\n" + self._funcs("space_ok")
            ok = subprocess.run([POSIX_SH, "-c", base + "AVAIL=4000\nspace_ok && echo PASS\n"],
                                capture_output=True, text=True, timeout=5)
            self.assertIn("PASS", ok.stdout, ok.stderr)                     # 2*1000+1024 <= 4000
            need = subprocess.run([POSIX_SH, "-c", base + "AVAIL=4000\nspace_ok " + repr(str(root / "src-state"))
                                   + " && echo PASS\n"], capture_output=True, text=True, timeout=5)
            self.assertNotIn("PASS", need.stdout, "restore-state also needs room for two copies of the source")
            enough = subprocess.run([POSIX_SH, "-c", base + "AVAIL=11100\nspace_ok " + repr(str(root / "src-state"))
                                     + " && echo PASS\n"], capture_output=True, text=True, timeout=5)
            self.assertIn("PASS", enough.stdout, enough.stderr)              # 2*1000+2*4000+1024 = 11024
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        rst = full[full.index("# ---------------------------------------------------------------- --restore"):
                   full.index("# ---------------------------------------------------------------- switch forward")]
        self.assertIn('space_ok "$SRC/state"', rst)

    def test_a02_cutover_in_place_checks_run_and_state_from_the_filesystem(self):
        cases = [("NEW", "SWAPPED", "SWAPPED", "o", "n", 0), ("NEW", "ORIGINAL", "ORIGINAL", "o", "n", 0),
                 ("ORIGINAL", "ORIGINAL", "ORIGINAL", "same", "same", 0),      # same release: same hash
                 ("ORIGINAL", "SWAPPED", "SWAPPED", "o", "n", 1),              # run swap did not happen
                 ("UNKNOWN", "SWAPPED", "SWAPPED", "o", "n", 1),
                 ("NEW", "ORIGINAL", "SWAPPED", "o", "n", 1),                  # renames did not happen
                 ("NEW", "MOVED_ASIDE", "SWAPPED", "o", "n", 1)]
        for run, state, want, orig, new, rc in cases:
            script = (f"say() {{ :; }}\nclassify_run() {{ echo {run}; }}\nclassify_state() {{ echo {state}; }}\n"
                      f"ORIG_RUN_SHA={orig}; NEW_RUN_SHA={new}\n" + self._funcs("cutover_in_place")
                      + f"cutover_in_place {want}\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, rc, (run, state, want))

    def test_a02_every_run_script_swap_step_ends_the_script_on_failure(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        main = full[full.index("# ---------------------------------------------------------------- --install-finish"):]
        for line in main.splitlines():
            code = line.split("#", 1)[0].strip()
            if code.startswith(("install ", "mv ", "cp ")) and '"$S/run.tmp"' in code:   # the run-script swap
                self.assertTrue(code.endswith("|| exit 1"), f"not guarded: {code}")
            self.assertFalse(code.startswith(("install ", "cp ", "mv ")) and " && " in code, f"AND-list: {code}")
        for start in ('start_and_wait "$NEWCONF" "$NEW"', 'start_and_wait "$OLD_RUNCONF" "$OLD_RID"'):
            before = main[:main.index(start)].rsplit("unlock_state", 1)[0]
            self.assertIn("cutover_in_place", before.rsplit("require_state_locks", 1)[1], start)

    def test_a07_service_down_proof_accepts_only_a_settled_down(self):
        """Regex guard alone: whatever sv down returned, the status must say down with nothing pending."""
        log = "; run: log: (pid 77) 99s"
        cases = [(f"down: hg-runtime: 3s, normally up{log}", 0),
                 ("down: hg-runtime: 3s", 0),                                   # ./down marker present
                 (f"down: hg-runtime: 0s, normally up, want up{log}", 1),       # runsv about to start it
                 (f"down: hg-runtime: 2s, normally up, paused{log}", 1),
                 (f"run: hg-runtime: (pid 7) 9s{log}", 1),
                 ("warning: hg-runtime: unable to open supervise/ok: file does not exist", 1),
                 (f"run: log: (pid 77) 99s; down: hg-runtime: 3s, normally up", 1)]
        for line, rc in cases:
            script = ("sv() { echo " + repr(line) + "; }\n" + self._funcs("service_down_proven")
                      + "service_down_proven\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, rc, line)

    def test_a07_ensure_down_requires_sv_to_confirm_the_stop(self):
        """sv-confirmation guard alone: a stop sv reports as failed is not DOWN, even if a status
        sampled afterwards happens to read down."""
        for down_rc, want in ((0, 0), (1, 1)):
            script = ('sv() { if [ "$1" = status ]; then echo "down: hg-runtime: 3s, normally up"; '
                      f'else return {down_rc}; fi; }}\n'
                      + self._funcs("service_down_proven", "ensure_down") + "ensure_down\n")
            proc = subprocess.run([POSIX_SH, "-c", script], capture_output=True, text=True, timeout=5)
            self.assertEqual(proc.returncode, want, down_rc)

    def test_m07_classify_state_rejects_a_foreign_prev_dir_beside_an_intact_live_state(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory(prefix="hg-classify-") as td:
            root = Path(td)
            live = root / "state"
            live.mkdir()
            ident = lambda p: f"{os.lstat(p).st_dev}:{os.lstat(p).st_ino}"
            base = ("STATE=" + repr(str(live)) + "\nTS=T\nLIVE_ID=" + ident(live) + "\nINCOMING_ID=\n"
                    + self._funcs("absent", "dir_id", "classify_state") + "classify_state\n")
            run = lambda: subprocess.run([POSIX_SH, "-c", base], capture_output=True, text=True,
                                         timeout=10).stdout.strip()
            self.assertEqual(run(), "ORIGINAL")
            (root / "state.prev-T").mkdir()                       # something this switch did not create
            self.assertEqual(run(), "UNKNOWN")

    def test_m12_backup_refuses_when_the_lock_is_lost_during_the_copy(self):
        """The backup proves ownership again after the copy and hashes: losing the lock while
        `cp` runs must not produce an attestation (the outer shell check is a second, separate guard)."""
        import fcntl
        import os
        import tempfile
        import threading
        import time
        tmp = self._tmp()
        live = self._state_copy(tmp, "live-lost-mid-copy")
        (tmp / "bk").mkdir()
        dst = tmp / "bk" / "state"
        stubs = Path(tempfile.mkdtemp(prefix="hg-cp-pause-"))
        self.addCleanup(shutil.rmtree, stubs, ignore_errors=True)
        real_cp = shutil.which("cp")
        (stubs / "cp").write_text(f"#!{shutil.which('sh')}\n: > {stubs}/copying\n"
                                  f"while [ ! -e {stubs}/go ]; do sleep 0.01; done\nexec {real_cp} \"$@\"\n")
        os.chmod(stubs / "cp", 0o755)
        owner = os.open(live / ".writer.lock", os.O_RDONLY)
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def lose_lock_mid_copy():
            deadline = time.monotonic() + 20
            while not (stubs / "copying").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            fcntl.flock(owner, fcntl.LOCK_UN)                     # same open file description as the child's
            (stubs / "go").touch()
        thread = threading.Thread(target=lose_lock_mid_copy)
        thread.start()
        try:
            env = {k: v for k, v in os.environ.items() if k not in ("HG_STATE_LOCK_FD", "HG_STATE_LOCK_HELD")}
            env.update(PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}", HG_STATE_LOCK_FD=str(owner))
            proc = subprocess.run([sys.executable, "-I", "-", str(live), str(dst), str(DEPLOY / "state_lock.py")],
                                  input=self._backup_body(), text=True, capture_output=True, timeout=60,
                                  env=env, pass_fds=(owner,))
        finally:
            thread.join(timeout=30)
            os.close(owner)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("not owned by the switch", proc.stderr)
        self.assertFalse((dst / ".hg-state-copy.json").exists(), "an attestation was written without the lock")

    def test_restore_state_never_makes_a_copy_attestation_live(self):
        text = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        branch = text.split('if [ "$MODE" = "--restore-state" ]; then\n    require_state_locks', 1)[1].split("else", 1)[0]
        self.assertLess(branch.index("precheck_with"), branch.index('rm -f "$STATE.incoming-$TS/.hg-state-copy.json"'))
        self.assertLess(branch.index(".hg-state-copy.json"), branch.index('mv "$STATE.incoming-$TS" "$STATE"'))
        self.assertIn('HG_RUNTIME_STATE_DIR="$STATE" HG_SERVICE_CONFIG="$OLDCONF"', text)

    def test_install_never_overwrites_a_foreign_hg_command(self):
        text = (DEPLOY / "install_release.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "HG command shim"', text)
        self.assertIn("not overwriting", text)


class StateLockHelperTests(unittest.TestCase):
    """state_lock.py only locks or checks a descriptor its caller owns (review F-01)."""

    def _tool(self, mode, fd, path):
        return subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "state_lock.py"), mode, str(fd), str(path)],
                              capture_output=True, text=True, timeout=10, pass_fds=(fd,))

    def _lock_file(self):
        import os
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="hg-state-lock-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        lock = root / ".writer.lock"
        lock.touch(mode=0o600)
        os.chmod(lock, 0o600)
        return root, lock

    def test_lock_taken_by_the_tool_stays_with_the_callers_descriptor_after_the_tool_exits(self):
        import fcntl
        import os
        _root, lock = self._lock_file()
        owner = os.open(lock, os.O_RDONLY)                  # the switch shell's descriptor
        contender = os.open(lock, os.O_RDWR)
        try:
            proc = self._tool("acquire", owner, lock)
            self.assertEqual(proc.returncode, 0, proc.stderr)   # the tool has exited ...
            with self.assertRaises(BlockingIOError):            # ... and the lock is still held
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self._tool("verify", owner, lock).returncode, 0)
            proc = self._tool("verify", contender, lock)        # a different description is not the owner
            self.assertEqual(proc.returncode, 5, proc.stderr)
            os.close(owner)                                     # only closing the owner releases it
            owner = None
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(contender, fcntl.LOCK_UN)
        finally:
            if owner is not None:
                os.close(owner)
            os.close(contender)

    def test_verify_refuses_a_lost_lock_and_never_takes_it_back(self):
        import fcntl
        import os
        _root, lock = self._lock_file()
        owner = os.open(lock, os.O_RDONLY)
        try:
            self.assertEqual(self._tool("acquire", owner, lock).returncode, 0)
            fcntl.flock(owner, fcntl.LOCK_UN)                   # the lock is lost (e.g. an unlocking child)
            proc = self._tool("verify", owner, lock)
            self.assertEqual(proc.returncode, 5, proc.stderr)
            self.assertIn("nobody holds", proc.stderr)
            probe = os.open(lock, os.O_RDONLY)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)   # verify did not re-lock it
                proc = self._tool("verify", owner, lock)            # now a competitor owns it
                self.assertEqual(proc.returncode, 5, proc.stderr)
                self.assertIn("another process", proc.stderr)
            finally:
                os.close(probe)
        finally:
            os.close(owner)

    def test_a05_verify_never_retakes_a_lock_released_by_a_competitor_mid_check(self):
        """Review A-05: the switch's descriptor lost the lock; a competitor holds it and lets go
        right after verify's independent probe was refused. verify must still answer NOT HELD."""
        import fcntl
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location("hg_state_lock_under_test", DEPLOY / "state_lock.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _root, lock = self._lock_file()
        owner = os.open(lock, os.O_RDONLY)
        competitor = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(owner, fcntl.LOCK_UN)                     # lost
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)

            class Interleave:
                fired = False

                def flock(self, fd, op):
                    try:
                        return fcntl.flock(fd, op)
                    except BlockingIOError:
                        if fd not in (owner, competitor) and not Interleave.fired:
                            Interleave.fired = True
                            fcntl.flock(competitor, fcntl.LOCK_UN)   # competitor lets go right now
                        raise

                def __getattr__(self, name):
                    return getattr(fcntl, name)
            mod.fcntl = Interleave()
            with self.assertRaises(mod.LockNotHeld):
                mod.verify_held(owner, str(lock))
            probe = os.open(lock, os.O_RDONLY)
            try:                                                  # and it did not take the lock
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(probe)
        finally:
            os.close(owner)
            os.close(competitor)

    def test_acquire_reports_contention_and_takes_nothing(self):
        import fcntl
        import os
        _root, lock = self._lock_file()
        competitor = os.open(lock, os.O_RDWR)
        mine = os.open(lock, os.O_RDONLY)
        try:
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            proc = self._tool("acquire", mine, lock)
            self.assertEqual(proc.returncode, 3, proc.stderr)
            self.assertIn("already held", proc.stderr)
        finally:
            os.close(mine)
            os.close(competitor)

    def test_switch_lock_tool_refuses_a_symlink_or_a_path_that_names_another_file(self):
        import os
        root, lock = self._lock_file()
        target = root / "target"
        target.touch(mode=0o600)
        link = root / "link.lock"
        link.symlink_to(target)
        fd = os.open(target, os.O_RDONLY)
        try:
            proc = self._tool("acquire", fd, link)
            self.assertEqual(proc.returncode, 4)
            self.assertIn("writer lock refused", proc.stderr)
            proc = self._tool("acquire", fd, lock)               # descriptor and path disagree
            self.assertEqual(proc.returncode, 4)
            self.assertIn("no longer names the locked file", proc.stderr)
        finally:
            os.close(fd)

    def test_switch_lock_tool_refuses_a_group_readable_lock_and_bad_usage(self):
        import os
        _root, lock = self._lock_file()
        os.chmod(lock, 0o640)
        fd = os.open(lock, os.O_RDONLY)
        try:
            self.assertEqual(self._tool("acquire", fd, lock).returncode, 4)
        finally:
            os.close(fd)
        proc = subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "state_lock.py"), "hold", "x"],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 2)


class InstallSealOrderTests(unittest.TestCase):
    def test_release_is_sealed_and_reverified_before_the_pointer_is_published(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2] / "deploy/termux/install_release.sh").read_text(encoding="utf-8")
        verify_first = text.index("verify_root(")
        seal = text.index("seal_root(")
        verify_again = text.index("verify_root(", seal)
        pointer = text.index('"$POINTER.tmp"')
        self.assertLess(verify_first, seal)
        self.assertLess(seal, verify_again)
        self.assertLess(verify_again, pointer)


if __name__ == "__main__":
    unittest.main()
