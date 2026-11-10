"""WS-04 / RT-06 trust-root read oracle: ambiguous inputs on the trust-root path must deny.

Each case gives the canonical manifest source or `authorize` an input that is ambiguous or
non-canonical, and asserts it is refused rather than read in the permissive way:

* a resource whose path has dot segments ("file:out/../x", also percent-encoded),
  a backslash or control/whitespace characters is not "inside" a scope by string prefix;
* a GitHub API response that repeats a JSON key is refused, not read last-value-wins;
* manifest content with bytes outside the base64 alphabet (other than line breaks) is refused;
* a cached manifest is reloaded when the clock moves backwards, so `max_age_s` stays an
  upper bound on how long a revoked grant is honoured.
"""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone

from maep.authority.canonical_source import API_ROOT, CanonicalManifest, load_canonical_manifest
from maep.authority.trust_anchor import MANIFEST_PATH, TrustAnchorError, authorize, load_manifest
from maep.tests.test_canonical_source import MAIN_SHA, FakeGitHub, manifest

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
CONTENTS_URL = f"{API_ROOT}/repos/OAI-GIANG/HG/contents/{MANIFEST_PATH}?ref={MAIN_SHA}"
COMMIT_URL = f"{API_ROOT}/repos/OAI-GIANG/HG/commits/main"


def doc(scope=("file:out/", "repo:OAI-GIANG/HG", "url:https://example.org/docs/")):
    return load_manifest(lambda _p: (200, json.dumps(manifest(scope=scope))))


class ResourceCanonicalFormTests(unittest.TestCase):
    def allow(self, resource):
        return authorize(doc(), principal="STT", action="maep.write", resource=resource,
                         policy_version="MAEP-1.1.0", now=NOW)

    def test_controls_inside_scope_still_allow(self):
        for resource in ("file:out/", "file:out/a.txt", "file:out/dir/b.md", "file:out/.hidden",
                         "file:out/a..b", "repo:OAI-GIANG/HG", "repo:OAI-GIANG/HG/maep/core.py",
                         "url:https://example.org/docs/page?q=a/../b"):
            with self.subTest(resource=resource):
                self.assertEqual(self.allow(resource)["principal"], "STT")

    def test_non_canonical_resources_are_refused_even_when_the_prefix_matches(self):
        for resource in ("file:out/../escaped.txt", "file:out/./a.txt", "file:out/x/..", "file:out/..",
                         "repo:OAI-GIANG/HG/../HG2", "repo:OAI-GIANG/HG/%2e%2e/HG2",
                         "file:out/%2E%2e/x", "file:out/%2e/x", "url:https://example.org/docs/../admin",
                         "url:https://example.org/docs/%2e%2e/admin", "file:out/a\\..\\b",
                         "file:out/a\nb", "file:out/a b", "file:out/a\x00b", "file:out/a\tb"):
            with self.subTest(resource=resource):
                with self.assertRaisesRegex(TrustAnchorError, "not in canonical form"):
                    self.allow(resource)


class GitHubResponseTests(unittest.TestCase):
    def serve(self, overrides):
        gh = FakeGitHub()

        def get(url):
            if url in overrides:
                gh.urls.append(url)
                return 200, overrides[url]
            return gh.get(url)
        return get

    def contents(self, content, extra=""):
        return ('{"type": "file", "path": "%s", "encoding": "base64", "sha": "%s", "content": "%s"%s}'
                % (MANIFEST_PATH, "c" * 40, content, extra))

    def test_control_well_formed_responses_load(self):
        raw = base64.b64encode(json.dumps(manifest()).encode()).decode()
        wrapped = "\\n".join(raw[i:i + 60] for i in range(0, len(raw), 60)) + "\\n"   # GitHub wraps at 60
        loaded, provenance = load_canonical_manifest(self.serve({CONTENTS_URL: self.contents(wrapped)}))
        self.assertEqual(provenance["commit"], MAIN_SHA)
        self.assertEqual(loaded["grants"][0]["principal"], "STT")

    def test_duplicate_key_in_commit_response_is_refused(self):
        body = '{"sha": "%s", "sha": "%s"}' % ("d" * 40, MAIN_SHA)
        with self.assertRaisesRegex(TrustAnchorError, "duplicate key"):
            load_canonical_manifest(self.serve({COMMIT_URL: body}))

    def test_duplicate_key_in_contents_response_is_refused(self):
        good = base64.b64encode(json.dumps(manifest()).encode()).decode()
        other = base64.b64encode(json.dumps(manifest(principal="OTHER")).encode()).decode()
        body = self.contents(other, extra=', "content": "%s"' % good)
        with self.assertRaisesRegex(TrustAnchorError, "duplicate key"):
            load_canonical_manifest(self.serve({CONTENTS_URL: body}))

    def test_content_outside_the_base64_alphabet_is_refused(self):
        raw = base64.b64encode(json.dumps(manifest()).encode()).decode()
        for bad in (raw[:20] + "*" + raw[20:], raw[:20] + "!!" + raw[20:], raw[:-4] + "====", raw[:-1]):
            with self.subTest(bad=bad[15:30]):
                with self.assertRaisesRegex(TrustAnchorError, "cannot be decoded"):
                    load_canonical_manifest(self.serve({CONTENTS_URL: self.contents(bad)}))


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class CacheClockTests(unittest.TestCase):
    def test_clock_moving_backwards_forces_a_reload(self):
        gh, clock = FakeGitHub(), Clock()
        source = CanonicalManifest.from_github(http_get=gh.get, max_age_s=60, clock=clock)
        source.current()
        gh.files = {}                                  # grant revoked on main
        clock.now -= timedelta(hours=1)                # clock stepped back (e.g. time sync)
        with self.assertRaises(TrustAnchorError):
            source.current()

    def test_control_cache_still_used_within_max_age(self):
        gh, clock = FakeGitHub(), Clock()
        source = CanonicalManifest.from_github(http_get=gh.get, max_age_s=60, clock=clock)
        source.current()
        clock.now += timedelta(seconds=59)
        source.current()
        self.assertEqual(len(gh.urls), 2)


if __name__ == "__main__":
    unittest.main()
