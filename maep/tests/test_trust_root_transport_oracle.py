"""WS-04 / RT-06 trust-root transport oracle: the production GitHub reader must be bounded.

`urllib_get` is the only production route to the trust root (`CanonicalManifest.from_github`).
These cases serve exact bytes from a real loopback HTTP server and assert that the reader:

* refuses a body larger than `HTTP_MAX_BODY` instead of reading it to EOF (declared by
  Content-Length or not);
* gives up once `HTTP_DEADLINE_S` has passed even when bytes keep trickling in under the
  per-read socket timeout (a slow drip would otherwise hold the trust-root reload forever);
* does not follow a redirect: the repository, ref and path are constants, so a 3xx is a
  different source, and the redirect target never receives the request or the token.

Each failure reaches `_get_json` as an exception or a non-200 status, so the runtime denies.
"""
import http.server
import os
import threading
import time
import unittest
from unittest import mock

from maep.authority import canonical_source
from maep.authority.canonical_source import _get_json, urllib_get
from maep.authority.trust_anchor import TrustAnchorError

FAKE_TOKEN = "ghp_test_token_not_real"
NO_PROXY_ENV = {k: "" for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                                "ALL_PROXY", "all_proxy")}


class _Server:
    """Loopback server; `routes` maps path -> callable(handler). Records every request."""

    def __init__(self, routes):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append((self.path, self.headers.get("Authorization")))
                routes.get(self.path, _not_found)(self)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _not_found(h):
    h.send_response(404)
    h.send_header("Content-Length", "0")
    h.end_headers()


def _body(data, *, length=True):
    def handle(h):
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        if length:
            h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        try:
            h.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        if not length:
            h.close_connection = True
    return handle


def _endless(h):
    h.send_response(200)
    h.send_header("Content-Type", "application/json")
    h.end_headers()
    h.close_connection = True
    chunk = b" " * 65536
    try:
        h.wfile.write(b"{")
        for _ in range(100000):
            h.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def _drip(h):
    h.send_response(200)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", "1000")
    h.end_headers()
    try:
        for _ in range(1000):
            h.wfile.write(b" ")
            h.wfile.flush()
            time.sleep(0.2)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def _redirect(target, code):
    def handle(h):
        h.send_response(code)
        h.send_header("Location", target)
        h.send_header("Content-Length", "0")
        h.end_headers()
    return handle


class TransportOracleTests(unittest.TestCase):
    def setUp(self):
        env = dict(NO_PROXY_ENV, GITHUB_TOKEN=FAKE_TOKEN)
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.close()

    def server(self, routes):
        s = _Server(routes)
        self.servers.append(s)
        return s

    def read(self, url, limit_s=5.0):
        """Call the production reader through `_get_json`; return (outcome, elapsed)."""
        start = time.monotonic()
        try:
            outcome = _get_json(urllib_get, url, "probe")
        except TrustAnchorError as exc:
            outcome = exc
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, limit_s, f"reader did not return within {limit_s}s")
        return outcome

    # controls -----------------------------------------------------------------------
    def test_control_canonical_body_is_read(self):
        s = self.server({"/ok": _body(b'{"sha": "abc"}')})
        self.assertEqual(self.read(s.base + "/ok"), {"sha": "abc"})
        self.assertEqual(s.requests, [("/ok", f"Bearer {FAKE_TOKEN}")])

    def test_control_body_without_content_length_is_read(self):
        s = self.server({"/ok": _body(b'{"sha": "abc"}', length=False)})
        self.assertEqual(self.read(s.base + "/ok"), {"sha": "abc"})

    def test_control_not_found_denies(self):
        s = self.server({})
        out = self.read(s.base + "/missing")
        self.assertIsInstance(out, TrustAnchorError)
        self.assertIn("status=404", str(out))

    def test_control_body_at_the_limit_is_read(self):
        with mock.patch.object(canonical_source, "HTTP_MAX_BODY", 64):
            data = b'{"a": "' + b"x" * (64 - 9) + b'"}'
            self.assertEqual(len(data), 64)
            s = self.server({"/edge": _body(data)})
            self.assertIsInstance(self.read(s.base + "/edge"), dict)

    # defects ------------------------------------------------------------------------
    def test_oversized_declared_body_is_refused(self):
        with mock.patch.object(canonical_source, "HTTP_MAX_BODY", 64):
            data = b'{"a": "' + b"x" * 200 + b'"}'
            s = self.server({"/big": _body(data)})
            out = self.read(s.base + "/big")
            self.assertIsInstance(out, TrustAnchorError)
            self.assertIn("too large", str(out))

    def test_oversized_undeclared_body_is_refused(self):
        with mock.patch.object(canonical_source, "HTTP_MAX_BODY", 64):
            data = b'{"a": "' + b"x" * 200 + b'"}'
            s = self.server({"/big": _body(data, length=False)})
            out = self.read(s.base + "/big")
            self.assertIsInstance(out, TrustAnchorError)
            self.assertIn("too large", str(out))

    def test_endless_body_is_refused_without_waiting_for_eof(self):
        s = self.server({"/endless": _endless})
        out = self.read(s.base + "/endless", limit_s=10.0)
        self.assertIsInstance(out, TrustAnchorError)
        self.assertIn("too large", str(out))

    def test_slow_drip_under_the_socket_timeout_hits_the_deadline(self):
        with mock.patch.object(canonical_source, "HTTP_DEADLINE_S", 1.0):
            s = self.server({"/drip": _drip})
            out = self.read(s.base + "/drip", limit_s=4.0)
            self.assertIsInstance(out, TrustAnchorError)
            self.assertIn("deadline", str(out))

    def test_redirects_are_not_followed_and_the_token_is_not_forwarded(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                other = self.server({"/manifest": _body(b'{"sha": "attacker"}')})
                origin = self.server({"/moved": _redirect(other.base + "/manifest", code)})
                out = self.read(origin.base + "/moved")
                self.assertIsInstance(out, TrustAnchorError)
                self.assertIn(f"status={code}", str(out))
                self.assertEqual(other.requests, [], "redirect target was contacted")


if __name__ == "__main__":
    unittest.main()
