"""Isolated tests for the local file-backed authority stores."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.native_authority import AuthorityError, TrustRootManager
from maep.local_owner_authority import LocalOwnerApprovalSource


class TempOwnerSource:
    def __init__(self, source):
        self.source = source

    def validate_owner_approval(self, canonical_payload, approval):
        return self.source.validate_owner_approval(canonical_payload, approval)


class LocalAuthorityStoreTests(unittest.TestCase):
    def test_bootstrap_root_readback_and_evidence_integrity_in_temp_directory(self):
        with tempfile.TemporaryDirectory(prefix="hg-authority-test-") as temp:
            temp_path = Path(temp)
            source_path = temp_path / "owner-bootstrap.json"
            source_data = {
                "schema_version": "hg.local-owner-bootstrap-source.v1",
                "repository": "OAI-GIANG/HG",
                "device_scope": "this-phone-local-only",
                "decision": "APPROVE",
                "action": "bootstrap_initial_trust_root",
                "authorization_basis": "isolated unit test",
                "authorization_ref": "owner-local:test",
                "approved_at": "2026-10-23T00:00:00Z",
                "root_payload": {
                    "root_id": "hg-test-root",
                    "generation": 1,
                    "created_at": "2026-10-23T00:00:00Z",
                    "bootstrap_authorization_ref": "owner-local:test",
                    "verification_method": "local-owner-source-v1",
                    "verification_material_ref": "file://test-owner-source",
                    "policy_change_rule_ref": "file://test-policy-rule",
                    "previous_root_digest": None,
                },
                "activation_status": "SOURCE_CREATED_ROOT_NOT_PROVISIONED",
                "limitations": "test-only",
            }
            source_path.write_text(json.dumps(source_data), encoding="utf-8")
            source_path.chmod(0o600)
            owner_source = LocalOwnerApprovalSource(source_path)
            root_store = LocalRootStore(temp_path / "root-store")
            evidence = LocalEvidenceSink(temp_path / "evidence")
            manager = TrustRootManager(root_store, TempOwnerSource(owner_source), evidence)

            root = manager.bootstrap(source_data["root_payload"], source_data)
            self.assertTrue(root.verify_integrity())
            reloaded = root_store.load_active()
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.record_digest, root.record_digest)
            self.assertTrue(evidence.verify_integrity())
            self.assertEqual(len(evidence._read_events()), 1)
            self.assertIn("hg-local-evidence:1:", root.evidence_ref)

            with self.assertRaisesRegex(AuthorityError, "already exists"):
                manager.bootstrap(source_data["root_payload"], source_data)

    def test_root_tamper_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="hg-root-tamper-") as temp:
            store = LocalRootStore(temp)
            from maep.native_authority import TrustRootRecord
            root = TrustRootRecord.create(
                root_id="root-test", generation=1, created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="owner:test",
                verification_method="test", verification_material_ref="test://material",
                policy_change_rule_ref="test://policy", evidence_ref="test://evidence",
            )
            store.store_active(root)
            value = json.loads(store.root_path.read_text(encoding="utf-8"))
            value["root_id"] = "tampered"
            store.root_path.write_text(json.dumps(value), encoding="utf-8")
            store.root_path.chmod(0o600)
            with self.assertRaises(AuthorityError):
                store.load_active()

    def test_evidence_tamper_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="hg-evidence-tamper-") as temp:
            sink = LocalEvidenceSink(temp)
            sink.append({"event_type": "test", "payload": {"x": 1}})
            self.assertTrue(sink.verify_integrity())
            lines = sink.ledger_path.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["payload"]["x"] = 2
            sink.ledger_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            sink.ledger_path.chmod(0o600)
            with self.assertRaises(AuthorityError):
                sink.verify_integrity()

    def test_root_store_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="hg-root-no-overwrite-") as temp:
            from maep.native_authority import TrustRootRecord
            store = LocalRootStore(temp)
            root = TrustRootRecord.create(
                root_id="root-test", generation=1, created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="owner:test",
                verification_method="test", verification_material_ref="test://material",
                policy_change_rule_ref="test://policy", evidence_ref="test://evidence",
            )
            store.store_active(root)
            with self.assertRaisesRegex(AuthorityError, "overwrite"):
                store.store_active(root)


if __name__ == "__main__":
    unittest.main()
