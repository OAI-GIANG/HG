"""Fixture-only validation of the proposed HG_AUDIT least-privilege grant.

This test does not change or simulate a change to the canonical owner-grants manifest.
"""
import json
import unittest
from datetime import datetime, timezone

from maep.authority.trust_anchor import TrustAnchorError, authorize, load_manifest

NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
PROPOSED_GRANT = {
    "principal": "HG_AUDIT",
    "actions": ["maep.read"],
    "scope": [
        "repo:OAI-GIANG/HG",
        "file:docs/architecture/",
        "file:hg/",
        "file:maep/",
        "file:evidence/",
    ],
    "issued_at": "2026-10-24T00:00:00Z",
    "expires_at": "2026-10-31T00:00:00Z",
}


def proposed_manifest(grant=None):
    document = {
        "trust_root": "main",
        "policy_version": "MAEP-1.1.0",
        "grants": [dict(PROPOSED_GRANT if grant is None else grant)],
    }
    return load_manifest(
        lambda _path: (200, json.dumps(document)),
        repo="OAI-GIANG/HG",
        branch="main",
        path="maep/authority/owner-grants.json",
    )


class HGAuditMinimumGrantProposalTests(unittest.TestCase):
    def test_proposed_grant_schema_is_valid(self):
        self.assertEqual(proposed_manifest()["grants"][0]["principal"], "HG_AUDIT")

    def test_read_allowed_only_inside_proposed_scope(self):
        doc = proposed_manifest()
        self.assertEqual(
            authorize(doc, principal="HG_AUDIT", action="maep.read",
                      resource="file:docs/architecture/EXECUTION_HOST_P0_CLOSURE_ASSESSMENT_V1.md",
                      policy_version="MAEP-1.1.0", now=NOW)["actions"],
            ["maep.read"],
        )
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="HG_AUDIT", action="maep.read",
                      resource="file:out/production.db",
                      policy_version="MAEP-1.1.0", now=NOW)

    def test_write_action_is_denied(self):
        doc = proposed_manifest()
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="HG_AUDIT", action="maep.write",
                      resource="file:docs/architecture/anything.md",
                      policy_version="MAEP-1.1.0", now=NOW)

    def test_other_principal_is_denied(self):
        doc = proposed_manifest()
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="STT", action="maep.read",
                      resource="file:docs/architecture/anything.md",
                      policy_version="MAEP-1.1.0", now=NOW)

    def test_expired_grant_is_denied(self):
        grant = dict(PROPOSED_GRANT, expires_at="2026-10-24T11:59:59Z")
        doc = proposed_manifest(grant)
        with self.assertRaises(TrustAnchorError):
            authorize(doc, principal="HG_AUDIT", action="maep.read",
                      resource="file:docs/architecture/anything.md",
                      policy_version="MAEP-1.1.0", now=NOW)


if __name__ == "__main__":
    unittest.main()
