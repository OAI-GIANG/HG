import unittest

from maep.native_authority import AuthorityError, TrustRootRecord
from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider


class RootStore:
    def __init__(self):
        self.root = TrustRootRecord.create(
            root_id="test-root", generation=1, created_at="2026-10-22T10:00:00Z",
            bootstrap_authorization_ref="test-approved", verification_method="test-only",
            verification_material_ref="test-material", policy_change_rule_ref="test-policy-rule",
            evidence_ref="test-ledger",
        )
    def load_active(self):
        return self.root


class PolicyProvider:
    def load_active(self, root):
        return {"status": "ACTIVE", "version": "policy:test", "root_generation": root.generation,
                "provenance_verified": True, "policy_digest": "sha256:" + "0" * 64,
                "approval_evidence_refs": ["test-policy-approval"]}


class Resolver:
    def __init__(self):
        self.candidate_ref = "candidate:test-current"
        self.applicability = {
            "applicability_id": "app:test", "candidate_ref": self.candidate_ref,
            "action": "WRITE", "resource": "hg://isolated/resource",
            "classification": "REQUIRED", "rule_version": "maep022-rules:test",
            "facts_used": ["action", "resource"], "evidence_refs": ["APP-EVIDENCE-1"],
        }
        self.app_evidence = {"evidence_id": "APP-EVIDENCE-1", "candidate_ref": self.candidate_ref,
                             "evidence_type": "POLICY_FACT", "source_ref": "isolated://app-fact",
                             "collected_at": "2026-10-22T10:00:00Z", "collector": "test-only",
                             "method": "fixture", "result": "PASS", "limitations": ["test fixture only"]}
        refs = ["INV-1", "CMP-1", "IMPACT-1", "REGRESSION-1"]
        self.gate = {
            "decision_id": "MAEP022-ISOLATED-TEST", "candidate_ref": self.candidate_ref,
            "policy_version": "policy:test", "scope": "isolated provider test",
            "capability": "isolated capability", "inventory_status": "COMPLETE",
            "inventory_evidence_refs": [refs[0]], "overlap_detected": True,
            "comparison_evidence_refs": [refs[1]], "decision": "EXISTING_REUSE",
            "selected_implementation": "existing isolated implementation",
            "rationale": "Fixture tests canonical verification path only",
            "impact_analysis_refs": [refs[2]], "regression_test_refs": [refs[3]],
            "gate_status": "PASS",
            "superiority_basis": {key: "fixture-only rationale" for key in (
                "correctness", "security", "reliability", "functional_coverage",
                "compatibility", "performance_resource_cost", "maintainability_operational_burden")},
        }
        self.gate_evidence = {
            ref: {"evidence_id": ref, "evidence_type": "TEST_RESULT",
                  "source_ref": "isolated://" + ref, "candidate_ref": self.candidate_ref,
                  "collected_at": "2026-10-22T10:00:00Z", "collector": "test-only",
                  "method": "unittest", "result": "PASS", "limitations": ["not production evidence"]}
            for ref in refs
        }
        self.records = {self.applicability["applicability_id"]: self.applicability,
                        self.app_evidence["evidence_id"]: self.app_evidence,
                        self.gate["decision_id"]: self.gate, **self.gate_evidence}

    def resolve_applicability(self, request, candidate):
        return self.applicability

    def resolve_gate(self, request, candidate, policy):
        return self.gate

    def resolve_evidence(self, evidence_ref):
        if evidence_ref == self.app_evidence["evidence_id"]:
            return self.app_evidence
        return self.gate_evidence.get(evidence_ref)


class TestOnlyProvenanceVerifier:
    __test__ = False  # pytest must not collect this helper as a test class.

    """Controlled fixture only; production provenance sources are not supplied by this test."""
    def __init__(self, resolver, accept=True):
        self.trusted_object_ids = {id(item) for item in resolver.records.values()}
        self.accept = accept

    def validate_record_provenance(self, record, *, record_type, root, policy):
        return self.accept and id(record) in self.trusted_object_ids and root.verify_integrity()


class TrustedProviderTests(unittest.TestCase):
    def setUp(self):
        self.root = RootStore()
        self.policy = PolicyProvider()
        self.resolver = Resolver()
        self.verifier = TestOnlyProvenanceVerifier(self.resolver)
        self.request = {"action": "WRITE", "resource": "hg://isolated/resource"}
        self.candidate = {"candidate_ref": self.resolver.candidate_ref}

    def test_applicability_is_bound_to_candidate_action_and_resource(self):
        provider = TrustedApplicabilityProvider(root_store=self.root, policy_provider=self.policy,
                                                resolver=self.resolver, verifier=self.verifier)
        result = provider.classify(self.request, self.candidate)
        self.assertTrue(result["verified"])
        self.assertEqual(result["classification"], "REQUIRED")
        self.assertEqual(result["candidate_ref"], self.candidate["candidate_ref"])

    def test_unverified_applicability_record_blocks_even_if_caller_claims_verified(self):
        provider = TrustedApplicabilityProvider(root_store=self.root, policy_provider=self.policy,
                                                resolver=self.resolver,
                                                verifier=TestOnlyProvenanceVerifier(self.resolver, accept=False))
        with self.assertRaisesRegex(AuthorityError, "unverified"):
            provider.classify(self.request, self.candidate)

    def test_gate_resolves_provenance_checked_evidence_and_runs_canonical_validator(self):
        provider = TrustedGateEvidenceProvider(root_store=self.root, policy_provider=self.policy,
                                               resolver=self.resolver, verifier=self.verifier)
        result = provider.evaluate(self.request, self.candidate, self.policy.load_active(self.root.load_active()))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["evidence_verified"])
        self.assertEqual(result["candidate_ref"], self.candidate["candidate_ref"])
        self.assertEqual(len(result["evidence_by_id"]), 4)

    def test_gate_blocks_when_evidence_provenance_cannot_be_verified(self):
        provider = TrustedGateEvidenceProvider(root_store=self.root, policy_provider=self.policy,
                                               resolver=self.resolver,
                                               verifier=TestOnlyProvenanceVerifier(self.resolver, accept=False))
        with self.assertRaisesRegex(AuthorityError, "unverified"):
            provider.evaluate(self.request, self.candidate, self.policy.load_active(self.root.load_active()))

    def test_candidate_mismatch_blocks_trusted_gate(self):
        provider = TrustedGateEvidenceProvider(root_store=self.root, policy_provider=self.policy,
                                               resolver=self.resolver, verifier=self.verifier)
        wrong_candidate = {"candidate_ref": "candidate:stale"}
        with self.assertRaisesRegex(AuthorityError, "candidate/policy mismatch"):
            provider.evaluate(self.request, wrong_candidate, self.policy.load_active(self.root.load_active()))

    def test_deprecation_gate_resolves_all_retirement_and_obsolescence_evidence(self):
        gate = self.resolver.gate
        gate.update({
            "decision": "DEPRECATE_OBSOLETE",
            "obsolescence_basis": "obsolete implementation demonstrated by evidence",
            "obsolescence_evidence_refs": ["OBS-1"],
            "retire_candidates": ["old-implementation"],
            "retirement_authorized": True,
            "retirement_authorization_ref": "AUTH-1",
            "recovery_plan_ref": "RECOVERY-1",
        })
        for ref in ("OBS-1", "AUTH-1", "RECOVERY-1"):
            self.resolver.gate_evidence[ref] = {
                "evidence_id": ref, "evidence_type": "AUTHORIZATION" if ref == "AUTH-1" else "ARCHITECTURE_EVIDENCE",
                "source_ref": "isolated://" + ref, "candidate_ref": self.resolver.candidate_ref,
                "collected_at": "2026-10-22T10:00:00Z", "collector": "test-only",
                "method": "isolated fixture", "result": "PASS", "limitations": ["test fixture only"],
            }
        self.resolver.records.update(self.resolver.gate_evidence)
        verifier = TestOnlyProvenanceVerifier(self.resolver)
        provider = TrustedGateEvidenceProvider(
            root_store=self.root, policy_provider=self.policy,
            resolver=self.resolver, verifier=verifier)
        result = provider.evaluate(
            self.request, self.candidate, self.policy.load_active(self.root.load_active()))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["evidence_by_id"]), 7)
        self.assertIn("OBS-1", result["evidence_by_id"])
        self.assertIn("AUTH-1", result["evidence_by_id"])
        self.assertIn("RECOVERY-1", result["evidence_by_id"])


if __name__ == "__main__":
    unittest.main()
