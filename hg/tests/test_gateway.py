"""RT-02/RT-05: ActionGateway denies effects without fresh authority and never replays uncertain actions.

The effect target is the real local filesystem under a temporary root, not a fake.
The task is driven to RUNNING through the real orchestrator and canonical TaskStore.
"""
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from maep.core import MAEPError
from hg.tools.gateway import ActionGateway, AdapterFailure, LocalFileWriteAdapter
from hg.verification.evidence import EventLog
from hg.tests.support import PRINCIPAL, TempDirMixin, grant, make_task, write_step


class WritesThenCrashes(LocalFileWriteAdapter):
    name = "crash.write"

    def _perform(self, params):
        super()._perform(params)
        raise RuntimeError("process died after the write")


class RaisesTimeout(LocalFileWriteAdapter):
    name = "timeout.write"

    def _perform(self, params):
        raise TimeoutError("remote side did not answer")


class Hangs(LocalFileWriteAdapter):
    name = "hang.write"
    timeout_s = 0.05

    def __init__(self, root, release):
        super().__init__(root)
        self._release = release

    def _perform(self, params):
        self._release.wait(5)
        return {}


class NeverVerifies(LocalFileWriteAdapter):
    name = "noverify.write"

    def verify(self, params, observed):
        return False


class KnownFailure(LocalFileWriteAdapter):
    name = "fail.write"

    def _perform(self, params):
        raise AdapterFailure("refused by target before any change")


class ConcurrencyProbe(LocalFileWriteAdapter):
    """Records how many effects were in flight at once, and holds each one briefly."""

    name = "probe.write"

    def __init__(self, root):
        super().__init__(root)
        self.guard = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0

    def _perform(self, params):
        with self.guard:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            time.sleep(0.05)
            return super()._perform(params)
        finally:
            with self.guard:
                self.in_flight -= 1


class GatewayFixture(TempDirMixin):
    def setUp(self):
        super().setUp()
        self.release = threading.Event()
        self.extra = [WritesThenCrashes(self.root), RaisesTimeout(self.root), Hangs(self.root, self.release),
                      NeverVerifies(self.root), KnownFailure(self.root)]

    def tearDown(self):
        self.release.set()
        super().tearDown()

    def running(self, steps, grants=(grant(),), mode="AUTHORIZED_EXECUTION", extra_adapters=()):
        self.rt = self.build(grants, mode=mode, extra_adapters=list(self.extra) + list(extra_adapters))
        orch = self.rt.orch
        orch.submit_task(make_task())
        orch.assess("T-1")
        orch.plan("T-1", steps)
        orch.authorize("T-1")
        orch._move("T-1", "RUNNING")
        return self.rt.gateway

    def target_file(self, rel="out/hello.txt"):
        return self.root / rel

    def kinds(self):
        return [e["kind"] for e in self.rt.actions.events()]


class AllowedEffectTests(GatewayFixture):
    def test_authorized_write_succeeds_and_is_recorded(self):
        gw = self.running([write_step()])
        outcome = gw.execute("T-1", "S-1")
        self.assertEqual(outcome["status"], "SUCCEEDED")
        self.assertEqual(self.target_file().read_text(encoding="utf-8"), "xin chao")
        self.assertEqual(self.kinds(), ["ACTION_STARTED", "ACTION_COMPLETED"])
        self.assertEqual(gw.pending_actions(), [])
        self.assertEqual(outcome["decision"]["decision"], "ALLOW")

    def test_registry_declares_contract(self):
        gw = self.running([write_step()])
        entry = next(t for t in gw.registry() if t["name"] == "fs.write")
        self.assertEqual((entry["action"], entry["idempotent"], entry["params"]),
                         ("WRITE", True, {"path": "str", "content": "str"}))

    def test_preflight_has_no_effect_and_no_record(self):
        gw = self.running([write_step()])
        before = len(self.rt.actions.events())
        self.assertEqual([p["decision"]["decision"] for p in gw.preflight("T-1")], ["ALLOW"])
        self.assertEqual(len(self.rt.actions.events()), before)
        self.assertFalse(self.target_file().exists())


class DeniedEffectTests(GatewayFixture):
    def assertNoEffect(self, outcome, status, reason_fragment):
        self.assertEqual(outcome["status"], status)
        self.assertIn(reason_fragment, outcome["reason"])
        self.assertFalse(self.target_file().exists())
        self.assertNotIn("ACTION_STARTED", self.kinds())

    def test_grant_expiring_between_start_and_effect_denies(self):
        gw = self.running([write_step()])
        self.clock.advance(hours=3)
        self.assertNoEffect(gw.execute("T-1", "S-1"), "DENIED", "expired")

    def test_read_only_mode_denies_write(self):
        gw = self.running([write_step()], mode="READ_ONLY")
        self.assertNoEffect(gw.execute("T-1", "S-1"), "DENIED", "READ_ONLY")

    def test_planned_resource_must_match_real_effect(self):
        step = write_step(resource="file:out/other.txt")
        gw = self.running([step], grants=(grant(resource="file:out/other.txt"),))
        self.assertNoEffect(gw.execute("T-1", "S-1"), "DENIED", "does not match")

    def test_adapter_enforces_scope_independently(self):
        step = write_step(scope=("docs/",))
        gw = self.running([step], grants=(grant(scope=("docs/",)),))
        self.assertNoEffect(gw.execute("T-1", "S-1"), "DENIED", "scope")

    def test_path_traversal_is_invalid_input(self):
        step = write_step(path="../escape.txt", resource="file:../escape.txt")
        gw = self.running([step], grants=(grant(resource="file:../escape.txt"),))
        outcome = gw.execute("T-1", "S-1")
        self.assertEqual(outcome["status"], "INVALID_INPUT")
        self.assertFalse((self.workdir / "escape.txt").exists())

    def test_unknown_tool_reported_unavailable(self):
        gw = self.running([write_step(tool="fs.nuke")])
        self.assertNoEffect(gw.execute("T-1", "S-1"), "TOOL_UNAVAILABLE", "fs.nuke")

    def test_step_not_in_plan_blocked(self):
        gw = self.running([write_step()])
        self.assertNoEffect(gw.execute("T-1", "S-INJECTED"), "BLOCKED", "not in the recorded plan")

    def test_task_not_running_blocked(self):
        gw = self.running([write_step()])
        self.rt.orch._writer.record_blocker("T-1", {
            "blocker_id": "B-1", "known_cause": "stop", "unknowns": [], "missing_prerequisite": "x",
            "next_action": "y", "reopen_condition": "z"}, expected_version=self.rt.orch._version("T-1"))
        self.rt.orch._move("T-1", "BLOCKED")
        self.assertNoEffect(gw.execute("T-1", "S-1"), "BLOCKED", "not RUNNING")

    def test_unknown_task_blocked(self):
        gw = self.running([write_step()])
        self.assertNoEffect(gw.execute("T-404", "S-1"), "BLOCKED", "unknown task_id")

    def test_evidence_capture_failure_before_effect_blocks(self):
        gw = self.running([write_step()])
        real_append = self.rt.actions.append

        def failing(kind, task_id, payload):
            if kind == "ACTION_STARTED":
                raise OSError("disk full")
            return real_append(kind, task_id, payload)

        with mock.patch.object(self.rt.actions, "append", side_effect=failing):
            self.assertNoEffect(gw.execute("T-1", "S-1"), "BLOCKED", "evidence capture failed")


class SerializedEffectTests(GatewayFixture):
    def test_two_concurrent_effects_never_overlap_and_keep_the_ledger_loadable(self):
        probe = ConcurrencyProbe(self.root)
        gw = self.running([write_step(tool="probe.write")], extra_adapters=[probe])
        outcomes, errors = [], []

        def call():
            try:
                outcomes.append(gw.execute("T-1", "S-1"))
            except Exception as exc:                      # a raised error is a failed assertion
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(probe.max_in_flight, 1)           # one effect at a time in this process
        self.assertEqual([o["status"] for o in outcomes], ["SUCCEEDED", "SUCCEEDED"])
        started = self.rt.actions.events("ACTION_STARTED")
        self.assertEqual(len(started), 2)
        self.assertEqual(len({e["payload"]["action_id"] for e in started}), 2)
        reopened = EventLog(self.rt.actions.path)          # the race would duplicate a sequence number
        self.assertEqual([e["seq"] for e in reopened.events()], list(range(1, len(self.rt.actions.events()) + 1)))
        self.assertEqual(gw.pending_actions(), [])


class AuthorityRecheckTests(GatewayFixture):
    def test_authority_withdrawn_between_decision_and_effect_stops_the_write(self):
        """MAEP-003: the permit re-asks the evaluator immediately before the effect."""
        gw = self.running([write_step()])
        real = gw._evaluator
        calls = []

        class WithdrawnAfterTheDecision:
            def evaluate(self, request, *, now=None):
                calls.append(request["resource"])
                if len(calls) == 1:
                    return real.evaluate(request, now=now)
                return {"decision": "DENY", "reason": "authority withdrawn after the decision"}

        gw._evaluator = WithdrawnAfterTheDecision()
        outcome = gw.execute("T-1", "S-1")
        self.assertEqual(len(calls), 2)                     # decision, then the pre-effect re-check
        self.assertEqual(outcome["status"], "FAILED")
        self.assertIn("no longer valid", outcome["reason"])
        self.assertFalse(self.target_file().exists())
        self.assertEqual(gw.pending_actions(), [])          # nothing happened, nothing left pending


class OutcomeTaxonomyTests(GatewayFixture):
    def test_known_failure_is_failed_and_not_pending(self):
        gw = self.running([write_step(tool="fail.write")])
        self.assertEqual(gw.execute("T-1", "S-1")["status"], "FAILED")
        self.assertEqual(gw.pending_actions(), [])

    def test_unverified_success_is_distinct(self):
        gw = self.running([write_step(tool="noverify.write")])
        self.assertEqual(gw.execute("T-1", "S-1")["status"], "SUCCEEDED_UNVERIFIED")

    def test_raised_timeout_is_unknown(self):
        gw = self.running([write_step(tool="timeout.write")])
        self.assertEqual(gw.execute("T-1", "S-1")["status"], "UNKNOWN")

    def test_real_timeout_is_unknown(self):
        gw = self.running([write_step(tool="hang.write")])
        outcome = gw.execute("T-1", "S-1")
        self.assertEqual(outcome["status"], "UNKNOWN")
        self.assertIn("timed out", outcome["reason"])


class ReconcileBeforeRetryTests(GatewayFixture):
    def test_unknown_outcome_blocks_further_effects(self):
        gw = self.running([write_step(tool="crash.write"), write_step("S-2")])
        self.assertEqual(gw.execute("T-1", "S-1")["status"], "UNKNOWN")
        blocked = gw.execute("T-1", "S-2")
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("unreconciled", blocked["reason"])

    def test_pending_action_survives_restart(self):
        gw = self.running([write_step(tool="crash.write")])
        gw.execute("T-1", "S-1")
        restarted = ActionGateway(self.rt.store, self.rt.evaluator, EventLog(self.rt.actions.path, clock=self.clock),
                                  [WritesThenCrashes(self.root)], principal=PRINCIPAL)
        self.assertEqual(len(restarted.pending_actions("T-1")), 1)

    def test_reconcile_inspects_live_state_and_clears(self):
        gw = self.running([write_step(tool="crash.write")])
        action_id = gw.execute("T-1", "S-1")["action_id"]
        self.assertEqual(gw.reconcile(action_id)["finding"], "APPLIED")
        self.assertEqual(gw.pending_actions(), [])
        self.assertEqual(self.kinds().count("ACTION_STARTED"), 1)   # reconciled, not replayed

    def test_reconcile_detects_effect_not_applied(self):
        gw = self.running([write_step(tool="timeout.write")])
        action_id = gw.execute("T-1", "S-1")["action_id"]
        self.assertEqual(gw.reconcile(action_id)["finding"], "NOT_APPLIED")

    def test_reconcile_unknown_action_rejected(self):
        gw = self.running([write_step()])
        with self.assertRaises(MAEPError):
            gw.reconcile("nope")


class ConstructionTests(GatewayFixture):
    def test_duplicate_tool_names_rejected(self):
        with self.assertRaises(MAEPError):
            self.build([], extra_adapters=[LocalFileWriteAdapter(self.root)])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(MAEPError):
            self.build([], mode="GOD_MODE")


if __name__ == "__main__":
    unittest.main()
