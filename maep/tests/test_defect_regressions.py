"""Regression tests for defects reproduced in the Phase 1 audit (probes P2-P7)."""
import unittest
from maep import core
from maep.core import MAEPError, retry_decision, transition, validate_closure


def evidence():
    return {
        "evidence_id": "E-1", "evidence_type": "TEST_RESULT", "source_ref": "test://unit",
        "candidate_ref": "abc123", "collected_at": "2026-10-22T10:00:00Z",
        "collector": "test-runner", "method": "unittest", "result": "PASS", "limitations": []
    }


def closure(**overrides):
    record = {
        "final_state": "CLOSED_VERIFIED", "candidate_ref": "abc123", "policy_version": "MAEP-1.0.0",
        "criteria_results": [{"criterion_id": "AC-1", "status": "PASS", "evidence_refs": ["E-1"]}],
        "evidence_refs": ["E-1"], "limitations": [], "closed_at": "2026-10-22T10:00:00Z"
    }
    record.update(overrides)
    return record


def close(record, evidence_by_id=None):
    gate = {"required": True, "status": "PASS", "evidence_refs": ["E-1"]}
    return validate_closure(record, mandatory_gates=[gate],
                            evidence_by_id={"E-1": evidence()} if evidence_by_id is None else evidence_by_id,
                            candidate_ref="abc123", policy_version="MAEP-1.0.0")


def draft_task(task_id="T-2", predecessor="T-1", state="DRAFT"):
    inputs = [{"ref_id": predecessor, "kind": "TASK"}] if predecessor else []
    return {"task_id": task_id, "state": state, "inputs": inputs}


class VerifyingEntryGuardTests(unittest.TestCase):
    """P2: STATE_TRANSITION_TABLE_V1 requires a result/candidate before VERIFYING."""

    def test_running_to_verifying_without_result_rejected(self):
        with self.assertRaises(MAEPError):
            transition("RUNNING", "VERIFYING")

    def test_running_to_verifying_without_candidate_rejected(self):
        with self.assertRaises(MAEPError):
            transition("RUNNING", "VERIFYING", guards={"result_recorded": True})

    def test_running_to_verifying_blank_candidate_rejected(self):
        with self.assertRaises(MAEPError):
            transition("RUNNING", "VERIFYING", guards={"result_recorded": True, "candidate_ref": " "})

    def test_unverified_to_verifying_requires_same_guard(self):
        with self.assertRaises(MAEPError):
            transition("UNVERIFIED", "VERIFYING")

    def test_verifying_with_result_and_candidate_allowed(self):
        guards = {"result_recorded": True, "candidate_ref": "abc123"}
        self.assertEqual(transition("RUNNING", "VERIFYING", guards=guards), "VERIFYING")
        self.assertEqual(transition("UNVERIFIED", "VERIFYING", guards=guards), "VERIFYING")


class BlockerReassessmentGuardTests(unittest.TestCase):
    """P3: BLOCKED -> ASSESSED needs resolution evidence and fresh authority/risk assessment."""

    def full_guards(self):
        return {"blocker_resolution_evidence_refs": ["E-9"], "authority_reassessed": True,
                "risk_reassessed": True}

    def test_resolved_flag_alone_rejected(self):
        with self.assertRaises(MAEPError):
            transition("BLOCKED", "ASSESSED", blocker_resolved=True)

    def test_missing_resolution_evidence_rejected(self):
        guards = self.full_guards()
        guards["blocker_resolution_evidence_refs"] = []
        with self.assertRaises(MAEPError):
            transition("BLOCKED", "ASSESSED", guards=guards, blocker_resolved=True)

    def test_missing_authority_reassessment_rejected(self):
        guards = self.full_guards()
        del guards["authority_reassessed"]
        with self.assertRaises(MAEPError):
            transition("BLOCKED", "ASSESSED", guards=guards, blocker_resolved=True)

    def test_missing_risk_reassessment_rejected(self):
        guards = self.full_guards()
        guards["risk_reassessed"] = "yes"
        with self.assertRaises(MAEPError):
            transition("BLOCKED", "ASSESSED", guards=guards, blocker_resolved=True)

    def test_full_reassessment_allowed(self):
        self.assertEqual(transition("BLOCKED", "ASSESSED", guards=self.full_guards(), blocker_resolved=True),
                         "ASSESSED")


class TerminalContinuationTests(unittest.TestCase):
    """P4: a caller flag must not move a terminal task back to DRAFT."""

    def test_caller_flag_no_longer_reopens_terminal_task(self):
        # The new_task flag was removed; continuation goes through validate_linked_task.
        with self.assertRaises(TypeError):
            transition("CLOSED_VERIFIED", "DRAFT", new_task=True)

    def test_every_terminal_state_rejects_draft(self):
        for state in ("FAILED", "CANCELLED", "CLOSED_VERIFIED"):
            with self.subTest(state=state), self.assertRaises(MAEPError):
                transition(state, "DRAFT")

    def test_linked_draft_task_accepted(self):
        for state in ("FAILED", "CANCELLED", "CLOSED_VERIFIED"):
            with self.subTest(state=state):
                predecessor = {"task_id": "T-1", "state": state}
                self.assertTrue(core.validate_linked_task(predecessor, draft_task()))

    def test_successor_without_task_reference_rejected(self):
        with self.assertRaises(MAEPError):
            core.validate_linked_task({"task_id": "T-1", "state": "FAILED"}, draft_task(predecessor=None))

    def test_successor_referencing_other_task_rejected(self):
        with self.assertRaises(MAEPError):
            core.validate_linked_task({"task_id": "T-1", "state": "FAILED"}, draft_task(predecessor="T-7"))

    def test_successor_reusing_predecessor_id_rejected(self):
        with self.assertRaises(MAEPError):
            core.validate_linked_task({"task_id": "T-1", "state": "FAILED"}, draft_task(task_id="T-1"))

    def test_non_terminal_predecessor_rejected(self):
        with self.assertRaises(MAEPError):
            core.validate_linked_task({"task_id": "T-1", "state": "RUNNING"}, draft_task())

    def test_successor_must_start_in_draft(self):
        with self.assertRaises(MAEPError):
            core.validate_linked_task({"task_id": "T-1", "state": "FAILED"}, draft_task(state="READY"))

    def test_malformed_records_rejected(self):
        for predecessor, successor in ((None, draft_task()), ({"task_id": "T-1", "state": "FAILED"}, "T-2"),
                                       ({"task_id": "T-1", "state": "FAILED"},
                                        {"task_id": "T-2", "state": "DRAFT", "inputs": "T-1"})):
            with self.subTest(predecessor=predecessor, successor=successor), self.assertRaises(MAEPError):
                core.validate_linked_task(predecessor, successor)


class ClosureInputValidationTests(unittest.TestCase):
    """P6/P7: closure.schema.json requires limitations: string[] and closed_at: date-time."""

    def test_reference_closure_still_valid(self):
        self.assertTrue(close(closure()))

    def test_empty_string_limitations_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(limitations=""))

    def test_non_string_limitation_item_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(limitations=[None]))

    def test_empty_closed_at_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(closed_at=""))

    def test_unparseable_closed_at_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(closed_at="yesterday"))

    def test_naive_closed_at_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(closed_at="2026-10-22T10:00:00"))

    def test_non_dict_criterion_raises_domain_error(self):
        with self.assertRaises(MAEPError):
            close(closure(criteria_results=["AC-1"]))

    def test_criteria_results_wrong_type_raises_domain_error(self):
        with self.assertRaises(MAEPError):
            close(closure(criteria_results="PASS"))

    def test_criterion_without_id_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(criteria_results=[{"status": "PASS", "evidence_refs": ["E-1"]}]))

    def test_closure_evidence_refs_wrong_type_rejected(self):
        with self.assertRaises(MAEPError):
            close(closure(evidence_refs="E-1"))

    def test_non_dict_evidence_record_raises_domain_error(self):
        with self.assertRaises(MAEPError):
            close(closure(), evidence_by_id={"E-1": "PASS"})


class RetryDecisionTypeTests(unittest.TestCase):
    """P5: attempt_count must be a plain int; bool is an int subclass in Python."""

    def test_bool_attempt_count_rejected(self):
        for value in (True, False):
            with self.subTest(value=value), self.assertRaises(MAEPError):
                retry_decision(value)

    def test_non_int_attempt_count_rejected(self):
        for value in (1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(MAEPError):
                retry_decision(value)

    def test_negative_attempt_count_rejected(self):
        with self.assertRaises(MAEPError):
            retry_decision(-1)

    def test_integer_boundaries(self):
        self.assertEqual(retry_decision(0), "CONTINUE")
        self.assertEqual(retry_decision(2), "CONTINUE")
        self.assertEqual(retry_decision(3), "STOP")

    def test_non_bool_stop_flags_rejected(self):
        with self.assertRaises(MAEPError):
            retry_decision(0, safety_stop="no")
        with self.assertRaises(MAEPError):
            retry_decision(0, progress_possible=None)


if __name__ == "__main__":
    unittest.main()
