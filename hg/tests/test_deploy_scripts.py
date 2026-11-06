"""The Termux deploy scripts parse, and the switch script keeps its safety steps in order."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"


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
            "quota_ok",                               # GitHub quota for safe restarts
            'release_ok "$NEWCONF" "$NEW"',          # verify-root, preflight, config consistency
            "finish_ok",                              # the reviewed ./finish is installed
            "space_ok",                               # room for the state backup
            'sh -n "$BK/run.new"',                   # rendered run script parses
            "stop_service",                           # only now stop (graceful sv down)
            'backup_state "$BK/state"',              # copy under the service's own writer lock
            'precheck_with "$ROOT"',                  # the new release must read that state
            'mv "$S/run.tmp" "$S/run"',               # then swap the run script
            'start_and_wait "$NEWCONF" "$NEW"')]      # READY on the new release with a stable pid
        self.assertEqual(order, sorted(order))
        self.assertIn("trap on_exit EXIT", full)
        for sig in ("HUP", "INT", "TERM"):
            self.assertRegex(full, rf"trap 'exit \d+' {sig}")
        stop = full[full.index("stop_service() {"):full.index("start_and_wait() {")]
        self.assertLess(stop.index("STOPPED=1"), stop.index("sv -w 60 -v down"))   # a timed-out stop still rolls back
        self.assertNotIn("kill -9", full)
        self.assertNotIn("sv kill", full)
        self.assertNotIn("! grep", full)                                              # `!` disables set -e

    def test_restore_is_mode_aware_and_checks_the_old_release_reads_the_state(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index("# ---------------------------------------------------------------- --restore"):
                    full.index("# ---------------------------------------------------------------- switch forward")]
        self.assertIn('PREV_RUN="$BK/run.current"', text)          # failure returns to the release that was running
        self.assertIn("the shared config changed since the switch", text)
        order = [text.index(m) for m in ("quota_ok", 'release_ok "$OLD_RUNCONF" "$OLD_RID"', "stop_service",
                                         'backup_state "$BK/state"', 'precheck_with "$OLD_ROOT"',
                                         'cp -p "$SRC/run.old" "$S/run.tmp"', 'start_and_wait "$OLD_RUNCONF" "$OLD_RID"')]
        self.assertEqual(order, sorted(order))
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
        body = text.split("backup_state() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
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

    def test_restore_state_never_makes_a_copy_attestation_live(self):
        text = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        branch = text.split('if [ "$MODE" = "--restore-state" ]; then', 1)[1].split("else", 1)[0]
        self.assertLess(branch.index("precheck_with"), branch.index('rm -f "$STATE.incoming-$TS/.hg-state-copy.json"'))
        self.assertLess(branch.index(".hg-state-copy.json"), branch.index('mv "$STATE.incoming-$TS" "$STATE"'))
        self.assertIn('HG_RUNTIME_STATE_DIR="$STATE" HG_SERVICE_CONFIG="$OLDCONF"', text)

    def test_install_never_overwrites_a_foreign_hg_command(self):
        text = (DEPLOY / "install_release.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "HG command shim"', text)
        self.assertIn("not overwriting", text)


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
