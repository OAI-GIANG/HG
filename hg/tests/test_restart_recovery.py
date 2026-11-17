"""RF-2: a task interrupted by a process death is recoverable after restart, never replayed blindly.

Found 2026-11-18 with a real child-process crash: a death inside the ActionGateway effect window
left the task RUNNING. No API continues a RUNNING task, and reconcile_and_reopen recorded the
reconciliation and then failed (reopen needs BLOCKED), so the pending marker was gone and the task
stayed RUNNING for good. The state table says an unknown state stays BLOCKED; RUNNING -> BLOCKED
is an allowed edge. Crash points below are real os._exit() calls in a child process.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maep.core import MAEPError
from hg.tests import restart_crash_child as child

REPO_ROOT = Path(__file__).resolve().parents[2]


class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-rf2-")
        self.workdir = Path(self.temp.name) / "rt"
        self.target = self.workdir / "root" / "out" / "hello.txt"

    def tearDown(self):
        self.temp.cleanup()

    def crash(self, point, *, recover=True):
        proc = subprocess.run([sys.executable, "-m", "hg.tests.restart_crash_child", str(self.workdir), point],
                              cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, child.EXIT[point], proc.stderr[-2000:])
        return child.build(self.workdir, recover_interrupted=recover)

    def started(self, rt):
        return len(rt.actions.events("ACTION_STARTED"))

    def assert_blocked_on_unknown(self, rt):
        snap = rt.store.snapshot(child.TASK_ID)
        self.assertEqual(snap["task"]["state"], "BLOCKED")
        [blocker] = snap["open_blockers"]
        self.assertIn("UNKNOWN", blocker["known_cause"])
        self.assertEqual(blocker["unknowns"], ["whether the effect was applied"])
        [pending] = rt.gateway.pending_actions(child.TASK_ID)
        self.assertEqual(blocker["next_action"], "reconcile action " + pending["action_id"])
        # No blind replay: the pending action blocks every further effect on the task.
        self.assertEqual(rt.gateway.execute(child.TASK_ID, "S-1")["status"], "BLOCKED")
        self.assertEqual(self.started(rt), 1)
        return pending["action_id"]

    def test_crash_before_effect_blocks_then_reconciles_not_applied_and_closes(self):
        rt = self.crash("before-effect")
        self.assertFalse(self.target.exists())
        action_id = self.assert_blocked_on_unknown(rt)
        reopened = rt.orch.reconcile_and_reopen(child.TASK_ID, action_id, risk_reassessment="effect not applied")
        self.assertEqual((reopened["state"], reopened["finding"]["finding"]), ("ASSESSED", "NOT_APPLIED"))
        self.assertEqual(rt.orch.resume(child.TASK_ID)["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "xin chao")

    def test_crash_after_effect_blocks_then_reconciles_applied_and_closes(self):
        rt = self.crash("after-effect")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "xin chao")
        action_id = self.assert_blocked_on_unknown(rt)
        reopened = rt.orch.reconcile_and_reopen(child.TASK_ID, action_id, risk_reassessment="write is idempotent")
        self.assertEqual((reopened["state"], reopened["finding"]["finding"]), ("ASSESSED", "APPLIED"))
        self.assertEqual(rt.orch.resume(child.TASK_ID)["task"]["state"], "CLOSED_VERIFIED")

    def test_crash_before_start_blocks_as_interrupted_and_nothing_was_started(self):
        rt = self.crash("before-start")
        self.assertEqual(self.started(rt), 0)
        self.assertFalse(self.target.exists())
        self.assert_interrupted_then_closes(rt, "no action was started before the interruption")

    def test_crash_after_completion_blocks_as_interrupted_without_pending_action(self):
        rt = self.crash("after-completion")
        self.assertEqual(self.started(rt), 1)
        self.assert_interrupted_then_closes(rt, "S-1 SUCCEEDED before the interruption")

    def assert_interrupted_then_closes(self, rt, finding):
        snap = rt.store.snapshot(child.TASK_ID)
        self.assertEqual(snap["task"]["state"], "BLOCKED")
        [blocker] = snap["open_blockers"]
        self.assertIn("INTERRUPTED", blocker["known_cause"])
        self.assertEqual(blocker["unknowns"], [])
        self.assertEqual(rt.gateway.pending_actions(child.TASK_ID), [])
        evidence = rt.orch.record_observation(child.TASK_ID, source_ref="actions.jsonl",
                                              method="operator read of the action ledger",
                                              result=finding)
        rt.orch.reopen(child.TASK_ID, evidence_refs=[evidence], risk_reassessment="write is idempotent")
        self.assertEqual(rt.orch.resume(child.TASK_ID)["task"]["state"], "CLOSED_VERIFIED")

    def test_reopen_after_restart_without_live_authority_stays_blocked(self):
        from maep.authority.trust_anchor import TrustAnchorError
        rt = self.crash("after-effect")
        action_id = self.assert_blocked_on_unknown(rt)

        def unavailable():
            raise TrustAnchorError("owner manifest unreachable")
        with patch.object(rt.orch._issuer._manifest, "current", unavailable):
            with self.assertRaisesRegex(MAEPError, "trust root unavailable"):
                rt.orch.reconcile_and_reopen(child.TASK_ID, action_id, risk_reassessment="write is idempotent")
        self.assertEqual(rt.store.snapshot(child.TASK_ID)["task"]["state"], "BLOCKED")
        self.assertEqual(self.started(rt), 1)                     # nothing re-executed
        # The outcome is known now (reconciled APPLIED); a later reopen with authority proceeds.
        evidence = rt.orch.record_observation(child.TASK_ID, source_ref="reconcile:" + action_id,
                                              method="adapter.reconcile", result="APPLIED")
        rt.orch.reopen(child.TASK_ID, evidence_refs=[evidence], risk_reassessment="write is idempotent")
        self.assertEqual(rt.orch.resume(child.TASK_ID)["task"]["state"], "CLOSED_VERIFIED")

    def test_recovery_runs_once_and_is_stable_across_restarts(self):
        self.crash("after-effect")
        second = child.build(self.workdir)
        snap = second.store.snapshot(child.TASK_ID)
        self.assertEqual(snap["task"]["state"], "BLOCKED")
        self.assertEqual(len(snap["open_blockers"]), 1)
        self.assertEqual(second.recovered, [])

    def test_recovery_is_opt_in_and_off_by_default(self):
        plain = self.crash("after-effect", recover=False)
        self.assertEqual(plain.recovered, [])
        self.assertEqual(plain.store.snapshot(child.TASK_ID)["task"]["state"], "RUNNING")
        self.assertEqual(len(plain.gateway.pending_actions(child.TASK_ID)), 1)   # still no replay

    def test_recovered_task_ids_are_reported(self):
        rt = self.crash("before-effect")
        self.assertEqual(rt.recovered, [child.TASK_ID])

    def test_reconcile_and_reopen_refuses_a_task_that_is_not_blocked_without_recording(self):
        rt = child.build(self.workdir)
        with patch.object(type(rt.orch), "_block", side_effect=MAEPError("blocker write failed")):
            with self.assertRaises(MAEPError):
                self._run_unknown(rt)
        self.assertEqual(rt.store.snapshot(child.TASK_ID)["task"]["state"], "RUNNING")
        [pending] = rt.gateway.pending_actions(child.TASK_ID)
        with self.assertRaisesRegex(MAEPError, "BLOCKED"):
            rt.orch.reconcile_and_reopen(child.TASK_ID, pending["action_id"], risk_reassessment="checked")
        self.assertEqual(rt.actions.events("ACTION_RECONCILED"), [])
        self.assertEqual(len(rt.gateway.pending_actions(child.TASK_ID)), 1)

    def _run_unknown(self, rt):
        """Run the task with an effect whose outcome is UNKNOWN; _block (patched) then fails."""
        from hg.tools import gateway as gw
        real = gw.LocalFileWriteAdapter.execute

        def unknown(adapter, params, permit=None):
            real(adapter, params, permit)
            raise RuntimeError("outcome lost")          # -> UNKNOWN, effect applied
        with patch.object(gw.LocalFileWriteAdapter, "execute", unknown):
            rt.orch.execute_task(child.task(), child.steps())


class ServeRecoveryTests(unittest.TestCase):
    """Through `hg serve`: a state dir left with a RUNNING task starts with it BLOCKED and logged."""

    def test_serve_blocks_and_logs_an_interrupted_task(self):
        import contextlib, io, json, os, signal, socket, threading, time
        from maep.authority.canonical_source import CanonicalManifest
        from maep.tests.test_canonical_source import FakeGitHub
        from hg.service import CONFIG_SCHEMA, run
        from hg.tests.release_helpers import make_tiny_release
        temp = tempfile.TemporaryDirectory(prefix="hg-rf2-serve-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        release = make_tiny_release(root / "release")
        state = root / "state"
        state.mkdir(mode=0o700)
        proc = subprocess.run([sys.executable, "-m", "hg.tests.restart_crash_child", str(state), "after-effect"],
                              cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, child.EXIT["after-effect"], proc.stderr[-2000:])
        token = root / "service.token"
        token.write_text("a-very-long-test-token-that-is-not-a-secret\n", encoding="ascii")
        token.chmod(0o600)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        config = root / "service.json"
        config.write_text(json.dumps({
            "schema": CONFIG_SCHEMA, "host": "127.0.0.1", "port": port, "state_dir": str(state),
            "token_file": str(token), "release_root": str(release["root"]),
            "release_manifest": str(release["manifest"]), "release_id": release["doc"]["release_id"],
            "max_body_bytes": 65536}), encoding="utf-8")
        config.chmod(0o600)
        authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0)
        out = io.StringIO()

        def stopper():
            deadline = time.monotonic() + 20
            while "HG_RUNTIME_READY" not in out.getvalue() and time.monotonic() < deadline:
                time.sleep(0.02)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=stopper, daemon=True).start()
        with patch.object(CanonicalManifest, "from_github", return_value=authority), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run(config), 0)
        self.assertIn(f"HG_RECOVERED_INTERRUPTED tasks=1 ids={child.TASK_ID}", out.getvalue())
        self.assertLess(out.getvalue().index("HG_RECOVERED_INTERRUPTED"), out.getvalue().index("HG_RUNTIME_READY"))
        from hg.__main__ import status          # read-only replay; the state now needs the service's session
        [task] = status(state)["tasks"]
        self.assertEqual((task["task_id"], task["state"], len(task["pending_actions"])), (child.TASK_ID, "BLOCKED", 1))
        started = [l for l in (state / "actions.jsonl").read_text(encoding="utf-8").splitlines() if '"ACTION_STARTED"' in l]
        self.assertEqual(len(started), 1)


if __name__ == "__main__":
    unittest.main()
