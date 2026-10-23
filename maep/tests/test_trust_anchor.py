import json
import unittest
from datetime import datetime, timedelta, timezone

from maep.authority.trust_anchor import (
    CANONICAL_BRANCH, MANIFEST_PATH, TrustAnchorError, authorize, fingerprint, load_manifest,
)

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def _doc(**over):
    doc = {
        "trust_root": "main",
        "policy_version": "MAEP-1.1.0",
        "grants": [{
            "principal": "owner",
            "actions": ["maep.commit"],
            "scope": ["repo:OAI-GIANG/HG"],
            "issued_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        }],
    }
    doc.update(over)
    return doc


def _fetch(doc=None, status=200, raw=None):
    body = raw if raw is not None else json.dumps(doc if doc is not None else _doc())
    return lambda path: (status, body)


class TrustAnchorTests(unittest.TestCase):
    def test_valid_grant_allows(self):
        doc = load_manifest(_fetch(), repo="OAI-GIANG/HG", branch=CANONICAL_BRANCH)
        self.assertTrue(authorize(doc, principal="owner", action="maep.commit",
                                  resource="repo:OAI-GIANG/HG",
                                  policy_version="MAEP-1.1.0", now=NOW))

    def test_unknown_principal_denied(self):
        doc = load_manifest(_fetch())
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="agent", action="maep.commit",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)

    def test_wrong_action_denied(self):
        doc = load_manifest(_fetch())
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="owner", action="repo.delete",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)

    def test_expired_grant_denied(self):
        d = _doc()
        d["grants"][0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        doc = load_manifest(_fetch(d))
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="owner", action="maep.commit",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)

    def test_scope_mismatch_denied(self):
        doc = load_manifest(_fetch())
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="owner", action="maep.commit",
                      resource="repo:OTHER/REPO", policy_version="MAEP-1.1.0", now=NOW)

    def test_feature_branch_never_trust_root(self):
        with self.assertRaises(TrustAnchorError):
            load_manifest(_fetch(), branch="rt06/trust-anchor-provider-20261023")

    def test_unexpected_repository_denied(self):
        with self.assertRaises(TrustAnchorError):
            load_manifest(_fetch(), repo="OAI-GIANG/OTHER")

    def test_unexpected_manifest_path_denied(self):
        with self.assertRaises(TrustAnchorError):
            load_manifest(_fetch(), path="other/owner-grants.json")

    def test_missing_manifest_denied(self):
        with self.assertRaises(TrustAnchorError):
            load_manifest(_fetch(status=404, raw=""))

    def test_transport_failure_denied(self):
        def boom(path):
            raise OSError("network down")
        with self.assertRaises(TrustAnchorError):
            load_manifest(boom)

    def test_ambiguous_grants_denied(self):
        d = _doc()
        d["grants"].append(dict(d["grants"][0]))
        doc = load_manifest(_fetch(d))
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="owner", action="maep.commit",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)

    def test_wrong_trust_root_denied(self):
        with self.assertRaises(TrustAnchorError):
            load_manifest(_fetch(_doc(trust_root="rt06/branch")))

    def test_policy_version_mismatch_denied(self):
        doc = load_manifest(_fetch())
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="owner", action="maep.commit",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.0.0", now=NOW)

    def test_fingerprint_stable(self):
        doc = load_manifest(_fetch())
        self.assertEqual(fingerprint(doc), fingerprint(json.loads(json.dumps(doc))))

    def test_naive_time_is_not_accepted_as_validity_input(self):
        doc = load_manifest(_fetch())
        with self.assertRaises(TypeError):
            authorize(doc, principal="owner", action="maep.commit",
                      resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0",
                      now=datetime(2026, 10, 23, 12, 0, 0))


if __name__ == "__main__":
    unittest.main()
