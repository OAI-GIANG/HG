"""Per-task grants issued only from the owner manifest (all-or-nothing, capped expiry, single issuer)."""
import unittest
from datetime import datetime, timedelta, timezone

from maep.authority.canonical_source import CanonicalManifest
from maep.authority.issuer import IssuedGrantEvaluator, TaskGrantIssuer
from maep.core import MAEPError
from maep.tests.test_canonical_source import MAIN_SHA, FakeGitHub, manifest

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def step(sid="S-1", resource="file:out/a.txt", action="WRITE", task="T-1"):
    return {"step_id": sid, "tool": "fs.write", "action": action, "resource": resource, "scope": ["out/"],
            "authorization_id": f"{task}/{sid}", "params": {}}


def request(s, task="T-1", principal="STT"):
    return {"authorization_id": s["authorization_id"], "principal": principal, "action": s["action"],
            "resource": s["resource"], "scope": s["scope"], "task_id": task, "policy_version": "MAEP-1.1.0"}


class IssuerTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub(files={MAIN_SHA: manifest(expires="2026-11-22T12:00:00Z")})
        self.clock = lambda: NOW
        self.source = CanonicalManifest.from_github(http_get=self.gh.get, max_age_s=0, clock=self.clock)
        self.evaluator = IssuedGrantEvaluator()
        self.issuer = TaskGrantIssuer(self.source, self.evaluator, principal="STT", ttl_s=3600, clock=self.clock)

    def test_permitted_plan_gets_bounded_grants(self):
        grants, provenance = self.issuer.issue_for_plan("T-1", [step()])
        self.assertEqual(provenance["commit"], MAIN_SHA)
        self.assertEqual(grants[0]["expires_at"], (NOW + timedelta(hours=1)).isoformat())
        self.assertEqual(self.evaluator.evaluate(request(step()), now=NOW)["decision"], "ALLOW")

    def test_expiry_capped_by_manifest_grant(self):
        self.gh.files[MAIN_SHA] = manifest(expires="2026-10-23T12:10:00Z")
        grants, _ = self.issuer.issue_for_plan("T-1", [step()])
        self.assertEqual(grants[0]["expires_at"], "2026-10-23T12:10:00+00:00")

    def test_one_unpermitted_step_issues_nothing(self):
        plan = [step(), step("S-2", resource="file:docs/b.txt")]
        with self.assertRaisesRegex(MAEPError, "S-2 not permitted"):
            self.issuer.issue_for_plan("T-1", plan)
        self.assertEqual(self.evaluator.evaluate(request(plan[0]), now=NOW)["decision"], "DENY")

    def test_action_not_in_manifest_issues_nothing(self):
        with self.assertRaises(MAEPError):
            self.issuer.issue_for_plan("T-1", [step(action="DELETE")])

    def test_unavailable_trust_root_issues_nothing(self):
        self.gh.files = {}
        with self.assertRaisesRegex(MAEPError, "trust root unavailable"):
            self.issuer.issue_for_plan("T-1", [step()])

    def test_only_the_claimed_issuer_adds_grants(self):
        with self.assertRaisesRegex(MAEPError, "already claimed"):
            TaskGrantIssuer(self.source, self.evaluator, principal="STT", clock=self.clock)
        with self.assertRaisesRegex(MAEPError, "claimed issuer"):
            self.evaluator._add(object(), [])

    def test_authorization_id_cannot_move_to_another_task(self):
        self.issuer.issue_for_plan("T-1", [step()])
        with self.assertRaisesRegex(MAEPError, "another task"):
            self.issuer.issue_for_plan("T-2", [dict(step(), authorization_id="T-1/S-1")])

    def test_issued_grant_does_not_cover_another_principal_or_task(self):
        self.issuer.issue_for_plan("T-1", [step()])
        self.assertEqual(self.evaluator.evaluate(request(step(), principal="intruder"), now=NOW)["decision"], "DENY")
        self.assertEqual(self.evaluator.evaluate(request(step(), task="T-9"), now=NOW)["decision"], "DENY")

    def test_bad_configuration_rejected(self):
        with self.assertRaises(MAEPError):
            TaskGrantIssuer(self.source, IssuedGrantEvaluator(), principal="STT", ttl_s=10)
        with self.assertRaises(MAEPError):
            TaskGrantIssuer(self.source, object(), principal="STT")


if __name__ == "__main__":
    unittest.main()
