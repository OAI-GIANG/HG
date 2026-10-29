"""Chat UI boundary of hg serve (contract revision 2026-10-29, docs/architecture/HG_SERVICE_V1.md §5).

Real loopback HTTP through HGHTTPServer:
- GET /ui/, /ui/index.html, /ui/app.js, /ui/styles.css: the web UI shipped in the release, served
  without a bearer token (static, no data, no effect) but only to a loopback Host; every other
  route still answers 401 before routing when the token is missing.
- POST /v1/chat: bearer token required; strict body {"message": str, "general": bool}; the
  answer comes from the injected chat service; errors map to honest status codes.
- The UI source itself: same-origin calls only (no 8080/18767), token only in an Authorization
  header, no localStorage, no innerHTML, no inline script/style (CSP script-src/style-src 'self').
"""
import http.client
import json
import re
import threading
import unittest
from pathlib import Path

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.http_api import HGHTTPServer, HTTPBoundaryError, planned_write_readback_verifier
from hg.runtime import build_runtime
from hg.tests.support import TempDirMixin

TOKEN = b"test-token-that-is-long-enough-for-the-boundary"
UI_DIR = Path(__file__).resolve().parents[1] / "ui"


class FakeChat:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def __call__(self, message, *, general):
        self.calls.append((message, general))
        if self.error is not None:
            raise self.error
        return self.result or {"outcome": "ANSWERED", "answer": "Xin chào.",
                               "sentences": [{"sentence": "Xin chào.", "label": "MODEL", "note": None}]}


class ChatHTTPBase(TempDirMixin):
    chat = None

    def setUp(self):
        super().setUp()
        gh = FakeGitHub()
        authority = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0, clock=self.clock)
        self.runtime = build_runtime(self.workdir, [], authority=authority, issue_task_grants=True,
                                     clock=self.clock,
                                     verifiers={"AC-READBACK": planned_write_readback_verifier(self.root)})
        self.release = {"result": "VERIFIED", "release_id": "a" * 64}
        self.trust = {"result": "LOADED", "provenance": {"commit": "b" * 40}}
        self.fake_chat = self.make_chat()
        self.server = HGHTTPServer(
            runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0, max_body_bytes=4096,
            release_report=lambda: self.release, trust_report=lambda: self.trust,
            idempotency_path=self.workdir / "http-idempotency.sqlite3", chat=self.fake_chat)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.address

    def make_chat(self):
        return FakeChat()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        super().tearDown()

    def raw_request(self, method, path, *, body=None, raw=None, token=True, headers=None,
                    content_type="application/json"):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        out = dict(headers or {})
        if token:
            out["Authorization"] = "Bearer " + TOKEN.decode()
        if body is not None:
            raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        if raw is not None:
            out.setdefault("Content-Type", content_type)
            out.setdefault("Content-Length", str(len(raw)))
        conn.request(method, path, body=raw, headers=out)
        response = conn.getresponse()
        result = (response.status, {k.lower(): v for k, v in response.getheaders()}, response.read())
        conn.close()
        return result

    def request(self, method, path, **kw):
        status, _headers, payload = self.raw_request(method, path, **kw)
        try:
            return status, json.loads(payload.decode("utf-8"))
        except ValueError:
            return status, payload.decode("utf-8", "replace")


class StaticUITests(ChatHTTPBase):
    def test_ui_index_is_served_without_token_with_strict_headers(self):
        for path in ("/ui/", "/ui/index.html"):
            status, headers, body = self.raw_request("GET", path, token=False)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
            self.assertEqual(body, (UI_DIR / "index.html").read_bytes())
            csp = headers["content-security-policy"]
            for directive in ("default-src 'none'", "script-src 'self'", "style-src 'self'",
                              "connect-src 'self'", "frame-ancestors 'none'", "base-uri 'none'",
                              "form-action 'none'"):
                self.assertIn(directive, csp)
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertEqual(headers["referrer-policy"], "no-referrer")
            self.assertEqual(headers["cache-control"], "no-store")

    def test_ui_script_and_style_have_their_own_types(self):
        status, headers, body = self.raw_request("GET", "/ui/app.js", token=False)
        self.assertEqual((status, headers["content-type"]), (200, "text/javascript; charset=utf-8"))
        self.assertEqual(body, (UI_DIR / "app.js").read_bytes())
        status, headers, body = self.raw_request("GET", "/ui/styles.css", token=False)
        self.assertEqual((status, headers["content-type"]), (200, "text/css; charset=utf-8"))
        self.assertEqual(body, (UI_DIR / "styles.css").read_bytes())

    def test_only_the_exact_ui_files_skip_the_token(self):
        for path in ("/ui", "/ui/../hg/service.py", "/ui/%2e%2e/service.py", "/ui/app.js?x=1",
                     "/ui/secret.json", "/", "/index.html", "/v1/chat", "/ui/tests/x"):
            status, body = self.request("GET", path, token=False)
            self.assertEqual((status, body["error"]), (401, "unauthorized"), path)

    def test_unknown_ui_path_with_token_is_not_found(self):
        status, body = self.request("GET", "/ui/secret.json")
        self.assertEqual((status, body["error"]), (404, "not_found"))

    def test_ui_still_requires_a_loopback_host(self):
        status, body = self.request("GET", "/ui/", token=False, headers={"Host": "attacker.example"})
        self.assertEqual((status, body["error"]), (400, "invalid_host"))
        status, body = self.request("GET", "/ui/", token=False, headers={"Host": "127.0.0.1:1"})
        self.assertEqual((status, body["error"]), (400, "invalid_host"))

    def test_ui_is_get_only(self):
        status, body = self.request("POST", "/ui/", token=False, body={})
        self.assertEqual((status, body["error"]), (401, "unauthorized"))
        status, body = self.request("POST", "/ui/", body={})
        self.assertEqual((status, body["error"]), (404, "not_found"))

    def test_existing_routes_still_require_the_token(self):
        for path in ("/v1/health/live", "/v1/health/ready", "/v1/integrity", "/v1/tasks/T-1"):
            self.assertEqual(self.request("GET", path, token=False)[0], 401, path)


class ChatRouteTests(ChatHTTPBase):
    def test_chat_requires_the_token(self):
        status, body = self.request("POST", "/v1/chat", token=False, body={"message": "xin chào", "general": True})
        self.assertEqual((status, body["error"]), (401, "unauthorized"))
        self.assertEqual(self.fake_chat.calls, [])

    def test_chat_answers_with_the_chat_service_result(self):
        status, body = self.request("POST", "/v1/chat", body={"message": "  Thủ đô của Pháp?  ", "general": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "ANSWERED")
        self.assertEqual(body["sentences"][0]["label"], "MODEL")
        self.assertEqual(self.fake_chat.calls, [("Thủ đô của Pháp?", True)])

    def test_chat_body_must_be_exact(self):
        bad = [{"message": "x"}, {"general": True}, {"message": "x", "general": True, "provider": "anthropic"},
               {"message": "x", "general": 1}, {"message": "x", "general": "true"}, {"message": 5, "general": True},
               {"message": "   ", "general": False}, {"message": "x" * 2001, "general": False}, ["x"]]
        for body in bad:
            status, payload = self.request("POST", "/v1/chat", body=body)
            self.assertEqual(status, 400, body)
            self.assertIn(payload["error"], {"invalid_request", "invalid_message"}, body)
        self.assertEqual(self.fake_chat.calls, [])

    def test_chat_content_type_and_size_limits(self):
        status, body = self.request("POST", "/v1/chat", raw=b'{"message":"x","general":true}',
                                    content_type="text/plain")
        self.assertEqual((status, body["error"]), (415, "content_type"))
        status, body = self.request("POST", "/v1/chat", raw=b"{" + b" " * 5000 + b"}")
        self.assertEqual((status, body["error"]), (413, "body_too_large"))
        status, body = self.request("POST", "/v1/chat", raw=b'{"message":"x","general":true,"general":false}')
        self.assertEqual((status, body["error"]), (400, "invalid_json"))

    def test_chat_needs_a_verified_release_but_not_canonical_authority(self):
        self.trust = {"result": "BLOCKED"}
        self.assertEqual(self.request("POST", "/v1/chat", body={"message": "a", "general": True})[0], 200)
        self.release = {"result": "FAILED"}
        status, body = self.request("POST", "/v1/chat", body={"message": "a", "general": True})
        self.assertEqual((status, body["error"]), (503, "service_not_ready"))

    def test_chat_route_is_post_only(self):
        status, body = self.request("GET", "/v1/chat")
        self.assertEqual((status, body["error"]), (404, "not_found"))
        status, body = self.request("PUT", "/v1/chat", body={})
        self.assertEqual((status, body["error"]), (405, "method_not_allowed"))

    def test_tasks_route_is_unchanged(self):
        status, body = self.request("POST", "/v1/tasks", body={"task": {}, "steps": []})
        self.assertEqual((status, body["error"]), (400, "idempotency_key"))


class ChatErrorMappingTests(ChatHTTPBase):
    def make_chat(self):
        return FakeChat(error=HTTPBoundaryError(503, "chat_busy", "another chat is being answered"))

    def test_chat_service_errors_keep_their_status_and_code(self):
        status, body = self.request("POST", "/v1/chat", body={"message": "a", "general": True})
        self.assertEqual((status, body["error"]), (503, "chat_busy"))

    def test_unexpected_chat_failure_is_an_internal_error_without_detail(self):
        self.fake_chat.error = RuntimeError("secret prompt text")
        status, body = self.request("POST", "/v1/chat", body={"message": "a", "general": True})
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "internal_error"})


class ChatNotConfiguredTests(ChatHTTPBase):
    def make_chat(self):
        return None

    def test_chat_without_a_chat_service_is_unavailable(self):
        status, body = self.request("POST", "/v1/chat", body={"message": "a", "general": True})
        self.assertEqual((status, body["error"]), (503, "chat_unavailable"))


class UISourceContractTests(unittest.TestCase):
    """The shipped UI talks only to its own origin, with the token only in an Authorization header."""

    @classmethod
    def setUpClass(cls):
        cls.html = (UI_DIR / "index.html").read_text(encoding="utf-8")
        cls.js = (UI_DIR / "app.js").read_text(encoding="utf-8")
        cls.css = (UI_DIR / "styles.css").read_text(encoding="utf-8")

    def test_no_stale_or_absolute_endpoints(self):
        for text in (self.html, self.js, self.css):
            for stale in ("8080", "18767", "127.0.0.1", "localhost", "/api/dispatch", "/api/tasks",
                          "'/health'", "http://", "https://"):
                self.assertNotIn(stale, text)

    def test_calls_only_contract_routes_on_its_own_origin(self):
        routes = set(re.findall(r"""['"](/v1/[A-Za-z0-9/_.:-]*)""", self.js))
        self.assertEqual(routes, {"/v1/chat", "/v1/health/ready", "/v1/tasks/"})
        self.assertIn("'Authorization'", self.js)
        self.assertIn("'Bearer '", self.js)
        self.assertIn("credentials: 'omit'", self.js)
        self.assertIn("cache: 'no-store'", self.js)

    def test_token_never_in_local_storage_or_url(self):
        self.assertNotIn("localStorage", self.js)
        self.assertNotIn("location.hash", self.js)
        self.assertNotIn("URLSearchParams", self.js)
        self.assertNotIn("?token", self.js)

    def test_no_html_injection_sinks(self):
        for sink in (".innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, self.js)
        self.assertIn(".textContent", self.js)

    def test_csp_compatible_markup(self):
        self.assertNotRegex(self.html, r"\sstyle\s*=")
        self.assertNotRegex(self.html, r"\son[a-z]+\s*=")
        self.assertEqual(re.findall(r"<script\b[^>]*>", self.html), ['<script src="app.js">'])
        self.assertEqual(re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", self.html), [""])
        self.assertEqual(re.findall(r"<link\b[^>]*>", self.html), ['<link rel="stylesheet" href="styles.css" />'])

    def test_enter_inserts_a_newline_and_only_the_button_sends(self):
        self.assertIn("e.key === 'Enter'", self.js)
        self.assertNotRegex(self.js, r"keydown[\s\S]{0,200}sendChat\(")

    def test_screens_and_root_navigation(self):
        for screen in ("home", "chat", "tasks", "settings"):
            self.assertIn(f'id="screen-{screen}"', self.html)
        for root in ("home", "chat", "quick-actions", "files", "tools"):
            self.assertIn(f'data-root-nav="{root}"', self.html)


if __name__ == "__main__":
    unittest.main()
