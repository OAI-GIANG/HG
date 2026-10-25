import unittest

from memory.experience_resolver import ExperienceResolutionBlocked, ExperienceResolver


class MemoryApi:
    def __init__(self, *, record=None, evidence=None, evidence_error=False):
        self.record = record
        self.evidence = evidence or {}
        self.evidence_error = evidence_error

    def get_knowledge(self, task_id, claim_id, *, include_stale=False):
        return self.record

    def get_evidence(self, task_id, evidence_id):
        if self.evidence_error:
            raise RuntimeError("revoked or unavailable")
        return self.evidence.get(evidence_id)


def make_record(**changes):
    record = {
        "record_id": "KNOW-2", "version": 2, "task_id": "T-1",
        "candidate_ref": "candidate-1", "policy_version": "MAEP-1.2.0",
        "record_status": "CURRENT", "verification_status": "VERIFIED",
        "claim": {
            "claim_id": "CL-1", "claim_type": "FACT",
            "statement": "Verified scoped fact", "evidence_refs": ["EV-1"], "limitations": [],
        },
        "verification": {"evidence_refs": ["EV-1"], "verification_id": "VER-1"},
        "provenance": {"source_ref": "observed://source"},
    }
    record.update(changes)
    return record


def make_evidence():
    return {
        "evidence_id": "EV-1", "task_id": "T-1", "candidate_ref": "candidate-1",
        "policy_version": "MAEP-1.2.0",
        "evidence": {"evidence_id": "EV-1", "candidate_ref": "candidate-1", "content": "source"},
    }


class ExperienceResolverTests(unittest.TestCase):
    def resolver(self, *, record=None, evidence=None, independent=True, applicable=True, evidence_error=False):
        api = MemoryApi(record=record if record is not None else make_record(),
                        evidence=evidence if evidence is not None else {"EV-1": make_evidence()},
                        evidence_error=evidence_error)
        return ExperienceResolver(
            memory_api=api,
            evidence_verifier=lambda **kwargs: independent,
            applicability_verifier=lambda **kwargs: applicable,
        )

    def resolve(self, resolver):
        return resolver.resolve(
            task_id="T-1", claim_id="CL-1", candidate_ref="candidate-1",
            policy_version="MAEP-1.2.0",
            applicability_context={"target": "same candidate", "conflict_detected": False},
        )

    def test_conflicting_or_unknown_conflict_state_fails_closed(self):
        resolver = self.resolver()
        for context in ({"target": "same candidate", "conflict_detected": True},
                        {"target": "same candidate"}):
            with self.assertRaisesRegex(ExperienceResolutionBlocked, "conflict state"):
                resolver.resolve(
                    task_id="T-1", claim_id="CL-1", candidate_ref="candidate-1",
                    policy_version="MAEP-1.2.0", applicability_context=context,
                )

    def test_verified_retrieval_requires_independent_evidence_and_applicability(self):
        resolved = self.resolve(self.resolver())
        self.assertEqual(resolved.statement, "Verified scoped fact")
        self.assertEqual(resolved.freshness, "CURRENT")
        self.assertEqual(resolved.authority_effect, "NONE")

    def test_stale_claim_rejected(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "stale"):
            self.resolve(self.resolver(record=make_record(record_status="STALE")))

    def test_candidate_or_policy_drift_rejected(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "binding mismatch"):
            self.resolve(self.resolver(record=make_record(candidate_ref="candidate-old")))
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "binding mismatch"):
            self.resolve(self.resolver(record=make_record(policy_version="MAEP-1.0.0")))

    def test_unverified_claim_rejected(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "not verified"):
            self.resolve(self.resolver(record=make_record(verification_status="UNVERIFIED")))

    def test_conflicting_evidence_reference_sets_rejected(self):
        record = make_record(verification={"evidence_refs": ["EV-OTHER"]})
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "references disagree"):
            self.resolve(self.resolver(record=record))

    def test_independent_verifier_must_accept_evidence(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "not independently verified"):
            self.resolve(self.resolver(independent=False))

    def test_applicability_must_be_established(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "applicability is not established"):
            self.resolve(self.resolver(applicable=False))

    def test_missing_or_revoked_evidence_fails_closed(self):
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "missing or revoked"):
            self.resolve(self.resolver(evidence={}))
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "authorized evidence read failed"):
            self.resolve(self.resolver(evidence_error=True))

    def test_evidence_scope_mismatch_rejected(self):
        evidence = make_evidence()
        evidence["candidate_ref"] = "candidate-other"
        with self.assertRaisesRegex(ExperienceResolutionBlocked, "binding mismatch"):
            self.resolve(self.resolver(evidence={"EV-1": evidence}))


if __name__ == "__main__":
    unittest.main()
