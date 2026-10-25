import tempfile
import unittest
from pathlib import Path

from maep.core import POLICY_VERSION
from maep.native_authority import Applicability, NativePolicyEngine, TrustRootRecord
from memory import MemoryStore
from memory.authority_adapter import MemoryNativeAuthorityAdapter


class RootStore:
    def __init__(self):
        self.root = TrustRootRecord.create(
            root_id="test-root", generation=1, created_at="2026-10-22T10:00:00Z",
            bootstrap_authorization_ref="test-approved", verification_method="test-only",
            verification_material_ref="fixture-ref", policy_change_rule_ref="policy-change:1",
            evidence_ref="ledger:bootstrap",
        )
    def load_active(self): return self.root
    def store_active(self, record): self.root = record


class Sink:
    def __init__(self): self.events = []
    def append(self, event):
        self.events.append(event)
        return "ledger:" + str(len(self.events))


class Principal:
    def resolve(self, context):
        if context != "test-auth-context": return None
        return {
            "principal_id": "test-runtime-principal", "status": "ACTIVE", "verified": True, "identity_evidence_ref": "identity:test",
            "capabilities": ["WRITE"], "resource_scopes": [
                "memory:database [store:{db}]".format(db=self.db_path),
                "memory:database/schema [store:{db}]".format(db=self.db_path),
            ],
            "allowed_scopes": ["memory:schema:initialize", "memory:schema:create"],
        }


class Candidate:
    def inspect(self, target):
        if target != "test-candidate-target": return None
        return {"verified": True, "repository": "OAI-GIANG/HG", "source_manifest_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "candidate_ref": "candidate:test"}


class Policy:
    def __init__(self, db_path): self.db_path = str(db_path)
    def load_active(self, root):
        return {
            "status": "ACTIVE", "version": POLICY_VERSION, "root_generation": root.generation, "provenance_verified": True, "policy_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "approval_evidence_refs": ["approval:test"],
            "grant_ttl_seconds": 60,
            "rules": [
                {"action": "WRITE", "resource": f"memory:database [store:{self.db_path}]",
                 "effect": "ALLOW", "scope": ["memory:schema:initialize"]},
                {"action": "WRITE", "resource": f"memory:database/schema [store:{self.db_path}]",
                 "effect": "ALLOW", "scope": ["memory:schema:create"]},
            ],
        }


class ApplicabilityProvider:
    def classify(self, request, candidate):
        return {
            "verified": True, "classification": Applicability.NOT_REQUIRED.value,
            "candidate_ref": candidate["candidate_ref"], "action": request["action"],
            "resource": request["resource"], "applicability_id": "app:test", "rule_version": "app-rules:1", "facts_used": ["action", "resource"], "evidence_refs": ["app-evidence:test"],
        }


class Gate:
    def evaluate(self, request, candidate, policy):
        return {"status": "PASS", "verified": True, "evidence_verified": True, "evidence_refs": ["gate-evidence:test"], "candidate_ref": candidate["candidate_ref"],
                "policy_version": policy["version"], "gate_id": "gate:test"}


class MemoryNativeAuthorityIntegrationTests(unittest.TestCase):
    def test_memory_initialization_uses_candidate_bound_native_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "memory.sqlite3"
            principal = Principal()
            principal.db_path = str(db_path)
            root_store = RootStore()
            policy = Policy(db_path)
            engine = NativePolicyEngine(
                root_store=root_store, principal_provider=principal, candidate_provider=Candidate(),
                policy_provider=policy, applicability_provider=ApplicabilityProvider(),
                gate_provider=Gate(), evidence_sink=Sink(),
            )
            adapter = MemoryNativeAuthorityAdapter(
                engine=engine,
                authenticated_context_provider=lambda: "test-auth-context",
                candidate_target_provider=lambda request: "test-candidate-target",
            )
            store = MemoryStore(
                db_path, principal_provider=lambda: "test-runtime-principal",
                policy_evaluator=adapter.policy_evaluator,
                applicability_provider=adapter.applicability_provider,
                candidate_ref_provider=lambda task_id: "candidate:test",
                effect_recheck_provider=adapter.effect_recheck_provider,
            )
            result = store.initialize(task_id="T-BOOT")
            self.assertEqual(result["status"], "READY")
            self.assertTrue(db_path.exists())

    def test_memory_rechecks_authority_before_creating_database(self):
        class RevokingPrincipal(Principal):
            def __init__(self): self.calls = 0
            def resolve(self, context):
                self.calls += 1
                principal = super().resolve(context)
                if self.calls >= 2:
                    principal = dict(principal)
                    principal["revoked"] = True
                return principal
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "memory.sqlite3"
            principal = RevokingPrincipal()
            principal.db_path = str(db_path)
            engine = NativePolicyEngine(
                root_store=RootStore(), principal_provider=principal, candidate_provider=Candidate(),
                policy_provider=Policy(db_path), applicability_provider=ApplicabilityProvider(),
                gate_provider=Gate(), evidence_sink=Sink(),
            )
            adapter = MemoryNativeAuthorityAdapter(
                engine=engine, authenticated_context_provider=lambda: "test-auth-context",
                candidate_target_provider=lambda request: "test-candidate-target",
            )
            store = MemoryStore(
                db_path, principal_provider=lambda: "test-runtime-principal",
                policy_evaluator=adapter.policy_evaluator,
                applicability_provider=adapter.applicability_provider,
                candidate_ref_provider=lambda task_id: "candidate:test",
                effect_recheck_provider=adapter.effect_recheck_provider,
            )
            with self.assertRaisesRegex(Exception, "Memory pre-effect authority recheck failed"):
                store.initialize(task_id="T-REVOKED")
            self.assertFalse(db_path.exists())

    def test_memory_native_adapter_blocks_without_candidate_identity(self):
        adapter = MemoryNativeAuthorityAdapter(
            engine=object(), authenticated_context_provider=lambda: "ctx",
            candidate_target_provider=lambda request: "target",
        )
        with self.assertRaisesRegex(Exception, "exact candidate identity"):
            adapter.policy_evaluator({"action": "WRITE", "resource": "memory", "scope": ["write"]})


if __name__ == "__main__":
    unittest.main()
