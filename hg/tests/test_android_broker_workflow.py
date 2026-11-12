"""G7-CI: the emulator negative-Binder job must run its checks as one bash process.

reactivecircus/android-emulator-runner runs every line of an inline multi-line `script:` in its
own `sh -c`. Shell variables, functions and heredocs then do not carry between lines; the run of
2026-11-10 failed at `test -s "$BROKER"` with an empty path. The workflow must hand the runner a
single command that executes the checked-in script, and that script must be strict bash.
"""
import os
import re
import stat
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hg-go-live-android-broker.yml"
SCRIPT = ROOT / "android" / "cim-broker" / "ci" / "emulator_negative_binder.sh"


@unittest.skipUnless(WORKFLOW.is_file(), "Android broker workflow not on this branch")
class EmulatorRunnerScriptTest(unittest.TestCase):
    def _runner_step(self):
        lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
        start = next(i for i, line in enumerate(lines) if "reactivecircus/android-emulator-runner" in line)
        step_indent = len(lines[start]) - len(lines[start].lstrip())
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= step_indent - 2),
            len(lines),
        )
        return lines[start:end]

    def test_runner_script_is_one_command(self):
        step = self._runner_step()
        script_lines = [line for line in step if re.match(r"^\s*script:", line)]
        self.assertEqual(len(script_lines), 1, step)
        value = script_lines[0].split("script:", 1)[1].strip()
        self.assertNotIn(value, {"|", ">", "|-", ">-", ""}, "multi-line inline script runs line by line")
        self.assertEqual(value, "bash android/cim-broker/ci/emulator_negative_binder.sh")

    def test_emulator_stack_installs_from_stable_channel(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "--channel=3" in line:
                for package in ('"platform-tools"', '"emulator"', '"system-images;'):
                    self.assertNotIn(package, line, f"canary channel for {package}: {line.strip()}")

    def test_owner_controls_matched_case_insensitively(self):
        # Buttons use textAllCaps; uiautomator can report the label upper-cased (run 2026-11-13:
        # "could not tap owner confirmation control 'Trust this installed Termux'").
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(".casefold()", text)
        self.assertIn('"content-desc"', text)
        self.assertIn("seen: ", text)

    def test_no_early_exit_reader_under_pipefail(self):
        # `... | awk '...; exit }'` under pipefail killed the writer with SIGPIPE: exit 141
        # (run on 403c830, 2026-11-13).
        import re as _re
        for line in SCRIPT.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "awk" in line:
                self.assertIsNone(_re.search(r"\bexit\b", line), line.strip())
            self.assertNotRegex(line, r"\|\s*head\b", line.strip())

    def test_ui_dump_avoids_sdcard(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/sdcard/", text)
        self.assertIn("/data/local/tmp/hg-window.xml", text)

    def test_emulator_uses_aosp_image(self):
        # google_apis image: Play services ANR dialog covered the Broker UI (run on 67be038).
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("google_apis", text.replace("# AOSP image: the google_apis", ""))
        self.assertIn("target: default", text)
        self.assertIn('"system-images;android-35;default;x86_64"', text)

    def test_kvm_enabled_before_emulator(self):
        # Without /dev/kvm access the emulator runs -accel off: 8-13 min boots, system ANRs.
        text = WORKFLOW.read_text(encoding="utf-8")
        kvm = text.find("99-kvm4all.rules")
        runner = text.find("reactivecircus/android-emulator-runner")
        self.assertGreater(kvm, 0)
        self.assertLess(kvm, runner)
        self.assertIn("udevadm trigger --name-match=kvm", text)

    def test_script_is_strict_bash(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("\nset -euo pipefail\n", text)
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)
        for needed in ('test -s "$BROKER"', "NEGATIVE_BINDER_PASS_DENY_UID", "UIDS_DISTINCT=PASS"):
            self.assertIn(needed, text)


if __name__ == "__main__":
    unittest.main()
