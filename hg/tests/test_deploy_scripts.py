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
        order = [text.index(m) for m in ("quota_ok", 'release_ok "$OLDCONF" "$OLD_RID"', "stop_service",
                                         'backup_state "$BK/state"', 'precheck_with "$OLD_ROOT"',
                                         'cp -p "$SRC/run.old" "$S/run.tmp"', "start_and_wait")]
        self.assertEqual(order, sorted(order))
        self.assertIn('sha256sum -c --quiet "$SRC/state.sha256"', text)

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
        run = lambda state: subprocess.run([sys.executable, "-I", "-B", str(DEPLOY / "state_precheck.py"), str(repo),
                                            str(state)], capture_output=True, text=True, timeout=60)
        proc = run(good)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual((report["result"], sorted(report["checks"])),
                         ("PASS", ["actions", "idempotency", "memory", "tasks"]))
        bad = tmp / "bad"
        shutil.copytree(good, bad)
        with (bad / "tasks.jsonl").open("ab") as stream:
            stream.write(b'{"event_id": "x"')
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["checks"]["tasks"]["ok"])

    def test_install_never_overwrites_a_foreign_hg_command(self):
        text = (DEPLOY / "install_release.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "HG command shim"', text)
        self.assertIn("not overwriting", text)


if __name__ == "__main__":
    unittest.main()
