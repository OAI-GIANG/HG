"""Memory ledger adapter tests; all records are isolated test fixtures."""
from __future__ import annotations

import json
import unittest

from maep.core import POLICY_VERSION
from maep.memory_evidence_providers import (CanonicalMemoryTaskSelectors, MemoryLedgerProvenanceVerifier, MemoryMAEPRecordResolver)
from maep.native_authority import AuthorityError, TrustRootRecord
from memory.tests.test_store import MemoryStoreTests


class SelectorsFixture:
    """Fixture selector stands in for canonical task-owned reference selection."""
    def resolve_applicability_ref(self, request, candidate):
        return "EV-APP" if request.get("task_ref") == "T-MK-1" else None

    def resolve_gate_ref(self, request, candidate, policy):
        return "EV-GATE" if request.get("task_ref") == "T-MK-1" else None

    def resolve_evidence_task(self, evidence_ref):
        return "T-MK-1" if evidence_ref.startswith("EV-") else None


class ApprovedSourceFixture:
    def verify_approved_memory_record(self, record, *, record_type, root, policy):
        return (
            root.verify_integrity() and policy.get("root_generation") == root.generation
            and record.get("_memory_binding", {}).get("memory_integrity") == "PASS"
            and record.get("_evidence_record", {}).get("source_ref") == "test://approved-source"
            and record_type in {"MAEP022_APPLICABILITY", "MAEP022_GATE_DECISION", "MAEP022_GATE_EVIDENCE"}
        )


class MemoryEvidenceProviderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = MemoryStoreTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.selectors = SelectorsFixture()
        self.resolver = MemoryMAEPRecordResolver(memory_store=self.store, selectors=self.selectors)

    def tearDown(self):
        self.fixture.tearDown()

    def _record(self, evidence_id, payload):
        evidence = self.fixture.evidence(evidence_id)
        evidence["evidence_type"] = "OTHER"
        evidence["source_ref"] = "test://approved-source"
        evidence["result"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.store.record_evidence("T-MK-1", evidence)

    def test_resolver_reads_applicability_and_gate_from_existing_memory_ledger(self):
        candidate_ref = "candidate-1"
        applicability = {
            "candidate_ref": candidate_ref, "action": "WRITE", "resource": "memory:test",
            "classification": "NOT_REQUIRED", "facts_used": ["canonical-task", "candidate"],
            "evidence_refs": ["EV-SUPPORT"], "rule_version": "MAEP-022-v1",
            "applicability_id": "APP-1", "policy_version": POLICY_VERSION,
        }
        gate = {
            "candidate_ref": candidate_ref, "policy_version": POLICY_VERSION,
            "gate_status": "PASS", "decision_id": "GATE-1",
            "inventory_evidence_refs": ["EV-SUPPORT"],
            "comparison_evidence_refs": ["EV-SUPPORT"],
            "impact_analysis_refs": ["EV-SUPPORT"],
            "regression_test_refs": ["EV-SUPPORT"],
            "decision": "EXISTING_REUSE", "scope": "test scope", "capability": "test capability",
            "inventory_status": "COMPLETE", "overlap_detected": True,
            "selected_implementation": "existing", "rationale": "fixture only",
            "superiority_basis": {key: "fixture evidence" for key in (
                "correctness", "security", "reliability", "functional_coverage", "compatibility",
                "performance_resource_cost", "maintainability_operational_burden")},
        }
        self._record("EV-APP", applicability)
        self._record("EV-GATE", gate)
        self._record("EV-SUPPORT", {"candidate_ref": candidate_ref, "policy_version": POLICY_VERSION,
                                     "note": "supporting fixture evidence"})
        request = {"task_ref": "T-MK-1", "action": "WRITE", "resource": "memory:test"}
        candidate = {"candidate_ref": candidate_ref}
        policy = {"version": POLICY_VERSION, "status": "ACTIVE", "root_generation": 1}
        got_app = self.resolver.resolve_applicability(request, candidate)
        got_gate = self.resolver.resolve_gate(request, candidate, policy)
        got_support = self.resolver.resolve_evidence("EV-SUPPORT")
        self.assertEqual(got_app["applicability_id"], "APP-1")
        self.assertEqual(got_gate["decision_id"], "GATE-1")
        self.assertEqual(got_support["evidence_id"], "EV-SUPPORT")
        self.assertEqual(got_support["_memory_binding"]["memory_integrity"], "PASS")

    def test_missing_or_stale_records_fail_closed(self):
        self.assertIsNone(self.resolver._load("T-MK-1", "EV-NOT-FOUND", candidate_ref="candidate-1"))
        self._record("EV-OLD", {"candidate_ref": "candidate-1", "policy_version": "old-policy"})
        with self.assertRaisesRegex(AuthorityError, "another policy version"):
            self.resolver._load("T-MK-1", "EV-OLD", candidate_ref="candidate-1", policy_version="old-policy")

    def test_provenance_verifier_requires_explicit_approved_source_verifier(self):
        with self.assertRaisesRegex(AuthorityError, "approved trust source unavailable"):
            MemoryLedgerProvenanceVerifier(object())
        root = TrustRootRecord.create(
            root_id="test-root", generation=1, created_at="2026-10-23T00:00:00Z",
            bootstrap_authorization_ref="fixture:approval", verification_method="fixture",
            verification_material_ref="fixture://material", policy_change_rule_ref="fixture://policy",
            evidence_ref="fixture://ledger",
        )
        verifier = MemoryLedgerProvenanceVerifier(ApprovedSourceFixture())
        self._record("EV-APP", {"candidate_ref": "candidate-1", "action": "WRITE",
                                "resource": "memory:test", "classification": "NOT_REQUIRED",
                                "facts_used": ["task"], "evidence_refs": ["EV-SUPPORT"],
                                "rule_version": "MAEP-022-v1", "policy_version": POLICY_VERSION})
        record = self.resolver.resolve_applicability(
            {"task_ref": "T-MK-1", "action": "WRITE", "resource": "memory:test"},
            {"candidate_ref": "candidate-1"})
        policy = {"status": "ACTIVE", "version": POLICY_VERSION, "root_generation": 1}
        self.assertTrue(verifier.validate_record_provenance(record, record_type="MAEP022_APPLICABILITY",
                                                            root=root, policy=policy))
        self.assertFalse(verifier.validate_record_provenance(record, record_type="UNAPPROVED_TYPE",
                                                             root=root, policy=policy))


class CanonicalTaskStoreFixture:
    def __init__(self):
        self.tasks = {
            "T-CANON": {
                "task": {"task_id": "T-CANON", "policy_version": POLICY_VERSION,
                         "inputs": [
                             {"ref_id": "EV-APP", "kind": "EVIDENCE", "description": "maep022:applicability"},
                             {"ref_id": "EV-GATE", "kind": "EVIDENCE", "description": "maep022:gate"},
                             {"ref_id": "EV-SUPPORT", "kind": "EVIDENCE", "description": "supporting evidence"},
                         ]},
                "candidate_ref": "candidate-1", "policy_status": "CURRENT",
            }
        }
        self.evidence = {("T-CANON", "EV-APP"), ("T-CANON", "EV-GATE"), ("T-CANON", "EV-SUPPORT")}

    def list_tasks(self, *, index_scope_task_id, limit, offset):
        if index_scope_task_id not in self.tasks:
            raise AuthorityError("index authorization task not found")
        ordered = sorted(self.tasks)
        selected = ordered[offset:offset + limit]
        snapshots = [self.tasks[task_id] for task_id in selected]
        return {
            "tasks": snapshots, "limit": limit, "offset": offset,
            "returned": len(snapshots), "has_more": len(snapshots) == limit,
            "policy_version": POLICY_VERSION, "integrity_status": "PASS",
        }

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def get_evidence(self, task_id, evidence_ref):
        return {"evidence_id": evidence_ref} if (task_id, evidence_ref) in self.evidence else None


class CanonicalTaskIdSourceFixture:
    def list_canonical_task_ids(self):
        return ["T-CANON"]


class CanonicalMemoryTaskSelectorTests(unittest.TestCase):
    def setUp(self):
        self.store = CanonicalTaskStoreFixture()
        self.selectors = CanonicalMemoryTaskSelectors(memory_store=self.store)

    def test_applicability_and_gate_refs_come_from_task_record_not_request(self):
        request = {"task_ref": "T-CANON", "applicability_ref": "EV-FAKE", "gate_ref": "EV-FAKE"}
        candidate = {"candidate_ref": "candidate-1"}
        policy = {"version": POLICY_VERSION}
        self.assertEqual(self.selectors.resolve_applicability_ref(request, candidate), "EV-APP")
        self.assertEqual(self.selectors.resolve_gate_ref(request, candidate, policy), "EV-GATE")

    def test_candidate_or_policy_drift_blocks(self):
        with self.assertRaisesRegex(AuthorityError, "candidate binding mismatch"):
            self.selectors.resolve_applicability_ref({"task_ref": "T-CANON"}, {"candidate_ref": "other"})
        with self.assertRaisesRegex(AuthorityError, "candidate/policy binding mismatch"):
            self.selectors.resolve_gate_ref({"task_ref": "T-CANON"}, {"candidate_ref": "candidate-1"}, {"version": "old"})

    def test_arbitrary_evidence_lookup_uses_authorized_memory_index(self):
        with self.assertRaisesRegex(AuthorityError, "index unavailable"):
            self.selectors.resolve_evidence_task("EV-SUPPORT")
        selectors = CanonicalMemoryTaskSelectors(
            memory_store=self.store, index_scope_task_id="T-CANON")
        self.assertEqual(selectors.resolve_evidence_task("EV-SUPPORT"), "T-CANON")
        self.assertIsNone(selectors.resolve_evidence_task("EV-UNKNOWN"))

    def test_invalid_or_duplicate_index_source_fails_closed(self):
        class DuplicateTaskIds:
            def list_canonical_task_ids(inner_self):
                return ["T-CANON", "T-CANON"]
        selectors = CanonicalMemoryTaskSelectors(
            memory_store=self.store, canonical_task_id_source=DuplicateTaskIds())
        with self.assertRaisesRegex(AuthorityError, "duplicate task identity"):
            selectors.resolve_evidence_task("EV-SUPPORT")

        class MalformedIndex:
            def get_task(inner_self, task_id):
                return {}
            def list_tasks(inner_self, *, index_scope_task_id, limit, offset):
                return {"tasks": [], "offset": offset, "limit": limit,
                        "returned": 0, "has_more": False,
                        "policy_version": POLICY_VERSION, "integrity_status": "FAIL"}
        selectors = CanonicalMemoryTaskSelectors(
            memory_store=MalformedIndex(), index_scope_task_id="T-CANON")
        with self.assertRaisesRegex(AuthorityError, "page integrity"):
            selectors.resolve_evidence_task("EV-SUPPORT")

    def test_ambiguous_role_and_duplicate_task_match_fail_closed(self):
        self.store.tasks["T-CANON"]["task"]["inputs"].append(
            {"ref_id": "EV-APP-2", "kind": "EVIDENCE", "description": "maep022:applicability"})
        with self.assertRaisesRegex(AuthorityError, "ambiguous references"):
            self.selectors.resolve_applicability_ref(
                {"task_ref": "T-CANON"}, {"candidate_ref": "candidate-1"})

        second = {
            "task": {"task_id": "T-CANON-2", "policy_version": POLICY_VERSION,
                     "inputs": [{"ref_id": "EV-SHARED", "kind": "EVIDENCE", "description": "support"}]},
            "candidate_ref": "candidate-2", "policy_status": "CURRENT",
        }
        self.store.tasks["T-CANON-2"] = second
        self.store.evidence.add(("T-CANON-2", "EV-SHARED"))
        self.store.tasks["T-CANON"]["task"]["inputs"].append(
            {"ref_id": "EV-SHARED", "kind": "EVIDENCE", "description": "support"})
        self.store.evidence.add(("T-CANON", "EV-SHARED"))
        class DuplicateTaskIds:
            def list_canonical_task_ids(inner_self):
                return ["T-CANON", "T-CANON-2"]
        selectors = CanonicalMemoryTaskSelectors(memory_store=self.store,
                                                 canonical_task_id_source=DuplicateTaskIds())
        with self.assertRaisesRegex(AuthorityError, "ambiguous across canonical tasks"):
            selectors.resolve_evidence_task("EV-SHARED")


if __name__ == "__main__":
    unittest.main()
