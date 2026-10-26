"""LocalLiveStateProvider: live task/candidate/policy/resource observation for Memory."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from maep.core import POLICY_VERSION
from maep.local_authority_store import LocalRootStore
from maep.local_runtime_providers import GitCandidateProvider, LocalLiveStateProvider, LocalPolicyProvider, _digest
from maep.native_authority import AuthorityError, TrustRootRecord
from memory import MemoryStore
from memory.tests import test_store as store_fixtures


class AcceptMarkedPolicy:
    def verify_policy_source(self, record, *, root, policy):
        return record.get("fixture_approval") == "test-only"


def git(checkout, *args):
    subprocess.run(["git", "-C", str(checkout), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


class LocalLiveStateProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-live-state-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.checkout = base / "checkout"
        self.checkout.mkdir()
        git(self.checkout, "init", "-q")
        git(self.checkout, "remote", "add", "origin", "https://github.com/OAI-GIANG/HG.git")
        (self.checkout / "README.md").write_text("x\n")
        git(self.checkout, "add", "README.md")
        git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x")
        self.root_store = LocalRootStore(base / "authority")
        self.root_store.store_active(TrustRootRecord.create(
            root_id="r", generation=1, created_at="2026-10-26T00:00:00Z", bootstrap_authorization_ref="f",
            verification_method="f", verification_material_ref="f", policy_change_rule_ref="f", evidence_ref="f"))
        self.policy_path = base / "policy.json"
        self.write_policy(POLICY_VERSION)
        self.candidates = GitCandidateProvider(self.checkout)
        self.provider = LocalLiveStateProvider(
            candidate_provider=self.candidates, checkout=self.checkout,
            policy_provider=LocalPolicyProvider(self.policy_path, AcceptMarkedPolicy()), root_store=self.root_store)

    def write_policy(self, version, marker="test-only"):
        policy = {"status": "ACTIVE", "version": version, "root_generation": 1,
                  "approval_evidence_refs": ["fixture"], "grant_ttl_seconds": 60, "rules": []}
        if self.policy_path.exists():
            self.policy_path.unlink()
        fd = os.open(self.policy_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"policy": policy, "policy_digest": _digest(policy), "fixture_approval": marker}, handle)

    def test_observes_candidate_policy_and_checkout_resource(self):
        observed = self.provider("T-1")
        candidate = self.candidates.inspect(str(self.checkout))
        self.assertEqual(observed["task_id"], "T-1")
        self.assertEqual(observed["candidate_ref"], candidate["candidate_ref"])
        self.assertEqual(observed["policy_version"], POLICY_VERSION)
        self.assertEqual(observed["resources"], [{"resource_id": "repo:OAI-GIANG/HG",
                                                  "version": candidate["source_manifest_digest"]}])
        self.assertTrue(observed["observed_at"].endswith("Z"))

    def test_checkout_change_is_observed(self):
        before = self.provider("T-1")
        (self.checkout / "README.md").write_text("changed\n")
        after = self.provider("T-1")
        self.assertNotEqual(before["candidate_ref"], after["candidate_ref"])
        self.assertNotEqual(before["resources"], after["resources"])

    def test_unverified_policy_candidate_or_root_raise(self):
        self.write_policy(POLICY_VERSION, marker="not-approved")
        with self.assertRaises(AuthorityError):
            self.provider("T-1")
        self.write_policy(POLICY_VERSION)
        git(self.checkout, "remote", "set-url", "origin", "https://example.invalid/other.git")
        with self.assertRaisesRegex(AuthorityError, "candidate"):
            self.provider("T-1")
        git(self.checkout, "remote", "set-url", "origin", "https://github.com/OAI-GIANG/HG.git")
        (Path(self.tmp.name) / "authority" / "active-root.json").unlink()
        with self.assertRaisesRegex(AuthorityError, "trust root"):
            self.provider("T-1")
        with self.assertRaises(AuthorityError):
            self.provider("")

    def test_memory_checkpoint_resumes_current_then_blocks_on_checkout_drift(self):
        candidate_ref = self.candidates.inspect(str(self.checkout))["candidate_ref"]
        store = MemoryStore(Path(self.tmp.name) / "memory.sqlite3", principal_provider=lambda: "p",
                            policy_evaluator=store_fixtures.policy_decision, live_state_provider=self.provider,
                            applicability_provider=store_fixtures.applicability_provider_for_test)
        store.initialize(task_id="T-BOOT")
        store.create_task(store_fixtures.MemoryStoreTests.task("T-1"), candidate_ref=candidate_ref)
        store.save_checkpoint(
            "T-1", expected_version=1, completed_steps=[],
            pending_steps=[{"step_id": "STEP-1", "prerequisites": [], "acceptance_conditions": ["live agrees"]}],
            blockers=[], decisions=[], evidence_refs=[],
            next_action={"description": "inspect", "preconditions": ["checkpoint current"],
                         "required_authorization": {"action": "READ", "resource": "repo:OAI-GIANG/HG"},
                         "expected_result": "context", "stop_condition": "conflict"})
        decision = store.assess_resume("T-1")
        self.assertEqual((decision["status"], decision["can_resume"]), ("CURRENT", True))
        (self.checkout / "README.md").write_text("drift\n")
        decision = store.assess_resume("T-1")
        self.assertFalse(decision["can_resume"])
        self.assertNotEqual(decision["status"], "CURRENT")


if __name__ == "__main__":
    unittest.main()
