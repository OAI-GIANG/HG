"""WS-04 oracle: url.read answers only for the URL the gateway authorized and scope-checked.

The gateway authorizes `url:<canonical url>` and checks it against the task scope (and, when
anchored, the owner manifest). A redirect names a different URL that was never authorized:
following it would read out of scope (another path, another host, a link-local metadata
address) and return that body as the in-scope result. Each redirect must end as a known
failure, with no request sent to the target and no redirected content in any outcome.

Controls: an in-scope 200 still closes CLOSED_VERIFIED; a 404 stays a known failure.
A real loopback HTTP server serves exact responses.
"""
import http.server
import threading
import itertools
import time

from hg.tests.support import make_task
from hg.tests.test_tools_research import ToolBase

SECRET = b"OUT-OF-SCOPE BODY"
PAGE = b"HG research page. timeout = 30"


def _server(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _handler(log, routes):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            log.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b"no"))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


class UrlReadRedirectOracle(ToolBase):
    def setUp(self):
        super().setUp()
        self.log, self.other_log = [], []
        self.other = _server(_handler(self.other_log, {
            "/secret": (200, {"Content-Type": "text/plain"}, SECRET)}))
        self.other_base = f"http://127.0.0.1:{self.other.server_port}/"
        self.routes = {"/docs/page": (200, {"Content-Type": "text/plain"}, PAGE),
                       "/secret": (200, {"Content-Type": "text/plain"}, SECRET)}
        self.server = _server(_handler(self.log, self.routes))
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def tearDown(self):
        for server in (self.server, self.other):
            server.shutdown()
            server.server_close()
        super().tearDown()

    _ids = itertools.count(1)

    def task(self):
        task = make_task(task_id=f"T-{next(self._ids)}")  # one runtime, one task per fetch
        task["scope"]["include"] = [self.base + "docs/"]
        return task

    def fetch(self, path):
        seen = []

        def verifier(snapshot):
            seen.extend(snapshot["outcomes"])
            return True, ""
        started = time.monotonic()
        rt, final = self.run_goal({"operations": [{"op": "fetch", "url": self.base + path}]},
                                  task=self.task(), verifiers={"AC-1": verifier})
        self.assertLess(time.monotonic() - started, 10)
        return rt, final, seen

    def assert_no_secret(self, rt, seen):
        for outcome in seen:
            self.assertNotIn(SECRET.decode(), repr(outcome))
        for event in rt.actions.events("ACTION_COMPLETED"):
            self.assertNotIn(SECRET.decode(), repr(event))

    def test_control_in_scope_page_closes(self):
        _rt, final, seen = self.fetch("docs/page")
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertIn(PAGE.decode(), seen[0]["observed"]["text"])

    def test_control_missing_page_is_a_known_failure(self):
        _rt, final, _seen = self.fetch("docs/missing")
        self.assertEqual(final["task"]["state"], "BLOCKED")

    def test_redirect_to_out_of_scope_path_is_not_followed(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                self.log.clear()
                self.routes["/docs/go"] = (code, {"Location": "/secret"}, b"")
                rt, final, seen = self.fetch("docs/go")
                self.assertNotIn("/secret", self.log)
                self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")
                self.assert_no_secret(rt, seen)

    def test_redirect_to_another_host_is_not_followed(self):
        for code in (302, 307):
            with self.subTest(code=code):
                self.other_log.clear()
                self.routes["/docs/away"] = (code, {"Location": self.other_base + "secret"}, b"")
                rt, final, seen = self.fetch("docs/away")
                self.assertEqual(self.other_log, [])
                self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")
                self.assert_no_secret(rt, seen)

    def test_redirect_inside_scope_is_still_not_followed(self):
        # The redirect target is a URL the gateway never authorized, even if a prefix test
        # would match it: only the authorized URL is read.
        self.log.clear()
        self.routes["/docs/moved"] = (301, {"Location": "/docs/page"}, b"")
        _rt, final, _seen = self.fetch("docs/moved")
        self.assertEqual(set(self.log), {"/docs/moved"})   # a known failure may be retried
        self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")


if __name__ == "__main__":
    import unittest
    unittest.main()
