"""WS-04/WS-03: rooted file adapters act only on the path that was authorized.

The gateway authorizes `file:<lexical path>` and checks scope on that lexical path. The
adapter must therefore act on that same file, not on wherever a symlink inside the root
points, and must not block on a FIFO. Each case goes through the real runtime path
(BrainOrchestrator -> ActionGateway -> adapter) and asserts that:

* a symlink anywhere on an in-scope path (final component or a parent directory) is
  refused before any effect, and the out-of-scope target is neither written nor returned;
* directory walks (code.search, code.symbols) never read a symlinked or non-regular file;
* a FIFO is refused or skipped within 5 s instead of blocking the adapter thread;
* controls: regular in-scope files are still written, read, searched and diffed.

Symlinks here model untrusted workspace content (for example a checked-out repository).
A same-UID process racing the check is out of scope (owner decision Q3).
"""
import os
import threading
import time
import unittest
from datetime import timedelta

from hg.tests.support import NOW, PRINCIPAL, TempDirMixin, grant, make_task, write_step

DEADLINE_S = 5.0
SECRET = "OUT-OF-SCOPE-SECRET helper(\n"


def step(tool, action, path, scope=("out/",), step_id="S-1", **extra):
    return {"step_id": step_id, "tool": tool, "action": action, "resource": f"file:{path}",
            "scope": list(scope), "authorization_id": f"AUTH-{step_id}", "params": {"path": path, **extra}}


def grant_for(s, task_id="T-1"):
    return {"authorization_id": s["authorization_id"], "principal": PRINCIPAL, "action": s["action"],
            "resource": s["resource"], "scope": s["scope"], "conditions": [], "task_id": task_id,
            "policy_version": "MAEP-1.1.0", "decision": "ALLOW",
            "issued_at": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(hours=2)).isoformat()}


def outcomes(rt):
    """(status, observed) of every completed or refused action, from the ledger."""
    return [e["payload"] for e in rt.actions.events("ACTION_COMPLETED")]


class Base(TempDirMixin):
    def setUp(self):
        super().setUp()
        (self.root / "secret").mkdir(parents=True)
        (self.root / "out").mkdir()
        self.secret = self.root / "secret" / "key.txt"
        self.secret.write_text(SECRET, encoding="utf-8")

    def run_steps(self, steps, verifiers=None):
        rt = self.build([grant_for(s) for s in steps], verifiers=verifiers or {})
        result = {}

        def go():
            result["final"] = rt.orch.execute_task(make_task(), steps)
        thread = threading.Thread(target=go, daemon=True)
        started = time.monotonic()
        thread.start()
        thread.join(DEADLINE_S)
        self.assertFalse(thread.is_alive(), f"adapter blocked for more than {DEADLINE_S} s")
        self.assertLess(time.monotonic() - started, DEADLINE_S)
        return rt, result["final"]

    def assert_secret_untouched(self, rt):
        self.assertEqual(self.secret.read_text(encoding="utf-8"), SECRET)
        for payload in outcomes(rt):
            self.assertNotIn("OUT-OF-SCOPE-SECRET", repr(payload))

    def assert_not_closed(self, final):
        self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")

    def assert_refused(self, rt, final, step_id="S-1"):
        """No effect ran to success for this step: refused before the effect or failed."""
        self.assert_not_closed(final)
        done = [p["status"] for p in outcomes(rt) if p["step_id"] == step_id]
        self.assertFalse(set(done) & {"SUCCEEDED", "SUCCEEDED_UNVERIFIED"}, done)


class SymlinkWriteTests(Base):
    def write(self, path="out/hello.txt"):
        rt = self.build([grant(resource=f"file:{path}")], verifiers={"AC-1": lambda _s: (True, "any")})
        return rt, rt.orch.execute_task(make_task(), [write_step(path=path)])

    def test_symlinked_file_inside_scope_does_not_write_its_target(self):
        os.symlink(self.secret, self.root / "out" / "hello.txt")
        rt, final = self.write()
        self.assert_secret_untouched(rt)
        self.assert_not_closed(final)
        self.assertTrue(os.path.islink(self.root / "out" / "hello.txt"))

    def test_relative_symlink_is_refused_too(self):
        os.symlink("../secret/key.txt", self.root / "out" / "hello.txt")
        rt, final = self.write()
        self.assert_secret_untouched(rt)
        self.assert_not_closed(final)

    def test_symlinked_parent_directory_does_not_write_outside_scope(self):
        os.symlink(self.root / "secret", self.root / "out" / "dir")
        rt, final = self.write("out/dir/key.txt")
        self.assert_secret_untouched(rt)
        self.assert_not_closed(final)
        self.assertEqual(sorted(p.name for p in (self.root / "secret").iterdir()), ["key.txt"])

    def test_symlinked_scope_directory_itself_is_refused(self):
        (self.root / "out").rmdir()
        os.symlink(self.root / "secret", self.root / "out")
        rt, final = self.write("out/key.txt")
        self.assert_secret_untouched(rt)
        self.assert_not_closed(final)

    def test_control_regular_write_still_closes(self):
        rt, final = self.write()
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual((self.root / "out" / "hello.txt").read_text(encoding="utf-8"), "xin chao")
        self.assert_secret_untouched(rt)


class SymlinkReadTests(Base):
    def test_fs_read_of_symlink_does_not_return_target(self):
        os.symlink(self.secret, self.root / "out" / "x.txt")
        rt, final = self.run_steps([step("fs.read", "READ", "out/x.txt")])
        self.assert_secret_untouched(rt)
        self.assert_refused(rt, final)

    def test_fs_read_through_symlinked_parent_is_refused(self):
        os.symlink(self.root / "secret", self.root / "out" / "dir")
        rt, final = self.run_steps([step("fs.read", "READ", "out/dir/key.txt")])
        self.assert_secret_untouched(rt)
        self.assert_refused(rt, final)

    def test_code_diff_of_symlink_is_refused(self):
        os.symlink(self.secret, self.root / "out" / "x.txt")
        rt, final = self.run_steps([step("code.diff", "READ", "out/x.txt", against="")])
        self.assert_secret_untouched(rt)
        self.assert_refused(rt, final)

    def test_search_walk_skips_symlinked_files_inside_and_outside_root(self):
        (self.root / "out" / "src").mkdir()
        os.symlink(self.secret, self.root / "out" / "src" / "in_root.py")
        outside = os.path.join(self.tmp, "outside.py")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write(SECRET)
        os.symlink(outside, self.root / "out" / "src" / "outside_root.py")
        (self.root / "out" / "src" / "real.py").write_text("x = helper(1)\n", encoding="utf-8")
        steps = [step("code.search", "READ", "out/src", pattern="helper("),
                 step("code.symbols", "READ", "out/src", step_id="S-2")]
        rt, final = self.run_steps(steps)
        self.assert_secret_untouched(rt)
        ok = [p for p in outcomes(rt) if p["status"] == "SUCCEEDED"]
        self.assertEqual(len(ok), 2)
        self.assertEqual(ok[0]["observed"]["files_scanned"], 1)       # only real.py was read

    def test_search_of_a_symlinked_start_path_is_refused(self):
        os.symlink(self.root / "secret", self.root / "out" / "src")
        rt, final = self.run_steps([step("code.search", "READ", "out/src", pattern="SECRET")])
        self.assert_secret_untouched(rt)
        self.assert_refused(rt, final)


@unittest.skipUnless(hasattr(os, "mkfifo"), "platform has no FIFOs")
class FifoTests(Base):
    def test_search_walk_skips_a_fifo(self):
        (self.root / "out" / "src").mkdir()
        os.mkfifo(self.root / "out" / "src" / "pipe.py")
        (self.root / "out" / "src" / "real.py").write_text("x = helper(1)\n", encoding="utf-8")
        rt, _final = self.run_steps([step("code.search", "READ", "out/src", pattern="helper("),
                                     step("code.symbols", "READ", "out/src", step_id="S-2")])
        ok = [p for p in outcomes(rt) if p["status"] == "SUCCEEDED"]
        self.assertEqual(len(ok), 2)
        self.assertEqual(ok[0]["observed"]["match_count"], 1)

    def test_search_started_on_a_fifo_is_refused(self):
        os.mkfifo(self.root / "out" / "pipe.py")
        rt, final = self.run_steps([step("code.search", "READ", "out/pipe.py", pattern="x")])
        self.assert_refused(rt, final)

    def test_fs_read_of_a_fifo_is_refused(self):
        os.mkfifo(self.root / "out" / "pipe.txt")
        rt, final = self.run_steps([step("fs.read", "READ", "out/pipe.txt")])
        self.assert_refused(rt, final)

    def test_code_diff_of_a_fifo_is_refused(self):
        os.mkfifo(self.root / "out" / "pipe.txt")
        rt, final = self.run_steps([step("code.diff", "READ", "out/pipe.txt", against="")])
        self.assert_refused(rt, final)


class ControlReadTests(Base):
    def test_regular_read_search_and_diff_still_work(self):
        (self.root / "out" / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        steps = [step("fs.read", "READ", "out/a.py"),
                 step("code.search", "READ", "out", pattern="helper", step_id="S-2"),
                 step("code.diff", "READ", "out/a.py", step_id="S-3", against="def helper():\n")]
        rt, _final = self.run_steps(steps)
        ok = {p["step_id"]: p for p in outcomes(rt) if p["status"] == "SUCCEEDED"}
        self.assertEqual(set(ok), {"S-1", "S-2", "S-3"})
        self.assertEqual(ok["S-2"]["observed"]["match_count"], 1)
        self.assertEqual(ok["S-3"]["observed"]["added"], 1)


if __name__ == "__main__":
    unittest.main()
