import unittest

from maep.native_authority import AuthorityError, TrustRootRecord
from runtime.composition import build_runtime


class RootStore:
    def __init__(self):
        self.root = TrustRootRecord.create(
            root_id="root:test", generation=1, created_at="2026-10-22T10:00:00Z",
            bootstrap_authorization_ref="approved:test", verification_method="fixture",
            verification_material_ref="fixture-only", policy_change_rule_ref="policy-change:test",
            evidence_ref="ledger:test",
        )

    def load_active(self):
        return self.root


class PolicyProvider:
    def load_active(self, root):
        return {
            "status": "ACTIVE", "version": "policy:test",
            "root_generation": root.generation, "provenance_verified": True,
            "policy_digest": "sha256:" + "0" * 64,
            "approval_evidence_refs": ["approval:test"],
        }


class RuntimeCompositionTests(unittest.TestCase):
    def test_composition_rejects_untrusted_provider_implementations(self):
        dependencies = {
            "root_store": RootStore(), "principal_provider": object(),
            "candidate_provider": object(), "policy_provider": PolicyProvider(),
            "applicability_provider": object(), "gate_provider": object(),
            "evidence_sink": object(), "authenticated_context_provider": lambda: None,
            "candidate_target_provider": lambda: None, "memory_principal_provider": lambda: None,
            "memory_candidate_ref_provider": lambda: None, "memory_db_path": "/tmp/hg-isolated-test.db",
            "live_state_provider": lambda: None, "acceptance_provider": lambda: None,
            "adapter_registry": {"test": object()}, "idempotency_ledger": object(),
            "receipt_sink": object(),
        }
        with self.assertRaisesRegex(AuthorityError, "trusted applicability provider required"):
            build_runtime(**dependencies)


if __name__ == "__main__":
    unittest.main()
