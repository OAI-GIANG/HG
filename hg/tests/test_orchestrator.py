"""RT-03/RT-04/RT-05: BrainOrchestrator end to end through the canonical TaskStore, gateway and gate.

Covers catalogue T-006 (MAEP-006): one coordinator holds the only task-state writer.
Restart tests rebuild the whole runtime from its ledgers in the same work directory.
"""
import unittest

from maep.core import MAEPError, POLICY_VERSION
from maep.ledger import read_events
from hg.brain.orchestrator import BrainOrchestrator
from hg.tools.gateway import AdapterFailure, LocalFileWriteAdapter
from hg.tests.support import TempDirMixin, content_verifier, grant, make_task, write_step


class CrashOnce(LocalFileWriteAdapter):
    """Writes, then dies once before reporting. Later calls behave normally."""
    name = "crashonce.write"
    crashes_left = 1

    def execute(self, params):
        observed = super().execute(params)
        if CrashOnce.crashes_left:
            CrashOnce.crashes_left -= 1
            raise RuntimeError("process died after the write")
        return observed


class AlwaysFails(LocalFileWriteAdapter):
    name = "fail.write"

    def execute(self, params):
        raise AdapterFailure("target rejected the request")


class Base(TempDirMixin):
    def transitions(self):
        return [e["data"]["to"] for e in read_events(self.workdir / "tasks.jsonl")
                if e["type"] == "TRANSITION" and e["task_id"] == "T-1"]


class HappyPathTests(Base):
    def test_task_reaches_closed_verified_only_with_linked_evidence(self):
        rt = self.build([grant()])
        final = rt.orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual((self.root / "out/hello.txt").read_text(encoding="utf-8"), "xin chao")
        closure = final["closure"]
        self.assertEqual(closure["candidate_ref"], final["result"]["candidate_ref"])
        self.assertTrue(closure["evidence_refs"] and set(closure["evidence_refs"]) <= set(final["evidence"]))
        self.assertEqual(self.transitions(), ["READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING",
                                              "VERIFYING", "ACCEPTED", "CLOSED_VERIFIED"])

    def test_two_step_plan_closes(self):
        rt = self.build([grant(), grant("AUTH-W2", resource="file:out/b.txt")])
        steps = [write_step(), write_step("S-2", path="out/b.txt", authorization_id="AUTH-W2")]
        self.assertEqual(rt.orch.execute_task(make_task(), steps)["task"]["state"], "CLOSED_VERIFIED")
        self.assertTrue((self.root / "out/b.txt").is_file())


class SoleCoordinatorTests(Base):
    def test_second_orchestrator_cannot_claim_writer(self):
        rt = self.build([grant()])
        with self.assertRaisesRegex(MAEPError, "already claimed"):
            BrainOrchestrator(rt.store, rt.gateway, rt.gate, principal="intruder")

    def test_direct_store_mutation_refused_once_claimed(self):
        rt = self.build([grant()])
        with self.assertRaisesRegex(MAEPError, "writer is claimed"):
            rt.store.create_task(make_task())


class NoFalseClosureTests(Base):
    def test_failed_verification_ends_unverified(self):
        rt = self.build([grant()], verifiers={"AC-1": content_verifier(self.root, expected="something else")})
        final = rt.orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        self.assertIsNone(final["closure"])
        with self.assertRaises(MAEPError):
            rt.orch.close("T-1")

    def test_missing_verifier_is_not_run_not_pass(self):
        rt = self.build([grant()], verifiers={})
        self.assertEqual(rt.orch.execute_task(make_task(), [write_step()])["task"]["state"], "UNVERIFIED")

    def test_verifier_exception_is_fail_and_preserved(self):
        def broken(_snapshot):
            raise RuntimeError("checker crashed")
        rt = self.build([grant()], verifiers={"AC-1": broken})
        final = rt.orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        self.assertEqual([e["result"] for e in final["evidence"].values()], ["FAIL"])   # MAEP-015

    def test_evidence_recorded_on_another_task_is_ignored(self):
        rt = self.build([grant()], verifiers={})
        rt.orch.submit_task(make_task())
        rt.orch.assess("T-1")
        rt.orch.plan("T-1", [write_step()])
        rt.orch.authorize("T-1")
        candidate = rt.orch.run("T-1")["candidate_ref"]
        rt.orch.submit_task(make_task("T-2"))
        rt.orch._writer.record_evidence("T-2", {
            "evidence_id": "EV-FORGED", "evidence_type": "TEST_RESULT", "source_ref": "elsewhere",
            "candidate_ref": candidate, "collected_at": self.clock().isoformat(), "collector": "x",
            "method": "x", "result": "PASS", "limitations": [], "test_ids": ["AC-1"]},
            expected_version=rt.orch._version("T-2"))
        self.assertEqual(rt.orch.verify("T-1"), "UNVERIFIED")

    def test_task_with_no_mandatory_criterion_cannot_close(self):
        rt = self.build([grant()])
        task = make_task()
        task["acceptance_criteria"][0]["mandatory"] = False
        self.assertEqual(rt.orch.execute_task(task, [write_step()])["task"]["state"], "UNVERIFIED")


class AuthorityTests(Base):
    def assertNeverExecuted(self, rt):
        self.assertFalse((self.root / "out/hello.txt").exists())
        self.assertEqual(rt.actions.events("ACTION_STARTED"), [])

    def assertStaysPlanned(self, rt, steps=None):
        final = rt.orch.execute_task(make_task(), steps or [write_step()])
        self.assertEqual(final["task"]["state"], "PLANNED")
        self.assertNeverExecuted(rt)
        self.assertTrue(any(e["result"].startswith("DENY") for e in final["evidence"].values()))

    def test_missing_grant_keeps_task_planned(self):
        self.assertStaysPlanned(self.build([]))

    def test_grant_for_another_principal_denied(self):
        self.assertStaysPlanned(self.build([grant(principal="someone-else")]))

    def test_deny_decision_grant_denied(self):
        self.assertStaysPlanned(self.build([grant(decision="DENY")]))

    def test_one_unauthorized_step_stops_the_whole_plan_before_any_effect(self):
        steps = [write_step(), write_step("S-2", path="out/b.txt", authorization_id="AUTH-W2")]
        self.assertStaysPlanned(self.build([grant()]), steps)

    def test_grant_added_in_a_later_session_lets_task_resume(self):
        self.build([]).orch.execute_task(make_task(), [write_step()])
        second = self.build([grant()])                 # restart with the owner's new grant
        self.assertEqual(second.store.snapshot("T-1")["task"]["state"], "PLANNED")
        self.assertEqual(second.orch.resume("T-1")["task"]["state"], "CLOSED_VERIFIED")


class RetryLimitTests(Base):
    def test_known_failure_retried_three_times_then_blocked(self):
        rt = self.build([grant()], extra_adapters=[AlwaysFails(self.root)])
        final = rt.orch.execute_task(make_task(), [write_step(tool="fail.write")])
        self.assertEqual(final["task"]["state"], "BLOCKED")
        self.assertEqual(len(rt.actions.events("ACTION_STARTED")), 3)
        self.assertIn("retry limit", final["open_blockers"][0]["missing_prerequisite"])


class RecoveryTests(Base):
    def setUp(self):
        super().setUp()
        CrashOnce.crashes_left = 1

    def runtime(self, grants=None):
        return self.build([grant()] if grants is None else grants, extra_adapters=[CrashOnce(self.root)])

    def blocked_runtime(self):
        rt = self.runtime()
        final = rt.orch.execute_task(make_task(), [write_step(tool="crashonce.write")])
        self.assertEqual(final["task"]["state"], "BLOCKED")
        return rt, rt.gateway.pending_actions("T-1")[0]["action_id"]

    def test_unknown_outcome_blocks_then_reconcile_reopen_resume_closes(self):
        rt, action_id = self.blocked_runtime()
        self.assertEqual(rt.store.snapshot("T-1")["open_blockers"][0]["unknowns"], ["whether the effect was applied"])
        reopened = rt.orch.reconcile_and_reopen("T-1", action_id, risk_reassessment="write is idempotent")
        self.assertEqual((reopened["state"], reopened["finding"]["finding"]), ("ASSESSED", "APPLIED"))
        self.assertEqual(rt.orch.resume("T-1")["task"]["state"], "CLOSED_VERIFIED")

    def test_restart_preserves_block_and_pending_action(self):
        _first, _action = self.blocked_runtime()
        second = self.runtime()                        # fresh objects, rebuilt from both ledgers
        self.assertEqual(second.store.snapshot("T-1")["task"]["state"], "BLOCKED")
        pending = second.gateway.pending_actions("T-1")
        self.assertEqual(len(pending), 1)
        second.orch.reconcile_and_reopen("T-1", pending[0]["action_id"], risk_reassessment="checked")
        self.assertEqual(second.orch.resume("T-1")["task"]["state"], "CLOSED_VERIFIED")

    def test_reopen_without_risk_reassessment_refused(self):
        rt, action_id = self.blocked_runtime()
        with self.assertRaisesRegex(MAEPError, "risk assessment"):
            rt.orch.reconcile_and_reopen("T-1", action_id, risk_reassessment="")
        self.assertEqual(rt.store.snapshot("T-1")["task"]["state"], "BLOCKED")

    def test_reopen_refused_when_authority_has_expired(self):
        rt, action_id = self.blocked_runtime()
        self.clock.advance(hours=3)
        with self.assertRaisesRegex(MAEPError, "fresh authority and risk"):
            rt.orch.reconcile_and_reopen("T-1", action_id, risk_reassessment="checked")

    def test_reconcile_of_another_tasks_action_refused(self):
        rt, action_id = self.blocked_runtime()
        rt.orch.submit_task(make_task("T-2"))
        with self.assertRaisesRegex(MAEPError, "no pending action"):
            rt.orch.reconcile_and_reopen("T-2", action_id, risk_reassessment="x")


class LedgerTests(Base):
    def test_task_ledger_events_carry_policy_version(self):
        self.build([grant()]).orch.execute_task(make_task(), [write_step()])
        self.assertEqual({e["policy_version"] for e in read_events(self.workdir / "tasks.jsonl")}, {POLICY_VERSION})


if __name__ == "__main__":
    unittest.main()
