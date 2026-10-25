"""N1: how MAEP-022 applicability scopes Memory data-plane access in the production graph.

NativePolicyEngine requires a verified applicability record bound to the exact
(candidate, action, resource) of every request, and MemoryStore routes each data-plane
read/write through the engine (runtime.composition). CanonicalMemoryTaskSelectors admits
one `maep022:applicability` reference per task. Consequence, shown below: per task, one
Memory (action, resource) can be authorized; every other Memory operation on that task
is BLOCKED. maep/spec/LOCAL_VALIDATION_RECORD_V1.md records the intent that ordinary
Memory data-plane access is not a MAEP-022 capability change, so whether this scope is
intended is an owner policy decision (N1) -- these tests pin the current fail-closed
behaviour and the denial cases that must hold under any decision.
"""
import json
import unittest

from maep.core import POLICY_VERSION
from maep.native_authority import Decision
from memory import AuthorityEvidenceReader, MemoryStore
from memory.authority_adapter import MemoryNativeAuthorityAdapter
from memory.tests import test_store as store_fixtures

read_path = __import__("test_authority_memory_read_path")
CANDIDATE, PRINCIPAL = read_path.CANDIDATE, read_path.PRINCIPAL


class MemoryPolicy:
    def __init__(self, rules):
        self.rules = rules

    def load_active(self, root):
        return {"status": "ACTIVE", "version": POLICY_VERSION, "root_generation": root.generation,
                "provenance_verified": True, "policy_digest": "sha256:" + "d" * 64,
                "approval_evidence_refs": ["fixture:policy-approval"], "grant_ttl_seconds": 60,
                "rules": self.rules}


class MemoryPrincipal(read_path.PrincipalFixture):
    def __init__(self, resources, scopes):
        super().__init__()
        self.resources, self.scopes = resources, scopes

    def resolve(self, context):
        record = super().resolve(context)
        record.update(capabilities=["READ"], resource_scopes=list(self.resources),
                      allowed_scopes=list(self.scopes))
        return record


class MemoryApplicabilityScopeTests(unittest.TestCase):
    def setUp(self):
        self.memory = store_fixtures.MemoryStoreTests()
        self.memory.setUp()
        self.addCleanup(self.memory.tearDown)
        self.db = self.memory.db
        self.path = self.memory.store.path

    def resource(self, kind, task_id):
        return f"memory:{kind}/{task_id} [store:{self.path}]"

    def build(self, task_id, *, app_refs, records):
        task = store_fixtures.MemoryStoreTests.task(task_id)
        task["inputs"] = [{"ref_id": ref, "kind": "EVIDENCE", "description": "maep022:applicability"}
                          for ref in app_refs] + [
                         {"ref_id": "EV-SUPPORT", "kind": "EVIDENCE", "description": "support"}]
        self.memory.store.create_task(task, candidate_ref=CANDIDATE)
        records = dict(records, **{"EV-SUPPORT": ({"candidate_ref": CANDIDATE}, "test://approved-source")})
        for evidence_id, (payload, source) in records.items():
            evidence = store_fixtures.MemoryStoreTests.evidence(evidence_id, CANDIDATE)
            evidence.update(evidence_type="OTHER", source_ref=source,
                            result=json.dumps(payload, sort_keys=True, separators=(",", ":")))
            self.memory.store.record_evidence(task_id, evidence)
        task_res, events_res = self.resource("task", task_id), self.resource("events", task_id)
        scopes = [f"memory:task:{task_id}:read", f"memory:task:{task_id}:events:read"]
        rules = [{"action": "READ", "resource": task_res, "scope": [scopes[0]], "effect": "ALLOW"},
                 {"action": "READ", "resource": events_res, "scope": [scopes[1]], "effect": "ALLOW"}]
        self.principal = MemoryPrincipal([task_res, events_res], scopes)
        self.sink = read_path.EvidenceSinkFixture()
        root, policy = read_path.RootStoreFixture(), MemoryPolicy(rules)
        reader = AuthorityEvidenceReader(self.db)
        from maep.memory_evidence_providers import (CanonicalMemoryTaskSelectors,
                                                    MemoryLedgerProvenanceVerifier, MemoryMAEPRecordResolver)
        from maep.native_authority import NativePolicyEngine
        from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider
        resolver = MemoryMAEPRecordResolver(
            memory_store=reader, selectors=CanonicalMemoryTaskSelectors(
                memory_store=reader, index_scope_task_id=task_id))
        verifier = MemoryLedgerProvenanceVerifier(read_path.ApprovedSourceFixture())
        engine = NativePolicyEngine(
            root_store=root, principal_provider=self.principal,
            candidate_provider=read_path.CandidateFixture(), policy_provider=policy,
            applicability_provider=TrustedApplicabilityProvider(
                root_store=root, policy_provider=policy, resolver=resolver, verifier=verifier),
            gate_provider=TrustedGateEvidenceProvider(
                root_store=root, policy_provider=policy, resolver=resolver, verifier=verifier),
            evidence_sink=self.sink)
        adapter = MemoryNativeAuthorityAdapter(
            engine=engine, authenticated_context_provider=lambda: "fixture-session",
            candidate_target_provider=lambda request: "fixture-target")
        return MemoryStore(
            self.db, principal_provider=lambda: PRINCIPAL, policy_evaluator=adapter.policy_evaluator,
            live_state_provider=self.memory.live_state,
            applicability_provider=adapter.applicability_provider,
            candidate_ref_provider=lambda task_id: CANDIDATE,
            effect_recheck_provider=adapter.effect_recheck_provider)

    def applicability(self, task_id, kind, *, candidate=CANDIDATE):
        return {"candidate_ref": candidate, "action": "READ", "resource": self.resource(kind, task_id),
                "classification": "NOT_REQUIRED", "facts_used": ["memory-data-plane"],
                "evidence_refs": ["EV-SUPPORT"], "rule_version": "MAEP-022-v1",
                "applicability_id": f"APP-{kind}"}

    def decisions(self):
        return [event["event_type"] for event in self.sink.decisions()]

    def test_memory_read_bound_by_its_record_is_authorized_end_to_end(self):
        store = self.build("T-N1-A", app_refs=["EV-APP"], records={
            "EV-APP": (self.applicability("T-N1-A", "task"), "test://approved-source")})
        snapshot = store.get_task("T-N1-A")
        self.assertEqual(snapshot["task"]["task_id"], "T-N1-A")
        # authorize at the policy seam + fresh authorize at the pre-effect recheck
        self.assertEqual(self.decisions(), ["authorization.decision", "authorization.decision"])

    def test_second_memory_action_on_same_task_is_blocked_without_its_own_record(self):
        # N1 (pending owner decision): the task's single applicability record binds the
        # task read, so reading the same task's events is denied.
        store = self.build("T-N1-B", app_refs=["EV-APP"], records={
            "EV-APP": (self.applicability("T-N1-B", "task"), "test://approved-source")})
        store.get_task("T-N1-B")
        with self.assertRaisesRegex(Exception, "BLOCKED"):
            store.get_events("T-N1-B")
        self.assertEqual(self.decisions()[-1], "authorization.blocked")

    def test_two_applicability_references_on_one_task_are_ambiguous_and_blocked(self):
        store = self.build("T-N1-C", app_refs=["EV-APP", "EV-APP-2"], records={
            "EV-APP": (self.applicability("T-N1-C", "task"), "test://approved-source"),
            "EV-APP-2": (self.applicability("T-N1-C", "events"), "test://approved-source")})
        for call in (lambda: store.get_task("T-N1-C"), lambda: store.get_events("T-N1-C")):
            with self.assertRaisesRegex(Exception, "BLOCKED"):
                call()
        self.assertEqual(set(self.decisions()), {"authorization.blocked"})

    def test_record_for_another_candidate_is_blocked(self):
        store = self.build("T-N1-D", app_refs=["EV-APP"], records={
            "EV-APP": (self.applicability("T-N1-D", "task", candidate="candidate-OTHER"),
                       "test://approved-source")})
        with self.assertRaisesRegex(Exception, "BLOCKED"):
            store.get_task("T-N1-D")

    def test_record_from_an_unapproved_source_is_blocked(self):
        store = self.build("T-N1-E", app_refs=["EV-APP"], records={
            "EV-APP": (self.applicability("T-N1-E", "task"), "test://not-approved")})
        with self.assertRaisesRegex(Exception, "BLOCKED"):
            store.get_task("T-N1-E")
        self.assertEqual(self.decisions(), ["authorization.blocked"])

    def test_task_without_applicability_record_is_blocked(self):
        store = self.build("T-N1-F", app_refs=[], records={})
        with self.assertRaisesRegex(Exception, "BLOCKED"):
            store.get_task("T-N1-F")


if __name__ == "__main__":
    unittest.main()
