"""Isolated integration tests for explicit local bootstrap."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_bootstrap import bootstrap_local_root
from maep.native_authority import AuthorityError
from maep.local_owner_authority import LocalOwnerApprovalSource


class FailingEvidenceSink:
    def append(self, event):
        raise OSError("fixture evidence failure")


class LocalBootstrapTests(unittest.TestCase):
    def _owner_source(self, directory: Path) -> LocalOwnerApprovalSource:
        path = directory / "owner.json"
        data = {
            "schema_version": "hg.local-owner-bootstrap-source.v1",
            "repository": "OAI-GIANG/HG",
            "device_scope": "this-phone-local-only",
            "decision": "APPROVE",
            "action": "bootstrap_initial_trust_root",
            "authorization_basis": "isolated test only",
            "authorization_ref": "owner-local:bootstrap-test",
            "approved_at": "2026-10-23T00:00:00Z",
            "root_payload": {
                "root_id": "hg-test-root", "generation": 1,
                "created_at": "2026-10-23T00:00:00Z",
                "bootstrap_authorization_ref": "owner-local:bootstrap-test",
                "verification_method": "local-owner-source-v1",
                "verification_material_ref": "file://fixture-owner",
                "policy_change_rule_ref": "file://fixture-policy-rule",
                "previous_root_digest": None,
            },
            "activation_status": "SOURCE_CREATED_ROOT_NOT_PROVISIONED",
            "limitations": "isolated fixture; not production trust",
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        path.chmod(0o600)
        return LocalOwnerApprovalSource(path)

    def test_explicit_bootstrap_reopens_root_and_evidence_only_under_temp_path(self):
        with tempfile.TemporaryDirectory(prefix="hg-explicit-bootstrap-") as temp:
            base = Path(temp)
            source = self._owner_source(base)
            root = bootstrap_local_root(data_directory=base / "isolated-state", owner_source=source)
            self.assertTrue(root.verify_integrity())
            reopened = LocalRootStore(base / "isolated-state" / "root").load_active()
            self.assertEqual(reopened.record_digest, root.record_digest)
            sink = LocalEvidenceSink(base / "isolated-state" / "evidence")
            self.assertTrue(sink.verify_integrity())
            self.assertEqual(len(sink._read_events()), 1)
            self.assertFalse((base / "isolated-state" / "policy").exists())

    def test_invalid_or_pending_source_never_bootstraps(self):
        with tempfile.TemporaryDirectory(prefix="hg-invalid-bootstrap-") as temp:
            base = Path(temp)
            source = self._owner_source(base)
            data = source.load()
            data["activation_status"] = "ACTIVE"
            source.path.write_text(json.dumps(data), encoding="utf-8")
            source.path.chmod(0o600)
            with self.assertRaisesRegex(AuthorityError, "pending state"):
                bootstrap_local_root(data_directory=base / "isolated-state", owner_source=source)
            self.assertIsNone(LocalRootStore(base / "isolated-state" / "root").load_active())

    def test_evidence_failure_blocks_bootstrap_before_root_write(self):
        with tempfile.TemporaryDirectory(prefix="hg-bootstrap-evidence-failure-") as temp:
            base = Path(temp)
            source = self._owner_source(base)
            from maep.native_authority import TrustRootManager
            store = LocalRootStore(base / "root")
            manager = TrustRootManager(store, source, FailingEvidenceSink())
            approval = source.load()
            with self.assertRaisesRegex(AuthorityError, "evidence was not durably recorded"):
                manager.bootstrap(approval["root_payload"], approval)
            self.assertIsNone(store.load_active())


if __name__ == "__main__":
    unittest.main()
