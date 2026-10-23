"""RT-06 regression tests: one per defect found by probing the trust-anchor provider.

Each test failed against `cf366f6` (crash, wrong exception or wrongful acceptance) and
must pass after the fix. IDs match maep/spec/RT06_VALIDATION_RECORD_V1.md.
"""
import json
import unittest
from datetime import datetime, timezone

from maep.authority.trust_anchor import TrustAnchorError, authorize, load_manifest

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
ALLOW = dict(principal="owner", action="maep.commit", resource="repo:OAI-GIANG/HG",
             policy_version="MAEP-1.1.0", now=NOW)


def grant(**over):
    g = {"principal": "owner", "actions": ["maep.commit"], "scope": ["repo:OAI-GIANG/HG"],
         "issued_at": "2026-10-22T12:00:00Z", "expires_at": "2026-11-22T12:00:00Z"}
    g.update(over)
    return g


def manifest(*grants):
    return {"trust_root": "main", "policy_version": "MAEP-1.1.0", "grants": list(grants) or [grant()]}


def load(doc=None, raw=None):
    body = raw if raw is not None else json.dumps(doc if doc is not None else manifest())
    return load_manifest(lambda _path: (200, body))


class ManifestValidationDefects(unittest.TestCase):
    def test_f1_non_string_scope_entry_is_a_denial_not_a_crash(self):
        with self.assertRaisesRegex(TrustAnchorError, "scope"):
            load(manifest(grant(scope=[123])))

    def test_f2_empty_scope_entry_rejected(self):
        # Before: scope [""] authorized any resource starting with "/" (e.g. "/etc/passwd").
        with self.assertRaisesRegex(TrustAnchorError, "scope"):
            load(manifest(grant(scope=[""])))

    def test_f2_root_like_scope_entry_rejected(self):
        with self.assertRaisesRegex(TrustAnchorError, "scope"):
            load(manifest(grant(scope=["/"])))

    def test_f3_naive_manifest_timestamps_rejected_at_load(self):
        with self.assertRaisesRegex(TrustAnchorError, "timezone"):
            load(manifest(grant(issued_at="2026-10-22T12:00:00", expires_at="2026-11-22T12:00:00")))

    def test_f4_inverted_validity_window_rejected(self):
        with self.assertRaisesRegex(TrustAnchorError, "expires_at"):
            load(manifest(grant(issued_at="2026-12-01T00:00:00Z")))

    def test_f5_unsupported_action_rejected(self):
        with self.assertRaisesRegex(TrustAnchorError, "unsupported action"):
            load(manifest(grant(actions=["rm -rf"])))

    def test_f5_action_vocabulary_is_maep_actions(self):
        for action in ("maep.read", "maep.write", "maep.commit", "maep.push", "maep.merge",
                       "maep.deploy", "maep.migrate", "maep.delete", "maep.execute"):
            load(manifest(grant(actions=[action])))

    def test_f6_non_string_principal_rejected(self):
        with self.assertRaisesRegex(TrustAnchorError, "principal"):
            load(manifest(grant(principal=["owner"])))

    def test_f10_duplicate_json_keys_rejected(self):
        raw = ('{"trust_root":"main","policy_version":"MAEP-1.1.0","grants":[{"principal":"owner",'
               '"actions":["maep.commit"],"scope":["repo:OAI-GIANG/HG"],"issued_at":"2026-10-22T12:00:00Z",'
               '"expires_at":"2026-11-22T12:00:00Z","principal":"attacker"}]}')
        with self.assertRaisesRegex(TrustAnchorError, "duplicate key"):
            load(raw=raw)

    def test_f10_duplicate_top_level_key_rejected(self):
        raw = '{"trust_root":"rt06/x","trust_root":"main","policy_version":"MAEP-1.1.0","grants":[]}'
        with self.assertRaisesRegex(TrustAnchorError, "duplicate key"):
            load(raw=raw)

    def test_non_dict_grant_fields_never_crash(self):
        for bad in (grant(actions="maep.commit"), grant(scope="repo:OAI-GIANG/HG"),
                    grant(issued_at=20261022), grant(expires_at=None)):
            with self.assertRaises(TrustAnchorError):
                load(manifest(bad))


class AuthorizeDefects(unittest.TestCase):
    def test_f7_future_renewal_does_not_block_a_live_grant(self):
        renewal = grant(issued_at="2026-11-20T00:00:00Z", expires_at="2026-12-31T00:00:00Z")
        self.assertEqual(authorize(load(manifest(grant(), renewal)), **ALLOW)["issued_at"], "2026-10-22T12:00:00Z")

    def test_f7_only_future_grant_is_still_denied(self):
        future = grant(issued_at="2026-11-20T00:00:00Z", expires_at="2026-12-31T00:00:00Z")
        with self.assertRaisesRegex(TrustAnchorError, "no live grant"):
            authorize(load(manifest(future)), **ALLOW)

    def test_f7_two_live_grants_still_ambiguous(self):
        with self.assertRaisesRegex(TrustAnchorError, "ambiguous"):
            authorize(load(manifest(grant(), grant(expires_at="2026-12-01T00:00:00Z"))), **ALLOW)

    def test_f9_naive_now_is_a_denial(self):
        with self.assertRaisesRegex(TrustAnchorError, "timezone"):
            authorize(load(), **dict(ALLOW, now=datetime(2026, 10, 23, 12)))

    def test_f11_returned_grant_cannot_widen_the_loaded_manifest(self):
        doc = load()
        authorize(doc, **ALLOW)["scope"].append("repo:EVIL/X")
        with self.assertRaises(TrustAnchorError):
            authorize(doc, **dict(ALLOW, resource="repo:EVIL/X"))

    def test_f11_loaded_manifest_is_detached_from_fetched_object(self):
        source = manifest()
        doc = load(source)
        source["grants"][0]["scope"].append("repo:EVIL/X")
        with self.assertRaises(TrustAnchorError):
            authorize(doc, **dict(ALLOW, resource="repo:EVIL/X"))

    def test_prefix_confusion_denied(self):
        for resource in ("repo:OAI-GIANG/HG2", "repo:OAI-GIANG/HGx/a", "repo:OAI-GIANG", "repo:oai-giang/hg"):
            with self.assertRaises(TrustAnchorError, msg=resource):
                authorize(load(), **dict(ALLOW, resource=resource))

    def test_child_resource_allowed(self):
        self.assertTrue(authorize(load(), **dict(ALLOW, resource="repo:OAI-GIANG/HG/maep/core.py")))


if __name__ == "__main__":
    unittest.main()
