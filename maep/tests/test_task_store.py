"""RT-01 acceptance tests: TaskStore owns task state and derives every transition guard.

Acceptance criteria (RUNTIME_ENFORCEMENT_PLAN_V1 RT-01):
- direct state mutation is impossible through the public API;
- RUNNING -> VERIFYING is denied with no recorded result;
- a stale expected_version is rejected;
- a ledger append failure leaves state unchanged.
"""
import copy
import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from maep.core import MAEPError, POLICY_VERSION
from maep.ledger import append_event, read_events
from maep.policy import PolicyEvaluator
from maep.task_store import TaskStore

T0 = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)


def draft_task(task_id="T-1", inputs=None):
    return {
        "task_id": task_id, "objective": "Implement RT-01", "scope": {"include": ["maep/"], "exclude": []},
        "inputs": inputs or [], "outputs": [{"name": "code", "description": "task store"}],
        "acceptance_criteria": [{"criterion_id": "AC-1", "description": "tests pass", "mandatory": True,
                                 "evidence_types": ["TEST_RESULT"]}],
        "evidence_requirements": ["unit test output"], "risks": [], "stop_conditions": ["scope exceeded"],
        "next_action": "assess", "state": "DRAFT", "policy_version": POLICY_VERSION,
    }


def grant(task_id="T-1", expires="2026-10-23T11:00:00+00:00"):
    return {
        "authorization_id": f"AUTH-{task_id}", "principal": "stt", "action": "WRITE",
        "resource": "repo:HG/maep", "scope": ["maep/"], "conditions": [], "task_id": task_id,
        "policy_version": POLICY_VERSION, "decision": "ALLOW",
        "issued_at": "2026-10-23T09:00:00+00:00", "expires_at": expires,
    }


def request(task_id="T-1"):
    return {"authorization_id": f"AUTH-{task_id}", "principal": "stt", "action": "WRITE",
            "resource": "repo:HG/maep", "scope": ["maep/"], "task_id": task_id,
            "policy_version": POLICY_VERSION}


def evidence(evidence_id="E-1", candidate="abc123"):
    return {"evidence_id": evidence_id, "evidence_type": "TEST_RESULT", "source_ref": "test://unit",
            "candidate_ref": candidate, "collected_at": "2026-10-23T10:05:00Z", "collector": "unittest",
            "method": "python -m unittest", "result": "PASS", "limitations": []}


def gate(refs=("E-1",)):
    return {"gate_id": "G-1", "required": True, "status": "PASS", "evidence_refs": list(refs)}


def closure(candidate="abc123", refs=("E-1",)):
    return {"final_state": "CLOSED_VERIFIED", "candidate_ref": candidate, "policy_version": POLICY_VERSION,
            "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": list(refs)}],
            "evidence_refs": list(refs), "limitations": [], "closed_at": "2026-10-23T10:30:00+00:00"}


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "ledger.jsonl"
        self.clock = Clock()
        self.evaluator = PolicyEvaluator([grant()], lambda condition, req: True)
        self.store = TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=self.clock)

    def version(self, task_id="T-1"):
        return self.store.snapshot(task_id)["version"]

    def step(self, target, task_id="T-1"):
        return self.store.apply_transition(task_id, target, expected_version=self.version(task_id))

    def advance_to(self, target, task_id="T-1"):
        """Drive a task along the happy path, recording the facts each guard needs."""
        order = ["READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING", "VERIFYING", "ACCEPTED",
                 "CLOSED_VERIFIED"]
        for state in order[:order.index(target) + 1]:
            if state == "AUTHORIZED":
                self.store.record_authorization_request(task_id, request(task_id),
                                                        expected_version=self.version(task_id))
            if state == "VERIFYING":
                self.store.record_result(task_id, result_ref="run://1", candidate_ref="abc123",
                                         expected_version=self.version(task_id))
            if state == "ACCEPTED":
                self.store.record_evidence(task_id, evidence(), expected_version=self.version(task_id))
                self.store.set_mandatory_gates(task_id, [gate()], expected_version=self.version(task_id))
            if state == "CLOSED_VERIFIED":
                self.store.record_closure(task_id, closure(), expected_version=self.version(task_id))
            self.step(state, task_id)

    def assertUnchanged(self, before, task_id="T-1"):
        self.assertEqual(self.store.snapshot(task_id), before)


class AcceptanceCriteriaTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())

    def test_running_to_verifying_denied_without_recorded_result(self):
        self.advance_to("RUNNING")
        before, events = self.store.snapshot("T-1"), len(read_events(self.ledger))
        with self.assertRaises(MAEPError):
            self.step("VERIFYING")
        self.assertUnchanged(before)
        self.assertEqual(len(read_events(self.ledger)), events)

    def test_stale_expected_version_rejected(self):
        stale = self.version()
        self.step("READY")
        before = self.store.snapshot("T-1")
        with self.assertRaises(MAEPError):
            self.store.apply_transition("T-1", "ASSESSED", expected_version=stale)
        with self.assertRaises(MAEPError):
            self.store.record_authorization_request("T-1", request(), expected_version=stale)
        self.assertUnchanged(before)

    def test_transition_returns_new_version(self):
        before = self.version()
        self.assertEqual(self.store.apply_transition("T-1", "READY", expected_version=before), before + 1)
        self.assertEqual(self.version(), before + 1)

    def test_bool_expected_version_rejected(self):
        with self.assertRaises(MAEPError):
            self.store.apply_transition("T-1", "READY", expected_version=True)

    def test_ledger_append_failure_leaves_state_unchanged(self):
        def failing_append(path, event):
            raise OSError("disk full")

        store = TaskStore(Path(self.directory.name) / "other.jsonl", policy_evaluator=self.evaluator,
                          clock=self.clock, ledger_append=failing_append)
        with self.assertRaises(MAEPError):
            store.create_task(draft_task("T-9"))
        with self.assertRaises(MAEPError):
            store.snapshot("T-9")

        flaky = {"fail": False}

        def flaky_append(path, event):
            if flaky["fail"]:
                raise OSError("disk full")
            return append_event(path, event)

        store = TaskStore(Path(self.directory.name) / "flaky.jsonl", policy_evaluator=self.evaluator,
                          clock=self.clock, ledger_append=flaky_append)
        store.create_task(draft_task("T-8"))
        before = store.snapshot("T-8")
        flaky["fail"] = True
        with self.assertRaises(MAEPError):
            store.apply_transition("T-8", "READY", expected_version=before["version"])
        self.assertEqual(store.snapshot("T-8"), before)

    def test_snapshot_is_a_copy(self):
        snapshot = self.store.snapshot("T-1")
        snapshot["task"]["state"] = "CLOSED_VERIFIED"
        snapshot["version"] = 99
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "DRAFT")
        self.assertEqual(self.store.snapshot("T-1")["version"], 1)

    def test_created_task_is_copied_from_caller(self):
        task = draft_task("T-2")
        self.store.create_task(task)
        task["state"] = "RUNNING"
        self.assertEqual(self.store.snapshot("T-2")["task"]["state"], "DRAFT")

    def test_callers_cannot_supply_guards(self):
        parameters = inspect.signature(TaskStore.apply_transition).parameters
        self.assertNotIn("guards", parameters)
        self.assertNotIn("blocker_resolved", parameters)
        with self.assertRaises(TypeError):
            self.store.apply_transition("T-1", "READY", expected_version=1, guards={"task_valid": True})

    def test_public_api_has_no_state_setter(self):
        public = {name for name in dir(self.store) if not name.startswith("_")}
        self.assertEqual(public, {
            "apply_transition", "create_task", "record_authorization_request", "record_blocker",
            "record_closure", "record_evidence", "record_reassessment", "record_result",
            "set_mandatory_gates", "snapshot",
        })

    def test_forbidden_shortcut_denied_and_not_logged(self):
        events = len(read_events(self.ledger))
        with self.assertRaises(MAEPError):
            self.step("RUNNING")
        self.assertEqual(len(read_events(self.ledger)), events)


class TaskCreationTests(StoreTestCase):
    def test_task_must_start_in_draft(self):
        task = draft_task()
        task["state"] = "READY"
        with self.assertRaises(MAEPError):
            self.store.create_task(task)

    def test_policy_version_must_match(self):
        task = draft_task()
        task["policy_version"] = "MAEP-1.0.0"
        with self.assertRaises(MAEPError):
            self.store.create_task(task)

    def test_invalid_contract_rejected(self):
        task = draft_task()
        del task["stop_conditions"]
        with self.assertRaises(MAEPError):
            self.store.create_task(task)

    def test_duplicate_task_id_rejected(self):
        self.store.create_task(draft_task())
        with self.assertRaises(MAEPError):
            self.store.create_task(draft_task())

    def test_existing_ledger_requires_recovery(self):
        self.store.create_task(draft_task())
        with self.assertRaises(MAEPError):
            TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=self.clock)

    def test_every_accepted_change_is_in_the_ledger_first(self):
        self.store.create_task(draft_task())
        self.advance_to("CLOSED_VERIFIED")
        events = read_events(self.ledger)
        self.assertEqual([e["version"] for e in events], list(range(1, self.version() + 1)))
        self.assertEqual(events[-1]["type"], "TRANSITION")
        self.assertEqual(events[-1]["data"], {"from": "ACCEPTED", "to": "CLOSED_VERIFIED"})
        self.assertTrue(all(e["task_id"] == "T-1" and e["policy_version"] == POLICY_VERSION for e in events))


class AuthorityTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())
        self.advance_to("PLANNED")

    def test_authorized_requires_recorded_request(self):
        with self.assertRaises(MAEPError):
            self.step("AUTHORIZED")

    def test_request_for_another_task_rejected(self):
        with self.assertRaises(MAEPError):
            self.store.record_authorization_request("T-1", request("T-2"), expected_version=self.version())

    def test_authorized_denied_when_policy_denies(self):
        self.clock.now = T0 + timedelta(hours=2)
        self.store.record_authorization_request("T-1", request(), expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.step("AUTHORIZED")

    def test_running_rechecks_authority_at_transition_time(self):
        self.store.record_authorization_request("T-1", request(), expected_version=self.version())
        self.step("AUTHORIZED")
        self.clock.now = T0 + timedelta(hours=2)
        with self.assertRaises(MAEPError):
            self.step("RUNNING")
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "AUTHORIZED")

    def test_no_authority_provider_blocks_authorization(self):
        store = TaskStore(Path(self.directory.name) / "noauth.jsonl", clock=self.clock)
        store.create_task(draft_task())
        for target in ("READY", "ASSESSED", "PLANNED"):
            store.apply_transition("T-1", target, expected_version=store.snapshot("T-1")["version"])
        with self.assertRaises(MAEPError):
            store.record_authorization_request("T-1", request(), expected_version=store.snapshot("T-1")["version"])
        with self.assertRaises(MAEPError):
            store.apply_transition("T-1", "AUTHORIZED", expected_version=store.snapshot("T-1")["version"])


class ResultEvidenceAndClosureTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())

    def test_result_only_while_running_or_unverified(self):
        with self.assertRaises(MAEPError):
            self.store.record_result("T-1", result_ref="run://1", candidate_ref="abc123",
                                     expected_version=self.version())

    def test_acceptance_denied_for_evidence_of_another_candidate(self):
        self.advance_to("VERIFYING")
        self.store.record_evidence("T-1", evidence(candidate="old999"), expected_version=self.version())
        self.store.set_mandatory_gates("T-1", [gate()], expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.step("ACCEPTED")

    def test_acceptance_denied_without_gates_or_with_unknown_evidence(self):
        self.advance_to("VERIFYING")
        with self.assertRaises(MAEPError):
            self.step("ACCEPTED")
        with self.assertRaises(MAEPError):
            self.store.set_mandatory_gates("T-1", [gate(refs=("E-404",))], expected_version=self.version())

    def test_optional_gate_not_accepted_as_mandatory(self):
        self.advance_to("VERIFYING")
        optional = gate()
        optional["required"] = False
        with self.assertRaises(MAEPError):
            self.store.set_mandatory_gates("T-1", [optional], expected_version=self.version())

    def test_candidate_change_invalidates_old_evidence(self):
        self.advance_to("VERIFYING")
        self.store.record_evidence("T-1", evidence(), expected_version=self.version())
        self.store.set_mandatory_gates("T-1", [gate()], expected_version=self.version())
        self.step("UNVERIFIED")
        self.store.record_result("T-1", result_ref="run://2", candidate_ref="def456", expected_version=self.version())
        self.step("VERIFYING")
        with self.assertRaises(MAEPError):
            self.step("ACCEPTED")
        self.store.record_evidence("T-1", evidence("E-2", candidate="def456"), expected_version=self.version())
        self.store.set_mandatory_gates("T-1", [gate(refs=("E-2",))], expected_version=self.version())
        self.step("ACCEPTED")

    def test_duplicate_evidence_id_rejected(self):
        self.advance_to("VERIFYING")
        self.store.record_evidence("T-1", evidence(), expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.store.record_evidence("T-1", evidence(), expected_version=self.version())

    def test_closure_denied_without_closure_record(self):
        self.advance_to("ACCEPTED")
        with self.assertRaises(MAEPError):
            self.step("CLOSED_VERIFIED")

    def test_closure_denied_with_open_blocker(self):
        self.advance_to("ACCEPTED")
        self.store.record_closure("T-1", closure(), expected_version=self.version())
        blocker = {"blocker_id": "B-1", "known_cause": "flaky CI", "unknowns": [], "missing_prerequisite": "green CI",
                   "next_action": "rerun", "reopen_condition": "CI green"}
        self.store.record_blocker("T-1", blocker, expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.step("CLOSED_VERIFIED")

    def test_closure_denied_for_closure_of_another_candidate(self):
        self.advance_to("ACCEPTED")
        self.store.record_closure("T-1", closure(candidate="zzz000"), expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.step("CLOSED_VERIFIED")


class BlockerReassessmentTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())
        self.advance_to("RUNNING")
        self.blocker = {"blocker_id": "B-1", "known_cause": "dependency missing", "unknowns": ["eta"],
                        "missing_prerequisite": "dependency", "next_action": "install", "reopen_condition": "installed"}
        self.store.record_blocker("T-1", self.blocker, expected_version=self.version())
        self.step("BLOCKED")

    def test_blocking_requires_a_recorded_blocker(self):
        store = TaskStore(Path(self.directory.name) / "b.jsonl", clock=self.clock,
                          policy_evaluator=PolicyEvaluator([grant("T-3")], lambda c, r: True))
        store.create_task(draft_task("T-3"))
        for target in ("READY", "ASSESSED", "PLANNED"):
            store.apply_transition("T-3", target, expected_version=store.snapshot("T-3")["version"])
        store.record_authorization_request("T-3", request("T-3"), expected_version=store.snapshot("T-3")["version"])
        for target in ("AUTHORIZED", "RUNNING"):
            store.apply_transition("T-3", target, expected_version=store.snapshot("T-3")["version"])
        with self.assertRaises(MAEPError):
            store.apply_transition("T-3", "BLOCKED", expected_version=store.snapshot("T-3")["version"])

    def test_reassessment_required_before_reopening(self):
        with self.assertRaises(MAEPError):
            self.step("ASSESSED")

    def test_reassessment_must_cite_stored_evidence(self):
        with self.assertRaises(MAEPError):
            self.store.record_reassessment("T-1", resolution_evidence_refs=["E-404"], risk_assessment="low",
                                           expected_version=self.version())

    def test_reassessment_requires_risk_assessment(self):
        self.store.record_evidence("T-1", evidence("E-B"), expected_version=self.version())
        with self.assertRaises(MAEPError):
            self.store.record_reassessment("T-1", resolution_evidence_refs=["E-B"], risk_assessment=" ",
                                           expected_version=self.version())

    def test_reopening_also_requires_fresh_authority(self):
        self.store.record_evidence("T-1", evidence("E-B"), expected_version=self.version())
        self.store.record_reassessment("T-1", resolution_evidence_refs=["E-B"], risk_assessment="low",
                                       expected_version=self.version())
        self.clock.now = T0 + timedelta(hours=2)
        with self.assertRaises(MAEPError):
            self.step("ASSESSED")
        self.clock.now = T0
        self.step("ASSESSED")
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "ASSESSED")
        self.assertEqual(self.store.snapshot("T-1")["open_blockers"], [])

    def test_reassessment_from_an_earlier_block_does_not_reopen_a_new_one(self):
        self.store.record_evidence("T-1", evidence("E-B"), expected_version=self.version())
        self.store.record_reassessment("T-1", resolution_evidence_refs=["E-B"], risk_assessment="low",
                                       expected_version=self.version())
        for target in ("ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING"):
            self.step(target)
        second = dict(self.blocker, blocker_id="B-2")
        self.store.record_blocker("T-1", second, expected_version=self.version())
        self.step("BLOCKED")
        with self.assertRaises(MAEPError):
            self.step("ASSESSED")

    def test_reassessment_only_while_blocked(self):
        store_state = self.store.snapshot("T-1")["task"]["state"]
        self.assertEqual(store_state, "BLOCKED")
        self.store.record_evidence("T-1", evidence("E-B"), expected_version=self.version())
        self.store.record_reassessment("T-1", resolution_evidence_refs=["E-B"], risk_assessment="low",
                                       expected_version=self.version())
        self.step("ASSESSED")
        with self.assertRaises(MAEPError):
            self.store.record_reassessment("T-1", resolution_evidence_refs=["E-B"], risk_assessment="low",
                                           expected_version=self.version())


class TerminalAndLinkedTaskTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.create_task(draft_task())
        self.advance_to("RUNNING")
        self.step("FAILED")

    def test_terminal_task_cannot_transition(self):
        before = self.store.snapshot("T-1")
        with self.assertRaises(MAEPError):
            self.step("DRAFT")
        self.assertUnchanged(before)

    def test_terminal_task_rejects_new_facts(self):
        with self.assertRaises(MAEPError):
            self.store.record_evidence("T-1", evidence(), expected_version=self.version())

    def test_linked_continuation_task_created(self):
        successor = draft_task("T-1b", inputs=[{"kind": "TASK", "ref_id": "T-1"}])
        self.store.create_task(successor)
        self.assertEqual(self.store.snapshot("T-1b")["task"]["state"], "DRAFT")
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "FAILED")

    def test_unknown_task_reference_rejected(self):
        with self.assertRaises(MAEPError):
            self.store.create_task(draft_task("T-2", inputs=[{"kind": "TASK", "ref_id": "T-404"}]))


if __name__ == "__main__":
    unittest.main()
