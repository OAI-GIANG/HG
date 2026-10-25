import unittest

from creativity_research import (
    CONTRACT_VERSION, ResearchContractError, ResearchService, validate_research_request,
)
from maep.core import POLICY_VERSION


class FixtureSourceProvider:
    def __init__(self, sources=None):
        self.sources = sources or [{
            "source_id": "src:1", "ref": "fixture://source/1", "source_type": "FIXTURE",
            "collection_method": "local-test-fixture", "limitations": ["not an external source"],
        }]
        self.calls = []

    def collect(self, *, question, scope, limit):
        self.calls.append({"question": question, "scope": scope, "limit": limit})
        return list(self.sources)[:limit]


def request(**changes):
    value = {
        "contract_version": CONTRACT_VERSION, "task_ref": "task:research-1",
        "research_id": "research:1", "question": "Compare available approaches",
        "scope": "HG branch 3 only", "source_limit": 5,
        "required_evidence": ["evidence:source-index"], "policy_version": POLICY_VERSION,
    }
    value.update(changes)
    return value


def claim(**changes):
    value = {
        "claim_id": "claim:1", "claim_type": "HYPOTHESIS",
        "statement": "Approach A may be suitable for the stated scope",
        "source_refs": ["src:1"], "evidence_refs": [],
        "limitations": ["fixture source only; not verified externally"],
    }
    value.update(changes)
    return value


class ResearchContractTests(unittest.TestCase):
    def test_valid_request_is_bounded_and_policy_versioned(self):
        parsed = validate_research_request(request(source_limit=3))
        self.assertEqual(parsed.source_limit, 3)
        self.assertEqual(parsed.policy_version, POLICY_VERSION)

    def test_missing_fields_rejected(self):
        value = request()
        value.pop("task_ref")
        with self.assertRaisesRegex(ResearchContractError, "missing required"):
            validate_research_request(value)

    def test_unknown_contract_or_stale_policy_rejected(self):
        for patch in ({"contract_version": "hg.creativity-research.v99"},
                      {"policy_version": "MAEP-0.0"}):
            with self.subTest(patch=patch), self.assertRaises(ResearchContractError):
                validate_research_request(request(**patch))

    def test_source_limit_bounds_and_rejects_booleans(self):
        for limit in (0, 51, True, 1.5, "3"):
            with self.subTest(limit=limit), self.assertRaises(ResearchContractError):
                validate_research_request(request(source_limit=limit))

    def test_evidence_refs_must_be_nonempty_unique_strings(self):
        for refs in ([], ["e:1", "e:1"], [""]):
            with self.subTest(refs=refs), self.assertRaises(ResearchContractError):
                validate_research_request(request(required_evidence=refs))

    def test_service_returns_source_linked_unverified_record(self):
        provider = FixtureSourceProvider()
        record = ResearchService(source_provider=provider).prepare(
            request=request(), claims=[claim()], disagreements=[], limitations=["fixture only"]
        )
        self.assertEqual(record["status"], "PREPARED_UNVERIFIED")
        self.assertEqual(record["authority_effect"], "NONE")
        self.assertEqual(record["claims"][0]["source_refs"], ["src:1"])
        self.assertEqual(provider.calls, [{"question": request()["question"],
                                           "scope": request()["scope"], "limit": 5}])

    def test_missing_source_provider_is_blocked(self):
        for provider in (None, object()):
            with self.subTest(provider=provider), self.assertRaises(ResearchContractError):
                ResearchService(source_provider=provider)

    def test_claim_cannot_reference_unknown_source(self):
        with self.assertRaisesRegex(ResearchContractError, "unknown or duplicate sources"):
            ResearchService(source_provider=FixtureSourceProvider()).prepare(
                request=request(), claims=[claim(source_refs=["src:missing"])])

    def test_fact_requires_evidence_reference(self):
        with self.assertRaisesRegex(ResearchContractError, "FACT research claims require evidence_refs"):
            ResearchService(source_provider=FixtureSourceProvider()).prepare(
                request=request(), claims=[claim(claim_type="FACT", limitations=[], evidence_refs=[])])

    def test_hypothesis_without_limitations_rejected(self):
        with self.assertRaisesRegex(ResearchContractError, "must disclose limitations"):
            ResearchService(source_provider=FixtureSourceProvider()).prepare(
                request=request(), claims=[claim(limitations=[])])

    def test_duplicate_source_identifiers_rejected(self):
        duplicate = [{
            "source_id": "src:1", "ref": "fixture://1", "source_type": "FIXTURE",
            "collection_method": "fixture", "limitations": [],
        }, {
            "source_id": "src:1", "ref": "fixture://2", "source_type": "FIXTURE",
            "collection_method": "fixture", "limitations": [],
        }]
        with self.assertRaisesRegex(ResearchContractError, "unique"):
            ResearchService(source_provider=FixtureSourceProvider(duplicate)).prepare(
                request=request(), claims=[claim()])

    def test_service_does_not_expose_dispatch_or_memory_mutation(self):
        service = ResearchService(source_provider=FixtureSourceProvider())
        self.assertFalse(hasattr(service, "dispatch"))
        self.assertFalse(hasattr(service, "put_knowledge"))
        self.assertFalse(hasattr(service, "authorize"))


if __name__ == "__main__":
    unittest.main()
