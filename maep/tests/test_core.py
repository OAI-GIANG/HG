import unittest
from datetime import datetime, timezone
from maep.core import (
    MAEPError, authorize_action, evaluate_gate, transition,
    validate_closure, validate_evidence, validate_task
)


def valid_task():
    return {
        "task_id": "T-1", "objective": "Inspect", "scope": {"include": ["repo"], "exclude": []},
        "inputs": [], "outputs": [{"name": "report", "description": "result"}],
        "acceptance_criteria": [{"criterion_id": "AC-1", "description": "accurate", "mandatory": True, "evidence_types": ["TEST_RESULT"]}],
        "evidence_requirements": ["test output"], "risks": [], "stop_conditions": ["scope exceeded"],
        "next_action": "verify", "state": "READY", "policy_version": "MAEP-1.2.0"
    }


def valid_evidence():
    return {
        "evidence_id": "E-1", "evidence_type": "TEST_RESULT", "source_ref": "test://unit",
        "candidate_ref": "abc123", "collected_at": "2026-10-22T10:00:00Z",
        "collector": "test-runner", "method": "unittest", "result": "PASS", "limitations": []
    }


def valid_grant():
    return {
        "authorization_id": "AUTH-1", "principal": "owner", "action": "WRITE",
        "resource": "repo:HG/maep", "scope": ["maep/"], "conditions": [],
        "task_id": "T-1", "policy_version": "MAEP-1.2.0", "decision": "ALLOW",
        "issued_at": "2026-10-22T09:00:00+00:00", "expires_at": "2026-10-23T09:00:00+00:00"
    }


def valid_capability_gate_record():
    return {
        "decision_id": "DG-AUTH-1", "candidate_ref": "candidate-abc",
        "policy_version": "MAEP-1.2.0", "scope": "repo:HG/maep",
        "capability": "authorization primitive", "inventory_status": "COMPLETE",
        "inventory_evidence_refs": ["E-INVENTORY"], "overlap_detected": True,
        "comparison_evidence_refs": ["E-COMPARE"], "decision": "EXISTING_REUSE",
        "selected_implementation": "existing-owner", "rationale": "Evidence supports reuse",
        "superiority_basis": {
            "correctness": "E-COMPARE", "security": "E-COMPARE",
            "reliability": "E-COMPARE", "functional_coverage": "E-COMPARE",
            "compatibility": "E-COMPARE", "performance_resource_cost": "E-COMPARE",
            "maintainability_operational_burden": "E-COMPARE"
        },
        "impact_analysis_refs": ["E-IMPACT"], "regression_test_refs": ["T-REGRESSION"],
        "gate_status": "PASS"
    }


def valid_capability_gate_evidence():
    refs = ("E-INVENTORY", "E-COMPARE", "E-IMPACT", "T-REGRESSION")
    return {ref: {
        "evidence_id": ref, "evidence_type": "TEST_RESULT" if ref.startswith("T-") else "ARCHITECTURE_EVIDENCE",
        "source_ref": f"test://{ref}", "candidate_ref": "candidate-abc",
        "collected_at": "2026-10-22T10:00:00Z", "collector": "unit-test",
        "method": "unittest", "result": "PASS", "limitations": []
    } for ref in refs}


class TaskContractTests(unittest.TestCase):
    def test_valid_task(self):
        self.assertTrue(validate_task(valid_task()))

    def test_missing_task_field_rejected(self):
        task = valid_task()
        del task["objective"]
        with self.assertRaises(MAEPError):
            validate_task(task)

    def test_empty_scope_rejected(self):
        task = valid_task()
        task["scope"]["include"] = []
        with self.assertRaises(MAEPError):
            validate_task(task)

    def test_unknown_state_rejected(self):
        task = valid_task()
        task["state"] = "MAGIC"
        with self.assertRaises(MAEPError):
            validate_task(task)


class EvidenceTests(unittest.TestCase):
    def test_valid_evidence(self):
        self.assertTrue(validate_evidence(valid_evidence(), "abc123"))

    def test_missing_source_rejected(self):
        ev = valid_evidence()
        del ev["source_ref"]
        with self.assertRaises(MAEPError):
            validate_evidence(ev)

    def test_candidate_mismatch_rejected(self):
        with self.assertRaises(MAEPError):
            validate_evidence(valid_evidence(), "different")


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.request = {"principal": "owner", "action": "WRITE", "resource": "repo:HG/maep",
                        "scope": ["maep/"], "task_id": "T-1", "policy_version": "MAEP-1.2.0",
                        "capability_affecting": False,
                        "capability_gate": {"applies": False, "reason": "authorization primitive fixture is not a capability change"}}
        self.now = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)

    def test_exact_authorization_allowed(self):
        # MAEP-022 is a conditional capability-evolution rule, not a global
        # prerequisite for every ordinary authorization decision.
        self.assertTrue(authorize_action(valid_grant(), self.request,
                                         trusted_policy_allow=True, now=self.now))

    def test_untrusted_allow_not_enough(self):
        with self.assertRaises(MAEPError):
            authorize_action(valid_grant(), self.request, trusted_policy_allow=False, now=self.now)

    def test_wrong_resource_denied(self):
        req = dict(self.request, resource="repo:other")
        with self.assertRaises(MAEPError):
            authorize_action(valid_grant(), req, trusted_policy_allow=True, now=self.now)

    def test_scope_escalation_denied(self):
        req = dict(self.request, scope=["maep/", "secrets/"])
        with self.assertRaises(MAEPError):
            authorize_action(valid_grant(), req, trusted_policy_allow=True, now=self.now)

    def test_expired_grant_denied(self):
        grant = valid_grant()
        grant["expires_at"] = "2026-10-22T09:30:00+00:00"
        with self.assertRaises(MAEPError):
            authorize_action(grant, self.request, trusted_policy_allow=True, now=self.now)

    def test_unsatisfied_condition_denied(self):
        grant = valid_grant()
        grant["conditions"] = ["maintenance-window"]
        with self.assertRaises(MAEPError):
            authorize_action(grant, self.request, trusted_policy_allow=True, now=self.now)

    def test_future_grant_denied(self):
        grant = valid_grant()
        grant["issued_at"] = "2026-10-22T11:00:00+00:00"
        with self.assertRaises(MAEPError):
            authorize_action(grant, self.request, trusted_policy_allow=True, now=self.now)


class TransitionTests(unittest.TestCase):
    def test_valid_transition(self):
        self.assertEqual(transition("DRAFT", "READY", guards={"task_valid": True}), "READY")

    def test_forbidden_shortcut_rejected(self):
        with self.assertRaises(MAEPError):
            transition("DRAFT", "RUNNING", guards={"authorization_valid": True})

    def test_authorization_required(self):
        with self.assertRaises(MAEPError):
            transition("PLANNED", "AUTHORIZED", guards={"authorization_valid": False})

    def test_blocker_requires_resolution(self):
        with self.assertRaises(MAEPError):
            transition("BLOCKED", "ASSESSED", blocker_resolved=False)

    def test_terminal_state_cannot_reopen(self):
        with self.assertRaises(MAEPError):
            transition("FAILED", "DRAFT")

    def test_terminal_continuation_requires_a_separate_linked_task(self):
        with self.assertRaises(TypeError):
            transition("FAILED", "DRAFT", new_task=True)

    def test_acceptance_requires_gates(self):
        with self.assertRaises(MAEPError):
            transition("VERIFYING", "ACCEPTED", guards={"mandatory_gates_pass": False})

    def test_closure_requires_all_guards(self):
        with self.assertRaises(MAEPError):
            transition("ACCEPTED", "CLOSED_VERIFIED", guards={"mandatory_gates_pass": True})


class GateAndClosureTests(unittest.TestCase):
    def test_required_gate_passes_with_resolved_evidence(self):
        gate = {"required": True, "status": "PASS", "evidence_refs": ["E-1"]}
        self.assertTrue(evaluate_gate(gate, {"E-1": valid_evidence()}))

    def test_required_not_run_gate_fails(self):
        gate = {"required": True, "status": "NOT_RUN", "evidence_refs": []}
        self.assertFalse(evaluate_gate(gate, {}))

    def test_not_applicable_requires_reason(self):
        gate = {"required": False, "status": "NOT_APPLICABLE", "evidence_refs": []}
        with self.assertRaises(MAEPError):
            evaluate_gate(gate, {})

    def test_valid_closure(self):
        ev = valid_evidence()
        gate = {"required": True, "status": "PASS", "evidence_refs": ["E-1"], "not_applicable_reason": ""}
        closure = {
            "final_state": "CLOSED_VERIFIED", "candidate_ref": "abc123", "policy_version": "MAEP-1.2.0",
            "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": ["E-1"]}],
            "evidence_refs": ["E-1"], "limitations": [], "closed_at": "2026-10-22T10:00:00Z"
        }
        self.assertTrue(validate_closure(closure, mandatory_gates=[gate], evidence_by_id={"E-1": ev},
                                         candidate_ref="abc123", policy_version="MAEP-1.2.0"))

    def test_closure_candidate_mismatch_rejected(self):
        closure = {"final_state": "CLOSED_VERIFIED", "candidate_ref": "old", "policy_version": "MAEP-1.2.0"}
        with self.assertRaises(MAEPError):
            validate_closure(closure, mandatory_gates=[], evidence_by_id={},
                             candidate_ref="new", policy_version="MAEP-1.2.0")

    def test_closure_rejects_wrong_candidate_evidence(self):
        ev = valid_evidence()
        ev["candidate_ref"] = "different-candidate"
        closure = {
            "final_state": "CLOSED_VERIFIED", "candidate_ref": "abc123", "policy_version": "MAEP-1.2.0",
            "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": ["E-1"]}],
            "evidence_refs": ["E-1"], "limitations": [], "closed_at": "2026-10-22T10:00:00Z"
        }
        gate = {"required": True, "status": "PASS", "evidence_refs": ["E-1"]}
        with self.assertRaises(MAEPError):
            validate_closure(closure, mandatory_gates=[gate], evidence_by_id={"E-1": ev},
                             candidate_ref="abc123", policy_version="MAEP-1.2.0")

    def test_closure_requires_evidence_per_criterion(self):
        ev = valid_evidence()
        closure = {
            "final_state": "CLOSED_VERIFIED", "candidate_ref": "abc123", "policy_version": "MAEP-1.2.0",
            "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": []}],
            "evidence_refs": ["E-1"], "limitations": [], "closed_at": "2026-10-22T10:00:00Z"
        }
        gate = {"required": True, "status": "PASS", "evidence_refs": ["E-1"]}
        with self.assertRaises(MAEPError):
            validate_closure(closure, mandatory_gates=[gate], evidence_by_id={"E-1": ev},
                             candidate_ref="abc123", policy_version="MAEP-1.2.0")

    def test_closure_missing_gate_rejected(self):
        ev = valid_evidence()
        closure = {
            "final_state": "CLOSED_VERIFIED", "candidate_ref": "abc123", "policy_version": "MAEP-1.2.0",
            "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": ["E-1"]}],
            "evidence_refs": ["E-1"], "limitations": [], "closed_at": "2026-10-22T10:00:00Z"
        }
        gate = {"required": True, "status": "NOT_RUN", "evidence_refs": []}
        with self.assertRaises(MAEPError):
            validate_closure(closure, mandatory_gates=[gate], evidence_by_id={"E-1": ev},
                             candidate_ref="abc123", policy_version="MAEP-1.2.0")


if __name__ == "__main__":
    unittest.main()
