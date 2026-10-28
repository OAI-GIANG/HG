"""deploy/termux/hg-runtime.finish and hg-runtime.run.in (AC-D5): no restart loop, no blocking wait."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"
FINISH = DEPLOY / "hg-runtime.finish"


class FinishScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-finish-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = self.tmp / "service"
        (self.service / "supervise").mkdir(parents=True)
        self.control = self.service / "supervise" / "control"
        self.state = self.tmp / "state"
        self.boot = self.tmp / "boot_id"
        self.boot.write_text("boot-A\n")
        self.env = dict(os.environ, HG_FINISH_STATE_DIR=str(self.state), HG_BOOT_ID_FILE=str(self.boot),
                        HG_FINISH_MAX="5", HG_FINISH_SV="/bin/false")

    def started(self, seconds_ago, boot="boot-A"):
        self.state.mkdir(exist_ok=True)
        (self.state / "hg-runtime.started").write_text(f"{boot} {int(time.time()) - seconds_ago}\n")

    def finish(self, *args):
        t0 = time.monotonic()
        proc = subprocess.run(["/bin/sh", str(FINISH), *args], cwd=self.service, env=self.env,
                              capture_output=True, text=True, timeout=30)
        return proc, time.monotonic() - t0

    def held(self):
        return self.control.exists() and self.control.read_text() == "d"

    def test_returns_at_once_and_holds_down_after_five_short_failures(self):
        for attempt in range(1, 6):
            self.started(2)
            proc, elapsed = self.finish("78", "0")
            self.assertEqual(proc.returncode, 0)
            self.assertLess(elapsed, 1.0)
            self.assertIn(f"count={attempt}/5", proc.stdout)
            self.assertFalse(self.held())
        self.started(2)
        proc, _ = self.finish("78", "0")
        self.assertIn("HG_BLOCKED", proc.stdout)
        self.assertTrue(self.held())
        self.assertTrue((self.state / "hg-runtime.HELD").exists())

    def test_crash_and_android_kill_count_like_exit_78(self):
        for args in (("1", "0"), ("-1", "9"), ("78", "0")):
            self.started(1)
            self.finish(*args)
        self.assertTrue((self.state / "hg-runtime-finish.count").read_text().startswith("boot-A 3 "))

    def test_deliberate_stop_is_not_counted(self):
        self.started(1)
        proc, _ = self.finish("-1", "15")
        self.assertEqual(proc.stdout, "")
        self.assertFalse((self.state / "hg-runtime-finish.count").exists())

    def test_exit_zero_and_long_runs_reset_the_count(self):
        for _ in range(3):
            self.started(1)
            self.finish("78", "0")
        self.started(1)
        self.finish("0", "0")
        self.assertFalse((self.state / "hg-runtime-finish.count").exists())
        for _ in range(3):
            self.started(1)
            self.finish("78", "0")
        self.started(400)                                   # ran for 400 s, then crashed
        self.finish("-1", "9")
        self.assertFalse((self.state / "hg-runtime-finish.count").exists())

    def test_a_reboot_starts_fresh(self):
        for _ in range(5):
            self.started(1)
            self.finish("78", "0")
        self.boot.write_text("boot-B\n")
        self.started(1, boot="boot-B")
        proc, _ = self.finish("78", "0")
        self.assertIn("count=1/5", proc.stdout)
        self.assertFalse(self.held())


class RunTemplateTests(unittest.TestCase):
    def render(self, tmp):
        text = (DEPLOY / "hg-runtime.run.in").read_text(encoding="utf-8")
        return text.replace("@ROOT@", str(tmp / "release")).replace("@CONF@", str(tmp / "conf.json"))

    def test_template_renders_and_parses(self):
        tmp = Path(tempfile.mkdtemp(prefix="hg-run-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        run = tmp / "run"
        run.write_text(self.render(tmp))
        self.assertEqual(subprocess.run(["/bin/sh", "-n", str(run)]).returncode, 0)
        self.assertNotIn("@", self.render(tmp).split("set -eu", 1)[1].replace("@example", ""))

    def test_wait_happens_before_start_and_only_after_a_counted_failure(self):
        text = (DEPLOY / "hg-runtime.run.in").read_text(encoding="utf-8")
        order = [text.index(m) for m in ('if [ "$count" -gt 0 ]', "https://api.github.com/rate_limit",
                                         "hg-runtime.started.tmp",
                                         "exec python3 -B -u -m hg serve")]
        self.assertEqual(order, sorted(order))

    def test_no_quota_spent_while_waiting(self):
        """Run the prestart with a fake curl that reports 0 remaining: it must wait, not start."""
        tmp = Path(tempfile.mkdtemp(prefix="hg-run-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "curl").write_text('#!/bin/sh\necho \'{"resources":{"core":{"remaining":0}}}\'\n')
        (bindir / "sleep").write_text("#!/bin/sh\necho slept >> %s/sleeps\nexit 0\n" % tmp)
        (bindir / "termux-wake-lock").write_text("#!/bin/sh\nexit 0\n")
        for f in bindir.iterdir():
            f.chmod(0o755)
        state = tmp / "state"
        state.mkdir()
        boot = open("/proc/sys/kernel/random/boot_id").read().strip() if os.path.exists(
            "/proc/sys/kernel/random/boot_id") else "unknown"
        (state / "hg-runtime-finish.count").write_text(f"{boot} 2 0\n")
        run = tmp / "run"
        run.write_text(self.render(tmp))
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", HG_FINISH_STATE_DIR=str(state))
        proc = subprocess.run(["/bin/sh", str(run)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual((tmp / "sleeps").read_text().count("slept"), 30)          # 30 x 30 s = 15 min cap
        self.assertIn("HG_RUNTIME_WAIT attempt=2 github_remaining=0", proc.stdout)
        self.assertIn("verified release directory missing", proc.stdout)            # then tries once (fake root)


if __name__ == "__main__":
    unittest.main()
