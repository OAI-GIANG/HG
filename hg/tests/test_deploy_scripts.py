"""The Termux deploy scripts parse, and the switch script keeps its safety steps in order."""
import shutil
import subprocess
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"


class DeployScriptTests(unittest.TestCase):
    def test_shell_scripts_parse(self):
        sh = shutil.which("sh")
        for script in sorted(DEPLOY.glob("*.sh")):
            proc = subprocess.run([sh, "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{script.name}: {proc.stderr}")

    def test_smoke_script_compiles(self):
        path = DEPLOY / "deploy_smoke.py"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")     # no .pyc written next to the source

    def test_switch_records_recovery_before_stopping_and_backs_up_state_while_down(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index('NEW="$1"'):]          # the switch path, after the --restore branch
        order = [text.index(marker) for marker in (
            'cp -p "$S/run" "$BK/run.old"',          # recovery point first
            "--check",                                # read-only preflight of the new release
            "sv down hg-runtime; wait_state down",    # stop
            'cp -a "$STATE" "$BK/state"',             # state backup only while stopped
            'mv "$S/run.tmp" "$S/run"',               # only then the new run script
            "sv up hg-runtime; wait_state run")]
        self.assertEqual(order, sorted(order))
        self.assertIn('"78"', text)                   # finish script holds a fail-closed start down

    def test_install_never_overwrites_a_foreign_hg_command(self):
        text = (DEPLOY / "install_release.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "HG command shim"', text)
        self.assertIn("not overwriting", text)


if __name__ == "__main__":
    unittest.main()
