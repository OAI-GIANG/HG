import unittest
from maep.core import (
    MAEPError, assess_candidate_change, architecture_proposal_allowed,
    enforce_execution_mode, retry_decision, validate_blocker,
    validate_policy_change, validate_report_status, validate_review_label
)


class ExecutionModeTests(unittest.TestCase):
    def test_read_only_allows_read(self):
        self.assertTrue(enforce_execution_mode("READ_ONLY", "READ"))

    def test_read_only_denies_write(self):
        with self.assertRaises(MAEPError):
            enforce_execution_mode("READ_ONLY", "WRITE")

    def test_read_only_denies_unknown_action(self):
        with self.assertRaises(MAEPError):
            enforce_execution_mode("READ_ONLY", "UNRECOGNIZED")


class ReportingAndRetryTests(unittest.TestCase):
    def test_not_run_cannot_be_reported_pass(self):
        with self.assertRaises(MAEPError):
            validate_report_status("PASS", "NOT_RUN")

    def test_failed_result_cannot_be_reported_pass(self):
        with self.assertRaises(MAEPError):
            validate_report_status("PASS", "FAIL")

    def test_three_attempts_stop(self):
        self.assertEqual(retry_decision(3), "STOP")

    def test_safety_stop_is_immediate(self):
        self.assertEqual(retry_decision(0, safety_stop=True), "STOP")

    def test_invalid_attempt_count_rejected(self):
        with self.assertRaises(MAEPError):
            retry_decision(-1)


class PolicyAndReviewTests(unittest.TestCase):
    def test_policy_change_requires_new_version_and_authority(self):
        self.assertTrue(validate_policy_change("1.0", "1.1", authorized=True))

    def test_policy_self_approval_rejected(self):
        with self.assertRaises(MAEPError):
            validate_policy_change("1.0", "1.1", authorized=True, self_approval=True)

    def test_same_policy_version_rejected(self):
        with self.assertRaises(MAEPError):
            validate_policy_change("1.0", "1.0", authorized=True)

    def test_internal_critique_is_not_independent(self):
        with self.assertRaises(MAEPError):
            validate_review_label("INDEPENDENT", independent_evidence=False)

    def test_independent_label_requires_evidence(self):
        self.assertTrue(validate_review_label("INDEPENDENT", independent_evidence=True))


class BlockerAndArchitectureTests(unittest.TestCase):
    def test_valid_blocker(self):
        self.assertTrue(validate_blocker({
            "blocker_id": "B-1", "known_cause": "permission missing",
            "unknowns": [], "missing_prerequisite": "write access",
            "next_action": "request authorization", "reopen_condition": "authorization granted"
        }))

    def test_incomplete_blocker_rejected(self):
        with self.assertRaises(MAEPError):
            validate_blocker({"blocker_id": "B-1"})

    def test_changed_candidate_requires_impact_assessment(self):
        result = assess_candidate_change("old", "new", ["E1", "E1", "E2"])
        self.assertTrue(result["impact_assessment_required"])
        self.assertEqual(result["invalidate_evidence_refs"], ["E1", "E2"])

    def test_same_candidate_does_not_invalidate(self):
        result = assess_candidate_change("same", "same", [])
        self.assertFalse(result["impact_assessment_required"])

    def test_duplicate_module_rejected_by_default(self):
        self.assertFalse(architecture_proposal_allowed(existing_capability=True))

    def test_security_boundary_can_justify_module(self):
        self.assertTrue(architecture_proposal_allowed(existing_capability=True, security_or_isolation_need=True))


if __name__ == "__main__":
    unittest.main()
