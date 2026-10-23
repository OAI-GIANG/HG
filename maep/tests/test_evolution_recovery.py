import unittest
from maep.core import (
    MAEPError, make_evidence_amendment, recovery_decision,
    untrusted_content_can_authorize, validate_change_plan,
    validate_research_record
)


class EvidenceHistoryTests(unittest.TestCase):
    def test_amendment_links_original_without_reusing_id(self):
        amendment = make_evidence_amendment("E-1", "E-2", "typo correction", {"result": "PASS"})
        self.assertEqual(amendment["supersedes_evidence_id"], "E-1")
        self.assertEqual(amendment["amendment_id"], "E-2")

    def test_amendment_cannot_reuse_original_id(self):
        with self.assertRaises(MAEPError):
            make_evidence_amendment("E-1", "E-1", "correction", {"result": "PASS"})


class ChangeAndRecoveryTests(unittest.TestCase):
    def test_side_effect_requires_plan(self):
        with self.assertRaises(MAEPError):
            validate_change_plan({}, side_effecting=True)

    def test_destructive_change_requires_recovery_or_authorized_irreversibility(self):
        plan = {"scope": "delete test artifact", "risk_assessment": "low",
                "acceptance_criteria": "target removed", "stop_conditions": "target mismatch"}
        with self.assertRaises(MAEPError):
            validate_change_plan(plan, side_effecting=True, destructive=True)

    def test_read_only_action_needs_no_change_plan(self):
        self.assertTrue(validate_change_plan(None, side_effecting=False))

    def test_unknown_non_idempotent_outcome_blocks_retry(self):
        self.assertEqual(recovery_decision(False, False, False), "BLOCKED_RECONCILIATION_REQUIRED")

    def test_idempotent_retry_requires_reconciled_state(self):
        self.assertEqual(recovery_decision(False, True, True), "RETRY_ALLOWED")


class TrustBoundaryAndResearchTests(unittest.TestCase):
    def test_external_instruction_never_grants_authority(self):
        self.assertFalse(untrusted_content_can_authorize(False, True))
        self.assertFalse(untrusted_content_can_authorize(True, True))

    def test_research_claim_must_reference_known_source(self):
        self.assertTrue(validate_research_record({
            "sources": [{"source_id": "S1", "ref": "https://example.invalid"}],
            "claims": [{"claim_id": "C1", "source_refs": ["S1"]}],
            "limitations": ["example fixture only"]
        }))

    def test_research_claim_with_unknown_source_rejected(self):
        with self.assertRaises(MAEPError):
            validate_research_record({
                "sources": [{"source_id": "S1", "ref": "source"}],
                "claims": [{"claim_id": "C1", "source_refs": ["S2"]}],
                "limitations": []
            })


if __name__ == "__main__":
    unittest.main()
