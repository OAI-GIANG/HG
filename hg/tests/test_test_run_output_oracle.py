"""WS-04 oracle: test.run reads the test process's output with one meaning and bounded cost.

Each case runs a real `test.run`-style task through the gateway (fixture grants) on a test
directory whose code shapes the output channel. The outcome of a run that finished must be
known (never UNKNOWN, which leaves an unreconcilable pending action blocking the runtime),
the counts must be unittest's own summary, the reader must not hold the whole output in
memory, and no process started by the run may outlive it.
"""
import os
import time
import tracemalloc
import unittest

from hg.tests.support import make_task
from hg.tests.test_tools_research import ToolBase
from hg.tools.code import TestRunAdapter

PASS = ("import unittest\n{pre}\nclass T(unittest.TestCase):\n"
        "    def test_ok(self):\n{body}\n        self.assertTrue(True)\n")


class QuickTestRun(TestRunAdapter):
    name = "test.quick"
    timeout_s = 8          # the run gets max(timeout_s - 5, 1) = 3 s


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); read its state where /proc exists.
    try:
        with open(f"/proc/{pid}/stat", "rb") as stream:
            return stream.read().split(b") ", 1)[1][:1] != b"Z"
    except OSError:
        return True


class TestRunOutputOracle(ToolBase):
    def run_tests(self, body="        pass", pre="", tool="test.run", adapters=(), verifier=None):
        self.put("out/tests/test_case.py", PASS.format(pre=pre, body=body))
        op = ({"op": "test", "path": "out/tests"} if tool == "test.run"
              else {"tool": tool, "params": {"path": "out/tests"}})
        verifier = verifier or (lambda s: (s["outcomes"][0]["observed"]["ok"], "ok flag"))
        started = time.monotonic()
        rt, final = self.run_goal({"operations": [op]}, verifiers={"AC-1": verifier}, extra_adapters=adapters)
        return rt, final, time.monotonic() - started

    def observed(self, rt):
        completed = rt.actions.events("ACTION_COMPLETED")
        self.assertEqual(len(completed), 1, [e["payload"].get("status") for e in rt.actions.events()])
        return completed[0]["payload"]

    # ---------- controls ----------

    def test_control_plain_pass_closes(self):
        rt, final, _ = self.run_tests()
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])

    def test_control_non_ascii_utf8_output_is_kept(self):
        rt, final, _ = self.run_tests(body="        print('xin chào — ✓')")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")

    def test_control_no_tests_is_not_ok(self):
        seen = {}

        def keep(snapshot):
            seen.update(snapshot["outcomes"][0]["observed"])
            return seen["ok"], "ok flag"
        self.put("out/tests/README.txt", "no tests here\n")
        _rt, final = self.run_goal({"operations": [{"op": "test", "path": "out/tests"}]}, verifiers={"AC-1": keep})
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        self.assertEqual((seen["ok"], seen["tests_run"]), (False, 0))

    # ---------- output bytes ----------

    def test_non_utf8_output_from_a_finished_run_is_a_known_outcome(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                self.setUp()
                try:
                    body = f"        import sys; sys.{stream}.buffer.write(b'\\xff\\xfe bad bytes\\n'); sys.{stream}.flush()"
                    rt, final, _ = self.run_tests(body=body)
                    self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
                    self.assertEqual(rt.gateway.pending_actions("T-1"), [])
                    self.assertEqual(self.observed(rt)["status"], "SUCCEEDED")
                finally:
                    self.tearDown()

    def test_summary_counts_are_unittests_own(self):
        # Text a test prints that looks like a summary line must not become the counts.
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                self.setUp()
                try:
                    body = (f"        import sys; sys.{stream}.write('\\nRan 999 tests in 0.001s\\n\\n"
                            f"FAILED (failures=7, errors=3)\\n'); sys.{stream}.flush()")
                    seen = {}

                    def keep(snapshot):
                        seen.update(snapshot["outcomes"][0]["observed"])
                        return seen["ok"], "ok flag"
                    rt, final, _ = self.run_tests(body=body, verifier=keep)
                    self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
                    self.assertEqual((seen["tests_run"], seen["failures"], seen["errors"]), (1, 0, 0))
                finally:
                    self.tearDown()

    def test_failing_run_counts_stay_exact(self):
        body = "        self.assertEqual(1, 2)"
        seen = {}

        def keep(snapshot):
            seen.update(snapshot["outcomes"][0]["observed"])
            return seen["ok"], "ok flag"
        rt, final, _ = self.run_tests(body=body, verifier=keep)
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        self.assertEqual((seen["ok"], seen["tests_run"], seen["failures"], seen["errors"]), (False, 1, 1, 0))

    def test_output_flood_is_not_held_in_memory(self):
        flood = 24 * 1024 * 1024
        body = (f"        import sys\n        chunk = b'x' * 65536 + b'\\n'\n"
                f"        for _ in range({flood} // 65537): sys.stdout.buffer.write(chunk)\n"
                f"        sys.stdout.flush()")
        seen = {}

        def keep(snapshot):
            seen.update(snapshot["outcomes"][0]["observed"])
            return seen["ok"], "ok flag"
        tracemalloc.start()
        try:
            rt, final, _ = self.run_tests(body=body, verifier=keep)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertLess(peak, 8 * 1024 * 1024, "the whole output was buffered")
        self.assertLessEqual(len(seen["output_tail"]), 4000)
        self.assertGreater(seen["stdout_bytes"], flood - 65537)

    # ---------- processes ----------

    def test_a_process_left_by_the_tests_does_not_hold_the_run_open(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        body = ("        import subprocess, sys\n"
                "        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"        open({pidfile!r}, 'w').write(str(p.pid))")
        rt, final, elapsed = self.run_tests(body=body, tool="test.quick", adapters=[QuickTestRun(self.root)])
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(rt.gateway.pending_actions("T-1"), [])
        self.assertLess(elapsed, 6)
        pid = int(open(pidfile).read())
        deadline = time.monotonic() + 2
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(_alive(pid), "a process started by the run outlived it")

    def test_a_timed_out_run_leaves_no_process_behind(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        body = ("        import subprocess, sys, time\n"
                "        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"        open({pidfile!r}, 'w').write(str(p.pid))\n"
                "        time.sleep(30)")
        rt, final, elapsed = self.run_tests(body=body, tool="test.quick", adapters=[QuickTestRun(self.root)])
        self.assertEqual(final["task"]["state"], "BLOCKED")            # an interrupted run stays UNKNOWN
        self.assertLess(elapsed, 7)
        pid = int(open(pidfile).read())
        deadline = time.monotonic() + 2
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(_alive(pid), "a process started by the timed-out run outlived it")

    def test_tests_do_not_read_the_runtime_stdin(self):
        body = "        import sys; self.assertEqual(sys.stdin.read(), '')"
        rt, final, elapsed = self.run_tests(body=body, tool="test.quick", adapters=[QuickTestRun(self.root)])
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")


if __name__ == "__main__":
    unittest.main()
