import unittest
from maep.core import (
    MAEPError, assess_candidate_change, architecture_proposal_allowed,
    enforce_execution_mode, retry_decision, validate_blocker,
    validate_capability_evolution_decision, validate_policy_change,
    validate_report_status, validate_review_label
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

    def test_internal_critique_is_allowed(self):
        self.assertTrue(validate_review_label("INTERNAL_CRITIQUE"))

    def test_independent_review_is_prohibited_even_with_evidence(self):
        with self.assertRaisesRegex(MAEPError, "prohibited by MAEP-030"):
            validate_review_label("INDEPENDENT", independent_evidence=True)

    def test_independent_review_is_prohibited_without_evidence(self):
        with self.assertRaisesRegex(MAEPError, "prohibited by MAEP-030"):
            validate_review_label("INDEPENDENT", independent_evidence=False)

    def test_peer_review_label_is_not_an_allowed_workflow(self):
        with self.assertRaisesRegex(MAEPError, "unknown review type"):
            validate_review_label("PEER_REVIEW")


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

    @staticmethod
    def _capability_evidence(record):
        refs = set(record["inventory_evidence_refs"] + record["comparison_evidence_refs"] +
                   record["impact_analysis_refs"] + record["regression_test_refs"])
        for field in ("retirement_authorization_ref", "recovery_plan_ref"):
            if record.get(field):
                refs.add(record[field])
        refs.update(record.get("obsolescence_evidence_refs", []))
        return {ref: {
            "evidence_id": ref, "evidence_type": "TEST_RESULT" if ref.startswith("T-") else "ARCHITECTURE_EVIDENCE",
            "source_ref": f"test://{ref}", "candidate_ref": record["candidate_ref"],
            "collected_at": "2026-10-22T10:00:00Z", "collector": "unit-test",
            "method": "unittest", "result": "PASS", "limitations": []
        } for ref in refs}

    @staticmethod
    def _capability_gate(**overrides):
        record = {
            "decision_id": "DG-TEST-1", "candidate_ref": "candidate-abc",
            "policy_version": "MAEP-1.2.0", "scope": "maep/core.py",
            "capability": "task authorization", "inventory_status": "COMPLETE",
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
        record.update(overrides)
        return record

    def _validate_capability_gate(self, record, **kwargs):
        return validate_capability_evolution_decision(
            record, evidence_by_id=self._capability_evidence(record), **kwargs)

    def test_capability_gate_accepts_candidate_bound_evidenced_reuse(self):
        record = self._capability_gate()
        self.assertTrue(self._validate_capability_gate(
            record, candidate_ref="candidate-abc", policy_version="MAEP-1.2.0"))

    def test_unresolved_capability_evidence_blocks_gate(self):
        record = self._capability_gate()
        with self.assertRaisesRegex(MAEPError, "evidence reference unresolved"):
            validate_capability_evolution_decision(record, evidence_by_id={})

    def test_wrong_candidate_evidence_blocks_gate(self):
        record = self._capability_gate()
        evidence = self._capability_evidence(record)
        evidence["E-INVENTORY"]["candidate_ref"] = "other-candidate"
        with self.assertRaisesRegex(MAEPError, "evidence candidate mismatch"):
            validate_capability_evolution_decision(record, evidence_by_id=evidence)

    def test_unknown_capability_decision_fails_closed(self):
        with self.assertRaisesRegex(MAEPError, "UNKNOWN.*blocked"):
            self._validate_capability_gate(self._capability_gate(decision="UNKNOWN"))

    def test_incomplete_capability_inventory_blocks_gate(self):
        with self.assertRaisesRegex(MAEPError, "inventory incomplete"):
            self._validate_capability_gate(self._capability_gate(inventory_status="PARTIAL"))

    def test_capability_gate_rejects_candidate_mismatch(self):
        with self.assertRaisesRegex(MAEPError, "candidate mismatch"):
            self._validate_capability_gate(self._capability_gate(), candidate_ref="different")

    def test_overlapping_capability_requires_comparison_evidence(self):
        with self.assertRaisesRegex(MAEPError, "comparison evidence"):
            self._validate_capability_gate(self._capability_gate(comparison_evidence_refs=[]))

    def test_overlapping_capability_requires_all_superiority_dimensions(self):
        record = self._capability_gate(superiority_basis={"correctness": "E-COMPARE"})
        with self.assertRaisesRegex(MAEPError, "all MAEP-022 quality dimensions"):
            self._validate_capability_gate(record)

    def test_capability_gate_not_pass_cannot_authorize(self):
        with self.assertRaisesRegex(MAEPError, "must be PASS"):
            self._validate_capability_gate(self._capability_gate(gate_status="NOT_RUN"))

    def test_capability_gate_rejects_policy_version_mismatch(self):
        with self.assertRaisesRegex(MAEPError, "policy version mismatch"):
            self._validate_capability_gate(self._capability_gate(), policy_version="MAEP-1.1.0")

    def test_malformed_capability_decision_fails_closed(self):
        with self.assertRaisesRegex(MAEPError, "unknown capability evolution decision"):
            self._validate_capability_gate(self._capability_gate(decision={"unexpected": "object"}))

    def test_consolidation_requires_all_superiority_dimensions(self):
        record = self._capability_gate(
            decision="CONSOLIDATE_KEEP_SUPERIOR", selected_implementation="best",
            retire_candidates=["obsolete"], retirement_authorized=True,
            retirement_authorization_ref="AUTH-1", recovery_plan_ref="RECOVERY-1",
            superiority_basis={"correctness": "T1 evidence"})
        with self.assertRaisesRegex(MAEPError, "all MAEP-022 quality dimensions"):
            self._validate_capability_gate(record)

    def test_retirement_requires_explicit_authorization_and_recovery(self):
        record = self._capability_gate(
            decision="DEPRECATE_OBSOLETE", retire_candidates=["old-capability"],
            obsolescence_basis="EVIDENCE-OBSOLESCENCE", obsolescence_evidence_refs=["E-OBSOLESCENCE"],
            retirement_authorized=False, retirement_authorization_ref="", recovery_plan_ref="RECOVERY-1")
        with self.assertRaisesRegex(MAEPError, "explicit scoped authorization"):
            self._validate_capability_gate(record)

    def test_consolidation_passes_when_superiority_and_retirement_are_evidenced(self):
        record = self._capability_gate(
            decision="CONSOLIDATE_KEEP_SUPERIOR", selected_implementation="best-tested",
            retire_candidates=["old-implementation"], retirement_authorized=True,
            retirement_authorization_ref="AUTH-1", recovery_plan_ref="RECOVERY-1",
            superiority_basis={
                "correctness": "T-CORRECT", "security": "T-SECURE",
                "reliability": "T-RELIABLE", "functional_coverage": "T-COVERAGE",
                "compatibility": "T-COMPAT", "performance_resource_cost": "T-PERF",
                "maintainability_operational_burden": "T-MAINT"
            })
        self.assertTrue(self._validate_capability_gate(record))

    def test_false_gap_claim_conflicting_with_overlap_is_rejected(self):
        record = self._capability_gate(decision="GENUINE_GAP", proposed_owner="owner", capability_boundary="boundary")
        with self.assertRaisesRegex(MAEPError, "conflicts with GENUINE_GAP"):
            self._validate_capability_gate(record)

    def test_genuine_gap_requires_comparison_evidence(self):
        record = self._capability_gate(
            decision="GENUINE_GAP", overlap_detected=False, comparison_evidence_refs=[],
            proposed_owner="creativity_research", capability_boundary="source-linked research records")
        with self.assertRaisesRegex(MAEPError, "GENUINE_GAP requires comparison evidence"):
            self._validate_capability_gate(record)

    def test_genuine_gap_passes_with_resolved_comparison_evidence(self):
        record = self._capability_gate(
            decision="GENUINE_GAP", overlap_detected=False, comparison_evidence_refs=["E-COMPARE"],
            proposed_owner="creativity_research", capability_boundary="source-linked research records")
        self.assertTrue(self._validate_capability_gate(record))

    def test_nonpassing_evidence_with_explanatory_suffix_is_rejected(self):
        for status in ("FAIL", "BLOCKED", "NOT_RUN", "UNVERIFIED", "PASSED"):
            with self.subTest(status=status):
                record = self._capability_gate()
                evidence = self._capability_evidence(record)
                evidence["E-COMPARE"]["result"] = status + " — status followed by explanatory text"
                with self.assertRaisesRegex(MAEPError, "evidence is not passing"):
                    validate_capability_evolution_decision(record, evidence_by_id=evidence)

    def test_deprecation_requires_resolved_obsolescence_evidence(self):
        record = self._capability_gate(
            decision="DEPRECATE_OBSOLETE", obsolescence_basis="the old implementation is obsolete",
            retire_candidates=["old-implementation"], retirement_authorized=True,
            retirement_authorization_ref="AUTH-1", recovery_plan_ref="RECOVERY-1")
        with self.assertRaisesRegex(MAEPError, "obsolescence_evidence_refs"):
            self._validate_capability_gate(record)

    def test_deprecation_resolves_obsolescence_evidence(self):
        record = self._capability_gate(
            decision="DEPRECATE_OBSOLETE", obsolescence_basis="evidence-backed obsolete implementation",
            obsolescence_evidence_refs=["E-OBSOLETE"], retire_candidates=["old-implementation"],
            retirement_authorized=True, retirement_authorization_ref="AUTH-1",
            recovery_plan_ref="RECOVERY-1")
        self.assertTrue(self._validate_capability_gate(record))


if __name__ == "__main__":
    unittest.main()
