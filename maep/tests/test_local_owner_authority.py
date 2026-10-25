import json
import tempfile
import unittest
from pathlib import Path

from maep.local_owner_authority import (
    LocalOwnerApprovalSource, LocalOwnerAuthorityError,
    canonical_json_bytes,
)


class LocalOwnerApprovalSourceTests(unittest.TestCase):
    def make_source(self, directory):
        payload = {
            "root_id": "hg-test-root",
            "generation": 1,
            "created_at": "2026-10-23T00:00:00Z",
            "bootstrap_authorization_ref": "owner-test:1",
            "verification_method": "local-owner-source-v1",
            "verification_material_ref": "file://owner-bootstrap.json",
            "policy_change_rule_ref": "file://policy-change-rule.json",
            "previous_root_digest": None,
        }
        source = {
            "schema_version": "hg.local-owner-bootstrap-source.v1",
            "repository": "OAI-GIANG/HG",
            "device_scope": "this-phone-local-only",
            "decision": "APPROVE",
            "action": "bootstrap_initial_trust_root",
            "authorization_basis": "test only",
            "authorization_ref": "owner-test:1",
            "approved_at": "2026-10-23T00:00:00Z",
            "root_payload": payload,
            "activation_status": "SOURCE_CREATED_ROOT_NOT_PROVISIONED",
        }
        path = Path(directory) / "owner-bootstrap.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        path.chmod(0o600)
        return path, payload, source

    def test_approves_exact_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path, payload, source = self.make_source(directory)
            verifier = LocalOwnerApprovalSource(path)
            self.assertTrue(
                verifier.validate_owner_approval(canonical_json_bytes(payload), source)
            )
            changed = dict(payload, root_id="different-root")
            self.assertFalse(
                verifier.validate_owner_approval(canonical_json_bytes(changed), source)
            )

    def test_wrong_repository_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path, payload, source = self.make_source(directory)
            source["repository"] = "OAI-GIANG/HG2"
            path.write_text(json.dumps(source), encoding="utf-8")
            path.chmod(0o600)
            self.assertFalse(
                LocalOwnerApprovalSource(path).validate_owner_approval(
                    canonical_json_bytes(payload), source
                )
            )

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.make_source(directory)
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(LocalOwnerAuthorityError):
                LocalOwnerApprovalSource(link).load()

    def test_permissive_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _ = self.make_source(directory)
            path.chmod(0o644)
            with self.assertRaises(LocalOwnerAuthorityError):
                LocalOwnerApprovalSource(path).load()


if __name__ == "__main__":
    unittest.main()
