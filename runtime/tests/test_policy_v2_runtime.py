"""Integration of strict policy-v2 validation with real local owner approval in temp fixtures."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from maep.local_runtime_providers import _digest, _write_new_json, LocalPolicyProvider
from maep.policy_templates import POLICY_SCHEMA_V2
from maep.local_authority_store import LocalRootStore
from runtime.owner_approvals import (
    LocalPolicyApprovalVerifier, approve_policy,
)
from maep.native_authority import AuthorityError

fixture = __import__("e2e_fixture_factory")


def make_policy(root_generation, *, resource="memory:task/{task_id} [store:/test/memory.sqlite3]", scope="memory:task:{task_id}:read"):
    return {
        "schema_version": POLICY_SCHEMA_V2,
        "status": "ACTIVE",
        "version": "hg-runtime-v2-test",
        "root_generation": root_generation,
        "approval_evidence_refs": ["owner:test-runtime-policy-v2"],
        "grant_ttl_seconds": 30,
        "applicability_rules": [{
            "rule_id": "memory-read",
            "actions": ["READ"],
            "resource_prefix": "memory:",
            "classification": "NOT_REQUIRED",
        }],
        "rules": [{
            "action": "READ",
            "resource": resource,
            "match_mode": "TEMPLATE",
            "effect": "ALLOW",
            "scope": [scope],
        }],
    }


class PolicyV2RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-policy-v2-runtime-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.base / "fixture")
        self.config = self.state["config"]
        self.policy_path = self.base / "active-policy.json"
        self.approval_path = self.base / "policy-approval.json"
        self.authority_dir = self.config["authority_dir"]
        self.root = LocalRootStore(self.authority_dir).load_active()

    def write_policy(self, policy):
        _write_new_json(self.policy_path, {
            "policy": policy,
            "policy_digest": _digest(policy),
        })

    def test_owner_approval_binds_exact_valid_policy_v2(self):
        policy = make_policy(self.root.generation)
        self.write_policy(policy)
        result = approve_policy(
            policy_path=self.policy_path,
            authority_dir=self.authority_dir,
            approval_path=self.approval_path,
            approval_ref="owner:test-runtime-policy-v2",
        )
        self.assertEqual(result["result"], "APPROVED")
        self.assertEqual(result["policy_digest"], _digest(policy))
        self.assertEqual(os.stat(self.approval_path).st_mode & 0o777, 0o600)
        verifier = LocalPolicyApprovalVerifier(self.approval_path)
        active = LocalPolicyProvider(self.policy_path, verifier).load_active(self.root)
        self.assertEqual(active["schema_version"], POLICY_SCHEMA_V2)
        self.assertIs(active["provenance_verified"], True)
        self.assertEqual(active["policy_digest"], _digest(policy))

    def test_owner_approval_rejects_unknown_resource_template_without_record(self):
        policy = make_policy(self.root.generation, resource="memory:task/{arbitrary} [store:/test/memory.sqlite3]")
        self.write_policy(policy)
        with self.assertRaisesRegex(AuthorityError, "policy v2 schema validation failed"):
            approve_policy(
                policy_path=self.policy_path,
                authority_dir=self.authority_dir,
                approval_path=self.approval_path,
                approval_ref="owner:test-runtime-policy-v2",
            )
        self.assertFalse(self.approval_path.exists())

    def test_policy_provider_rejects_tamper_after_approval(self):
        policy = make_policy(self.root.generation)
        self.write_policy(policy)
        approve_policy(
            policy_path=self.policy_path,
            authority_dir=self.authority_dir,
            approval_path=self.approval_path,
            approval_ref="owner:test-runtime-policy-v2",
        )
        changed = dict(policy, grant_ttl_seconds=300)
        # Test tampering: rewrite an isolated test document; do not change approval.
        p = {"policy": changed, "policy_digest": _digest(changed)}
        self.policy_path.unlink()
        _write_new_json(self.policy_path, p)
        verifier = LocalPolicyApprovalVerifier(self.approval_path)
        with self.assertRaises(AuthorityError):
            LocalPolicyProvider(self.policy_path, verifier).load_active(self.root)

    def test_v2_policy_generation_mismatch_cannot_be_approved(self):
        policy = make_policy(self.root.generation + 1)
        self.write_policy(policy)
        with self.assertRaisesRegex(AuthorityError, "schema validation failed"):
            approve_policy(
                policy_path=self.policy_path,
                authority_dir=self.authority_dir,
                approval_path=self.approval_path,
                approval_ref="owner:test-runtime-policy-v2",
            )
        self.assertFalse(self.approval_path.exists())


if __name__ == "__main__":
    unittest.main()
