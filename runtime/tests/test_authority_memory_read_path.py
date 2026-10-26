"""Native Authority must not re-enter itself while reading its own MAEP-022 evidence.

Production wiring (runtime.composition.build_runtime) gives MemoryStore a policy
evaluator backed by NativePolicyEngine. When the engine's applicability/gate
providers resolve their records through that same authorizing MemoryStore API,
every authorize() asks Memory for permission, which calls authorize() again.

These tests build the real graph (engine, MemoryNativeAuthorityAdapter, MemoryStore,
Trusted* providers, MemoryMAEPRecordResolver, CanonicalMemoryTaskSelectors) over an
isolated temporary SQLite file. Only the owner-decision seams (approved-source
verifier, principal/session, policy record, candidate) are fixtures; no production
path, credential or service is touched.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from maep.core import POLICY_VERSION
from maep.memory_evidence_providers import (
    CanonicalMemoryTaskSelectors, MemoryLedgerProvenanceVerifier, MemoryMAEPRecordResolver,
)
from maep.native_authority import AuthorityError, Decision, NativePolicyEngine, TrustRootRecord
from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider
from memory import MemoryStore
from memory.authority_adapter import MemoryNativeAuthorityAdapter
from memory.tests import test_store as store_fixtures

PRINCIPAL = "test-runtime-principal"
CANDIDATE = "candidate-1"
TASK = "T-MK-1"
ACTION, RESOURCE, SCOPE = "WRITE", "repo:OAI-GIANG/HG/file", "repo:OAI-GIANG/HG"


class RootStoreFixture:
    def __init__(self):
        self.root = TrustRootRecord.create(
            root_id="test-root", generation=1, created_at="2026-10-25T00:00:00Z",
            bootstrap_authorization_ref="fixture:approval", verification_method="fixture",
            verification_material_ref="fixture://material", policy_change_rule_ref="fixture://policy",
            evidence_ref="fixture://ledger",
        )

    def load_active(self):
        return self.root


class PolicyFixture:
    def load_active(self, root):
        return {
            "status": "ACTIVE", "version": POLICY_VERSION, "root_generation": root.generation,
            "provenance_verified": True, "policy_digest": "sha256:" + "b" * 64,
            "approval_evidence_refs": ["fixture:policy-approval"], "grant_ttl_seconds": 60,
            "rules": [{"action": ACTION, "resource": RESOURCE, "scope": [SCOPE], "effect": "ALLOW"}],
        }


class PrincipalFixture:
    """Counts evaluations: each authorize() that gets past the root check resolves once."""
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def resolve(self, context):
        with self._lock:
            self.calls += 1
        return {
            "status": "ACTIVE", "verified": True, "identity_evidence_ref": "fixture:session",
            "principal_id": PRINCIPAL, "capabilities": [ACTION, "READ"],
            "resource_scopes": [RESOURCE], "allowed_scopes": [SCOPE],
        }


class CandidateFixture:
    def inspect(self, target):
        return {"verified": True, "repository": "OAI-GIANG/HG", "candidate_ref": CANDIDATE,
                "source_manifest_digest": "sha256:" + "c" * 64}


class EvidenceSinkFixture:
    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def append(self, event):
        with self._lock:
            self.events.append(event)
            return "fixture:evidence:%d" % len(self.events)

    def decisions(self):
        return [e for e in self.events if e["event_type"].startswith("authorization.")]


class ApprovedSourceFixture:
    """Stands in for the owner-approved Memory record rule (D4, owner decision)."""
    def verify_approved_memory_record(self, record, *, record_type, root, policy):
        return record.get("_evidence_record", {}).get("source_ref") == "test://approved-source"


class AuthorityMemoryReadPathTests(unittest.TestCase):
    def setUp(self):
        self.memory = store_fixtures.MemoryStoreTests()
        self.memory.setUp()            # isolated DB, initialized under a test-only evaluator
        self.addCleanup(self.memory.tearDown)
        self.db = self.memory.db
        task = store_fixtures.MemoryStoreTests.task("T-AUTH-1")
        task["inputs"] = [
            {"ref_id": "EV-APP", "kind": "EVIDENCE", "description": "maep022:applicability"},
            {"ref_id": "EV-SUPPORT", "kind": "EVIDENCE", "description": "supporting evidence"},
        ]
        self.task_id = "T-AUTH-1"
        self.memory.store.create_task(task, candidate_ref=CANDIDATE)
        self._record("EV-SUPPORT", {"candidate_ref": CANDIDATE, "note": "support"})
        self._record("EV-APP", {
            "candidate_ref": CANDIDATE, "action": ACTION, "resource": RESOURCE,
            "classification": "NOT_REQUIRED", "facts_used": ["canonical-task", "candidate"],
            "evidence_refs": ["EV-SUPPORT"], "rule_version": "MAEP-022-v1",
            "applicability_id": "APP-1",
        })
        self.root_store, self.policy = RootStoreFixture(), PolicyFixture()
        self.principal, self.sink = PrincipalFixture(), EvidenceSinkFixture()

    def _record(self, evidence_id, payload):
        evidence = store_fixtures.MemoryStoreTests.evidence(evidence_id, CANDIDATE)
        evidence["evidence_type"] = "OTHER"
        evidence["source_ref"] = "test://approved-source"
        evidence["result"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.memory.store.record_evidence(self.task_id, evidence)

    def _engine(self, record_source):
        resolver = MemoryMAEPRecordResolver(
            memory_store=record_source,
            selectors=CanonicalMemoryTaskSelectors(memory_store=record_source,
                                                   index_scope_task_id=self.task_id))
        verifier = MemoryLedgerProvenanceVerifier(ApprovedSourceFixture())
        return NativePolicyEngine(
            root_store=self.root_store, principal_provider=self.principal,
            candidate_provider=CandidateFixture(), policy_provider=self.policy,
            applicability_provider=TrustedApplicabilityProvider(
                root_store=self.root_store, policy_provider=self.policy,
                resolver=resolver, verifier=verifier),
            gate_provider=TrustedGateEvidenceProvider(
                root_store=self.root_store, policy_provider=self.policy,
                resolver=resolver, verifier=verifier),
            evidence_sink=self.sink,
        )

    def _production_memory(self, engine):
        """MemoryStore exactly as runtime.composition.build_runtime wires it."""
        adapter = MemoryNativeAuthorityAdapter(
            engine=engine, authenticated_context_provider=lambda: "fixture-session",
            candidate_target_provider=lambda request: "fixture-target")
        return MemoryStore(
            self.db, principal_provider=lambda: PRINCIPAL,
            policy_evaluator=adapter.policy_evaluator,
            live_state_provider=self.memory.live_state,
            applicability_provider=adapter.applicability_provider,
            candidate_ref_provider=lambda task_id: CANDIDATE,
            effect_recheck_provider=adapter.effect_recheck_provider,
        )

    def _request(self):
        return {"action": ACTION, "resource": RESOURCE, "scope": [SCOPE],
                "task_ref": self.task_id, "candidate_ref": CANDIDATE}

    def test_authority_reads_its_evidence_without_reentering_itself(self):
        from memory import AuthorityEvidenceReader
        engine = self._engine(AuthorityEvidenceReader(self.db))
        result = engine.authorize(self._request(), authenticated_context="fixture-session",
                                  candidate_target="fixture-target")
        self.assertEqual(result.decision, Decision.ALLOW, result.reason_codes)
        self.assertEqual(result.applicability_ref, "APP-1")
        self.assertEqual(self.principal.calls, 1, "authorize() must evaluate exactly once")
        self.assertEqual([e["event_type"] for e in self.sink.decisions()], ["authorization.decision"])

    def test_resolver_rejects_the_authorizing_memory_api(self):
        # The authorizing data-plane API calls back into authority; using it as the
        # authority's own record source is the recursion defect, so composition blocks.
        store = MemoryStore(self.db, principal_provider=lambda: PRINCIPAL,
                            policy_evaluator=store_fixtures.policy_decision,
                            applicability_provider=store_fixtures.applicability_provider_for_test)
        with self.assertRaisesRegex(AuthorityError, "authority evidence read path"):
            MemoryMAEPRecordResolver(memory_store=store, selectors=object())
        with self.assertRaisesRegex(AuthorityError, "authority evidence read path"):
            CanonicalMemoryTaskSelectors(memory_store=store)

    def test_miswired_graph_blocks_once_instead_of_recursing(self):
        # Defense in depth: even if a provider reaches authorize() again (here through
        # the authorizing MemoryStore, bypassing the constructor check), the nested
        # evaluation is BLOCKED at depth 2 and the outer decision fails closed.
        class LateBound:
            target = None
            def has_task(self, task_id):
                return True     # report the task present so the read reaches the authorizing API
            def __getattr__(self, name):
                return lambda *args, **kwargs: getattr(LateBound.target, name)(*args, **kwargs)
        engine = self._engine(LateBound())
        LateBound.target = self._production_memory(engine)
        result = engine.authorize(self._request(), authenticated_context="fixture-session",
                                  candidate_target="fixture-target")
        decisions = self.sink.decisions()
        self.assertEqual(result.decision, Decision.BLOCKED)
        # The nested call is refused before it evaluates anything: one full evaluation,
        # one nested BLOCKED event, one outer BLOCKED event.
        self.assertEqual((self.principal.calls, len(decisions)), (1, 2),
                         "evaluations=%d decision_events=%d" % (self.principal.calls, len(decisions)))
        self.assertEqual(decisions[0]["payload"]["reason_codes"], ["AUTHORITY_REENTRANT_EVALUATION"])
        self.assertEqual(decisions[1]["event_type"], "authorization.blocked")

    def test_memory_data_plane_still_requires_authority(self):
        from memory import AuthorityEvidenceReader
        engine = self._engine(AuthorityEvidenceReader(self.db))
        store = self._production_memory(engine)
        # The only applicability record on this task binds WRITE on the repo resource,
        # not a Memory read, so the data-plane read is denied (fail closed, depth 1).
        with self.assertRaisesRegex(Exception, "BLOCKED"):
            store.get_task(self.task_id)
        self.assertEqual(self.principal.calls, 1)
        self.assertEqual([e["event_type"] for e in self.sink.decisions()], ["authorization.blocked"])


if __name__ == "__main__":
    unittest.main()
