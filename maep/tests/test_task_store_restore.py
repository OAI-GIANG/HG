"""RT-05 and MAEP-006 extensions of the canonical TaskStore: restore, single writer, plans."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from maep.core import MAEPError
from maep.ledger import read_events
from maep.policy import PolicyEvaluator
from maep.task_store import TaskStore
from maep.tests.test_task_store import Clock, draft_task, evidence, grant, request

BLOCKER = {"blocker_id": "B-1", "known_cause": "tool timed out", "unknowns": ["effect applied?"],
           "missing_prerequisite": "reconciliation", "next_action": "reconcile",
           "reopen_condition": "outcome known"}
PLAN = [{"step_id": "S-1", "tool": "fs.write"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "ledger.jsonl"
        self.clock = Clock()
        self.evaluator = PolicyEvaluator([grant()], lambda c, r: True)
        self.store = TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=self.clock)

    def v(self, store=None):
        return (store or self.store).snapshot("T-1")["version"]

    def to_blocked(self, store=None):
        store = store or self.store
        store.create_task(draft_task())
        for target in ("READY", "ASSESSED"):
            store.apply_transition("T-1", target, expected_version=self.v(store))
        store.record_plan("T-1", PLAN, expected_version=self.v(store))
        store.apply_transition("T-1", "PLANNED", expected_version=self.v(store))
        store.record_authorization_request("T-1", request(), expected_version=self.v(store))
        for target in ("AUTHORIZED", "RUNNING"):
            store.apply_transition("T-1", target, expected_version=self.v(store))
        store.record_evidence("T-1", evidence(), expected_version=self.v(store))
        store.record_blocker("T-1", BLOCKER, expected_version=self.v(store))
        store.apply_transition("T-1", "BLOCKED", expected_version=self.v(store))

    def restore(self, evaluator=None):
        return TaskStore.restore(self.ledger, policy_evaluator=evaluator or self.evaluator, clock=self.clock)

    def rewrite(self, index, mutate):
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[index])
        mutate(event)
        lines[index] = json.dumps(event, sort_keys=True, separators=(",", ":"))
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")


class RestoreTests(Base):
    def test_restore_reproduces_every_record_field(self):
        self.to_blocked()
        self.assertEqual(self.restore().snapshot("T-1"), self.store.snapshot("T-1"))

    def test_plain_constructor_still_refuses_non_empty_ledger(self):
        self.to_blocked()
        with self.assertRaisesRegex(MAEPError, "TaskStore.restore"):
            TaskStore(self.ledger, policy_evaluator=self.evaluator)

    def test_restored_store_continues_the_same_history(self):
        self.to_blocked()
        restored = self.restore()
        restored.record_reassessment("T-1", resolution_evidence_refs=["E-1"], risk_assessment="safe",
                                     expected_version=self.v(restored))
        restored.apply_transition("T-1", "ASSESSED", expected_version=self.v(restored))
        ids = [e["event_id"] for e in read_events(self.ledger)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.restore().snapshot("T-1")["task"]["state"], "ASSESSED")

    def test_authority_is_re_evaluated_after_restore(self):
        self.to_blocked()
        restored = self.restore(PolicyEvaluator([], lambda c, r: True))   # grant gone after restart
        restored.record_reassessment("T-1", resolution_evidence_refs=["E-1"], risk_assessment="safe",
                                     expected_version=self.v(restored))
        with self.assertRaisesRegex(MAEPError, "fresh authority and risk"):
            restored.apply_transition("T-1", "ASSESSED", expected_version=self.v(restored))

    def test_expiry_during_downtime_denies_running(self):
        self.store.create_task(draft_task())
        for target in ("READY", "ASSESSED"):
            self.store.apply_transition("T-1", target, expected_version=self.v())
        self.store.record_plan("T-1", PLAN, expected_version=self.v())
        self.store.apply_transition("T-1", "PLANNED", expected_version=self.v())
        self.store.record_authorization_request("T-1", request(), expected_version=self.v())
        self.store.apply_transition("T-1", "AUTHORIZED", expected_version=self.v())
        self.clock.now += timedelta(hours=2)
        restored = self.restore()
        with self.assertRaisesRegex(MAEPError, "valid authorization required"):
            restored.apply_transition("T-1", "RUNNING", expected_version=self.v(restored))

    def test_version_gap_rejected(self):
        self.to_blocked()
        self.rewrite(3, lambda e: e.update(version=e["version"] + 50, event_id=f"T-1@{e['version'] + 50}"))
        with self.assertRaisesRegex(MAEPError, "inconsistent"):
            self.restore()

    def test_mismatched_event_id_rejected(self):
        self.to_blocked()
        self.rewrite(2, lambda e: e.update(event_id="T-1@99"))
        with self.assertRaisesRegex(MAEPError, "malformed"):
            self.restore()

    def test_transition_from_wrong_state_rejected(self):
        self.to_blocked()
        self.rewrite(1, lambda e: e["data"].update({"from": "PLANNED"}))
        with self.assertRaisesRegex(MAEPError, "recorded state"):
            self.restore()

    def test_other_policy_version_rejected(self):
        self.to_blocked()
        self.rewrite(0, lambda e: e.update(policy_version="MAEP-1.0.0"))
        with self.assertRaisesRegex(MAEPError, "policy version"):
            self.restore()

    def test_unknown_event_type_rejected(self):
        self.to_blocked()
        self.rewrite(4, lambda e: e.update(type="STATE_OVERRIDE"))
        with self.assertRaisesRegex(MAEPError, "inconsistent"):
            self.restore()


class WriterClaimTests(Base):
    def test_second_claim_refused(self):
        self.store.claim_writer()
        with self.assertRaisesRegex(MAEPError, "already claimed"):
            self.store.claim_writer()

    def test_after_claim_every_mutation_needs_the_writer(self):
        writer = self.store.claim_writer()
        writer.create_task(draft_task())
        calls = [
            lambda: self.store.create_task(draft_task("T-2")),
            lambda: self.store.apply_transition("T-1", "READY", expected_version=1),
            lambda: self.store.record_plan("T-1", PLAN, expected_version=1),
            lambda: self.store.record_authorization_request("T-1", request(), expected_version=1),
            lambda: self.store.record_result("T-1", result_ref="r", candidate_ref="c", expected_version=1),
            lambda: self.store.record_evidence("T-1", evidence(), expected_version=1),
            lambda: self.store.set_mandatory_gates("T-1", [], expected_version=1),
            lambda: self.store.record_closure("T-1", {}, expected_version=1),
            lambda: self.store.record_blocker("T-1", BLOCKER, expected_version=1),
            lambda: self.store.record_reassessment("T-1", resolution_evidence_refs=["E-1"],
                                                   risk_assessment="x", expected_version=1),
        ]
        for call in calls:
            with self.assertRaisesRegex(MAEPError, "writer is claimed"):
                call()
        self.assertEqual(self.store.snapshot("T-1")["version"], 1)
        writer.apply_transition("T-1", "READY", expected_version=1)
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "READY")

    def test_writer_exposes_only_mutation_methods(self):
        writer = self.store.claim_writer()
        with self.assertRaises(AttributeError):
            writer.claim_writer
        with self.assertRaises(AttributeError):
            writer._records

    def test_unclaimed_store_keeps_existing_behaviour(self):
        self.store.create_task(draft_task())
        self.assertEqual(self.v(), 1)


class PlanTests(Base):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())

    def test_plan_only_while_assessed(self):
        with self.assertRaisesRegex(MAEPError, "only while ASSESSED"):
            self.store.record_plan("T-1", PLAN, expected_version=1)

    def test_plan_shape_checked(self):
        for target in ("READY", "ASSESSED"):
            self.store.apply_transition("T-1", target, expected_version=self.v())
        for bad in ([], [{"tool": "x"}], [{"step_id": "S"}, {"step_id": "S"}], ["S-1"]):
            with self.assertRaises(MAEPError):
                self.store.record_plan("T-1", bad, expected_version=self.v())

    def test_plan_is_not_a_state_setter(self):
        for target in ("READY", "ASSESSED"):
            self.store.apply_transition("T-1", target, expected_version=self.v())
        self.store.record_plan("T-1", PLAN, expected_version=self.v())
        snap = self.store.snapshot("T-1")
        self.assertEqual((snap["task"]["state"], snap["plan"]), ("ASSESSED", PLAN))


if __name__ == "__main__":
    unittest.main()
