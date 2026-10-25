import tempfile
import unittest
from pathlib import Path

from maep.native_authority import AuthorityError
from runtime.composition import build_runtime


class EmptyRootStore:
    def load_active(self):
        return None


class RuntimeCompositionTests(unittest.TestCase):
    def test_missing_bootstrap_root_blocks_before_memory_database_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "memory.sqlite3"
            deps = {
                "root_store": EmptyRootStore(),
                "principal_provider": object(),
                "candidate_provider": object(),
                "policy_provider": object(),
                "applicability_provider": object(),
                "gate_provider": object(),
                "evidence_sink": object(),
                "authenticated_context_provider": lambda: "test-only",
                "candidate_target_provider": lambda request: "test-only",
                "memory_principal_provider": lambda: "test-only",
                "memory_candidate_ref_provider": lambda task_id: "candidate:test",
                "memory_db_path": db,
                "live_state_provider": object(),
                "acceptance_provider": object(),
                "adapter_registry": {"test": object()},
                "idempotency_ledger": object(),
                "receipt_sink": object(),
            }
            with self.assertRaisesRegex(AuthorityError, "approved active TrustRoot unavailable"):
                build_runtime(**deps)
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
