"""RT-06: canonical manifest source and AnchoredPolicyEvaluator (fail-closed, main-only)."""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone

from maep.authority.anchored import AnchoredPolicyEvaluator
from maep.authority.canonical_source import API_ROOT, CanonicalManifest, load_canonical_manifest
from maep.authority.trust_anchor import MANIFEST_PATH, TrustAnchorError
from maep.policy import PolicyEvaluator

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
MAIN_SHA = "a" * 40
FEATURE_SHA = "b" * 40


def manifest(principal="STT", actions=("maep.write",), scope=("file:out/",), expires="2026-11-22T12:00:00Z"):
    return {"trust_root": "main", "policy_version": "MAEP-1.1.0", "grants": [{
        "principal": principal, "actions": list(actions), "scope": list(scope),
        "issued_at": "2026-10-22T12:00:00Z", "expires_at": expires}]}


class FakeGitHub:
    """Serves commits by ref and manifest files by commit, like the GitHub REST API."""

    def __init__(self, refs=None, files=None):
        self.refs = refs if refs is not None else {"main": MAIN_SHA}
        self.files = files if files is not None else {MAIN_SHA: manifest()}
        self.urls = []
        self.raise_on = None

    def get(self, url):
        self.urls.append(url)
        if self.raise_on and self.raise_on in url:
            raise OSError("connection reset")
        prefix = f"{API_ROOT}/repos/OAI-GIANG/HG/"
        if not url.startswith(prefix):
            return 404, ""
        tail = url[len(prefix):]
        if tail.startswith("commits/"):
            sha = self.refs.get(tail[len("commits/"):])
            return (200, json.dumps({"sha": sha})) if sha else (404, "")
        if tail.startswith(f"contents/{MANIFEST_PATH}?ref="):
            doc = self.files.get(tail.split("?ref=", 1)[1])
            if doc is None:
                return 404, ""
            raw = doc if isinstance(doc, str) else json.dumps(doc)
            return 200, json.dumps({"type": "file", "path": MANIFEST_PATH, "encoding": "base64", "sha": "c" * 40,
                                    "content": base64.b64encode(raw.encode()).decode()})
        return 404, ""


class LoaderTests(unittest.TestCase):
    def test_reads_main_pinned_to_the_resolved_commit(self):
        gh = FakeGitHub()
        doc, prov = load_canonical_manifest(gh.get)
        self.assertEqual(gh.urls, [f"{API_ROOT}/repos/OAI-GIANG/HG/commits/main",
                                   f"{API_ROOT}/repos/OAI-GIANG/HG/contents/{MANIFEST_PATH}?ref={MAIN_SHA}"])
        self.assertEqual((prov["commit"], prov["ref"], prov["repo"]), (MAIN_SHA, "main", "OAI-GIANG/HG"))
        self.assertEqual(doc["grants"][0]["principal"], "STT")

    def test_feature_branch_manifest_is_never_read(self):
        gh = FakeGitHub(refs={"main": MAIN_SHA, "rt06/x": FEATURE_SHA}, files={FEATURE_SHA: manifest()})
        with self.assertRaisesRegex(TrustAnchorError, "status=404"):
            load_canonical_manifest(gh.get)
        self.assertFalse(any(FEATURE_SHA in u or "rt06" in u for u in gh.urls))

    def test_missing_manifest_denies(self):
        with self.assertRaisesRegex(TrustAnchorError, "status=404"):
            load_canonical_manifest(FakeGitHub(files={}).get)

    def test_unresolvable_main_denies(self):
        with self.assertRaisesRegex(TrustAnchorError, "unavailable"):
            load_canonical_manifest(FakeGitHub(refs={}).get)

    def test_malformed_commit_sha_denies(self):
        gh = FakeGitHub(refs={"main": "../../evil"})
        with self.assertRaisesRegex(TrustAnchorError, "commit SHA"):
            load_canonical_manifest(gh.get)

    def test_transport_failure_denies(self):
        gh = FakeGitHub()
        gh.raise_on = "contents/"
        with self.assertRaisesRegex(TrustAnchorError, "transport failure"):
            load_canonical_manifest(gh.get)

    def test_invalid_manifest_denies(self):
        for bad in ("not json", json.dumps({"trust_root": "main"}), json.dumps(manifest(scope=("",)))):
            with self.assertRaises(TrustAnchorError):
                load_canonical_manifest(FakeGitHub(files={MAIN_SHA: bad}).get)

    def test_directory_or_wrong_path_denies(self):
        gh = FakeGitHub()
        real = gh.get

        def as_dir(url):
            status, body = real(url)
            if "contents/" in url and status == 200:
                data = json.loads(body)
                data["type"] = "dir"
                return 200, json.dumps(data)
            return status, body
        with self.assertRaisesRegex(TrustAnchorError, "file"):
            load_canonical_manifest(as_dir)

    def test_non_json_api_response_denies(self):
        with self.assertRaisesRegex(TrustAnchorError, "not valid JSON"):
            load_canonical_manifest(lambda url: (200, "<html>"))


class ClockStub:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class CanonicalManifestTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.clock = ClockStub()
        self.source = CanonicalManifest.from_github(http_get=self.gh.get, max_age_s=60, clock=self.clock)

    def test_cached_within_max_age(self):
        self.source.current()
        self.source.current()
        self.assertEqual(len(self.gh.urls), 2)

    def test_reloaded_after_max_age(self):
        self.source.current()
        self.clock.now += timedelta(seconds=61)
        self.source.current()
        self.assertEqual(len(self.gh.urls), 4)

    def test_failed_reload_does_not_fall_back_to_stale_document(self):
        self.source.current()
        self.gh.files = {}
        self.clock.now += timedelta(seconds=61)
        with self.assertRaises(TrustAnchorError):
            self.source.current()
        with self.assertRaises(TrustAnchorError):     # still denied, cache was dropped
            self.source.current()

    def test_loader_crash_is_a_trust_anchor_error(self):
        def broken():
            raise KeyError("x")
        with self.assertRaisesRegex(TrustAnchorError, "loader failed"):
            CanonicalManifest(broken).current()

    def test_bad_configuration_rejected(self):
        for kwargs in ({"max_age_s": -1}, {"max_age_s": True}):
            with self.assertRaises(TrustAnchorError):
                CanonicalManifest(lambda: None, **kwargs)
        with self.assertRaises(TrustAnchorError):
            CanonicalManifest("not callable")


def pe_grant(**over):
    g = {"authorization_id": "AUTH-1", "principal": "STT", "action": "WRITE", "resource": "file:out/a.txt",
         "scope": ["out/"], "conditions": [], "task_id": "T-1", "policy_version": "MAEP-1.1.0",
         "decision": "ALLOW", "issued_at": "2026-10-23T11:00:00+00:00", "expires_at": "2026-10-23T13:00:00+00:00"}
    g.update(over)
    return g


def request(**over):
    r = {"authorization_id": "AUTH-1", "principal": "STT", "action": "WRITE", "resource": "file:out/a.txt",
         "scope": ["out/"], "task_id": "T-1", "policy_version": "MAEP-1.1.0"}
    r.update(over)
    return r


class AnchoredEvaluatorTests(unittest.TestCase):
    def evaluator(self, doc=None, grants=None, gh=None):
        gh = gh or FakeGitHub(files={MAIN_SHA: doc or manifest()})
        source = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0, clock=ClockStub())
        inner = PolicyEvaluator(grants if grants is not None else [pe_grant()], lambda c, r: False)
        return AnchoredPolicyEvaluator(inner, source), gh

    def test_both_checks_pass_allows_and_records_anchor(self):
        ev, _gh = self.evaluator()
        decision = ev.evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "ALLOW")
        self.assertEqual(decision["anchor"]["commit"], MAIN_SHA)

    def test_task_grant_without_manifest_grant_denied(self):
        ev, _gh = self.evaluator(doc=manifest(principal="owner"))
        decision = ev.evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "DENY")
        self.assertIn("trust anchor", decision["reason"])

    def test_action_not_in_manifest_denied(self):
        ev, _gh = self.evaluator(doc=manifest(actions=("maep.read",)))
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")

    def test_resource_outside_manifest_scope_denied(self):
        ev, _gh = self.evaluator(doc=manifest(scope=("file:docs/",)))
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")

    def test_expired_manifest_grant_denied(self):
        ev, _gh = self.evaluator(doc=manifest(expires="2026-10-23T11:59:59Z"))
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")

    def test_manifest_unavailable_denied(self):
        ev, _gh = self.evaluator(gh=FakeGitHub(files={}))
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")

    def test_manifest_cannot_grant_without_a_task_grant(self):
        ev, gh = self.evaluator(grants=[])
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")
        self.assertEqual(gh.urls, [])                   # manifest not even consulted

    def test_caller_cannot_carry_authority_in_the_request(self):
        ev, _gh = self.evaluator(doc=manifest(principal="owner"))
        self.assertEqual(ev.evaluate(dict(request(), anchor={"commit": MAIN_SHA}), now=NOW)["decision"], "DENY")

    def test_revocation_takes_effect_on_reload(self):
        ev, gh = self.evaluator()
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "ALLOW")
        gh.files[MAIN_SHA] = manifest(principal="someone-else")
        self.assertEqual(ev.evaluate(request(), now=NOW)["decision"], "DENY")

    def test_rejects_objects_without_the_interfaces(self):
        with self.assertRaises(TrustAnchorError):
            AnchoredPolicyEvaluator(object(), CanonicalManifest(lambda: None))
        with self.assertRaises(TrustAnchorError):
            AnchoredPolicyEvaluator(PolicyEvaluator([], lambda c, r: False), object())


if __name__ == "__main__":
    unittest.main()
