"""WS-04 oracle: url.read returns the body it received, exactly and whole, or a known failure.

`url.read` outcomes carry the body's `sha256`/`bytes` and, for a text response, its `text`.
That text must be the exact text of those bytes, and those bytes must be the whole body the
server sent: a body that is not valid UTF-8 (or declares another charset) must not be
returned as a "repaired" text (U+FFFD) under the digest of the original bytes; a body cut
short (fewer bytes than Content-Length, or a broken chunked stream) or larger than the
adapter bound must not be returned as if it were the document; and a server that drips its
body must not hold the task past the adapter's time budget. None of these may close the
task CLOSED_VERIFIED.

Each case runs a real `url.read` task through BrainOrchestrator -> ActionGateway -> adapter
against a loopback server that writes exact bytes. Controls: UTF-8 non-ASCII, CRLF, an
upper-case media type with `charset=UTF-8`, an empty body, a body of exactly the bound, a
chunked body and a binary body close CLOSED_VERIFIED with byte-exact results.
"""
import hashlib
import itertools
import socketserver
import threading
import time
import tracemalloc
from unittest import mock

from hg.tests.support import make_task
from hg.tests.test_tools_research import ToolBase
from hg.tools.code import UrlReadAdapter


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _raw_server(routes, log):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            line = self.rfile.readline(65537).decode("latin-1")
            while self.rfile.readline(65537) not in (b"\r\n", b"\n", b""):
                pass
            path = line.split(" ")[1] if line.count(" ") >= 2 else "/"
            log.append(path)
            writer = routes.get(path)
            try:
                if writer is None:
                    self.wfile.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno")
                else:
                    writer(self.wfile)
                self.wfile.flush()
            except OSError:
                pass
    server = _Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _response(body, ctype="text/plain", length=None):
    def write(out):
        head = (f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body) if length is None else length}\r\nConnection: close\r\n\r\n")
        out.write(head.encode("latin-1") + body)
    return write


def _chunked(chunks, tail=b"0\r\n\r\n"):
    def write(out):
        out.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nTransfer-Encoding: chunked\r\n"
                  b"Connection: close\r\n\r\n")
        for chunk in chunks:
            out.write(chunk)
        out.write(tail)
    return write


def _drip(stop, ended, total=200, every=0.1):
    def write(out):
        try:
            out.write(f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {total}\r\n"
                      f"Connection: close\r\n\r\n".encode())
            out.flush()
            for _ in range(total):
                if stop.is_set():
                    return
                out.write(b"x")
                out.flush()
                time.sleep(every)
        finally:
            ended.set()
    return write


class UrlReadContentOracle(ToolBase):
    _ids = itertools.count(1)

    def setUp(self):
        super().setUp()
        self.routes, self.log, self.stop = {}, [], threading.Event()
        self.server = _raw_server(self.routes, self.log)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def tearDown(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def fetch(self, writer, *, limit=10):
        self.routes["/docs/page"] = writer
        task = make_task(task_id=f"T-{next(self._ids)}")
        task["scope"]["include"] = [self.base + "docs/"]
        seen = []

        def verifier(snapshot):
            seen.extend(snapshot["outcomes"])
            return True, "any"
        started = time.monotonic()
        rt, final = self.run_goal({"operations": [{"op": "fetch", "url": self.base + "docs/page"}]},
                                  task=task, verifiers={"AC-1": verifier})
        self.assertLess(time.monotonic() - started, limit)
        return rt, final, seen

    def observed(self, seen):
        found = [o["observed"] for o in seen if o.get("tool") == "url.read"]
        self.assertEqual(len(found), 1)
        return found[0]

    def assert_exact(self, writer, body, *, text=True):
        _rt, final, seen = self.fetch(writer)
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        obs = self.observed(seen)
        self.assertEqual(obs["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(obs["bytes"], len(body))
        self.assertFalse(obs.get("truncated"))
        if text:
            self.assertEqual(obs["text"].encode("utf-8"), body)
        else:
            self.assertIsNone(obs["text"])

    def assert_refused(self, writer, *, limit=10):
        rt, final, seen = self.fetch(writer, limit=limit)
        self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")
        for outcome in seen:
            self.assertNotIn("�", repr(outcome))
            self.assertIsNone((outcome.get("observed") or {}).get("text"))
        completed = rt.actions.events("ACTION_COMPLETED")
        for event in completed:
            self.assertNotIn("\\ufffd", repr(event))
        # A read that did not get the document is a known failure, never "may have happened".
        self.assertTrue(completed)
        self.assertEqual({event["payload"]["status"] for event in completed}, {"FAILED"})
        return rt, final

    # ---- controls ----

    def test_control_utf8_text_is_exact(self):
        for body in ("Cấu hình: timeout = 30 ✓\n".encode(), b"a\r\nb\r\n", b""):
            with self.subTest(body=body):
                self.assert_exact(_response(body), body)

    def test_control_media_type_is_case_insensitive(self):
        body = "Xin chào".encode()
        self.assert_exact(_response(body, ctype="Text/Plain; Charset=\"UTF-8\""), body)

    def test_control_body_of_exactly_the_bound(self):
        body = b"y" * UrlReadAdapter.MAX_BYTES
        self.assert_exact(_response(body), body)

    def test_control_chunked_body_is_exact(self):
        body = b"hello world"
        self.assert_exact(_chunked([b"5\r\nhello\r\n", b"6\r\n world\r\n"]), body)

    def test_control_binary_body_has_no_text(self):
        body = b"\x00\xff\xfe binary"
        self.assert_exact(_response(body, ctype="application/octet-stream"), body, text=False)

    # ---- one reading or none ----

    def test_invalid_utf8_text_is_not_returned_as_replaced_text(self):
        for body in (b"timeout = 30 \xff\xfe end\n", "xin chà".encode()[:-1],
                     b"a\xed\xa0\x80b", b"a\xc0\xafb"):
            with self.subTest(body=body):
                self.assert_refused(_response(body))

    def test_declared_non_utf8_charset_is_not_read_as_utf8(self):
        for ctype, body in (("text/plain; charset=iso-8859-1", "café".encode("latin-1")),
                            ("text/html; charset=windows-1252", b"price \x80 5"),
                            ("text/plain; charset=utf-16", "hi".encode("utf-16"))):
            with self.subTest(ctype=ctype):
                self.assert_refused(_response(body, ctype=ctype))

    # ---- the whole body or none ----

    def test_body_shorter_than_content_length_is_refused(self):
        self.assert_refused(_response(b"partial doc", length=500))

    def test_broken_chunked_body_is_refused(self):
        self.assert_refused(_chunked([b"5\r\nhello\r\n", b"40\r\nshort"], tail=b""))

    def test_body_over_the_bound_is_refused_and_bounded_in_memory(self):
        body = b"z" * (UrlReadAdapter.MAX_BYTES + 1)
        tracemalloc.start()
        try:
            self.assert_refused(_response(body))
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024 * 1024)

    def test_body_over_the_bound_cut_inside_a_character_is_refused(self):
        body = b"a" * (UrlReadAdapter.MAX_BYTES - 1) + "ạ".encode() + b"tail"
        self.assert_refused(_response(body))

    # ---- bounded in time ----

    def test_dripping_body_ends_within_the_adapter_budget(self):
        ended = threading.Event()
        with mock.patch.object(UrlReadAdapter, "timeout_s", 4):
            self.assert_refused(_drip(self.stop, ended, total=200, every=0.1), limit=9)
        # The adapter stopped reading: the server's writes fail soon after the task ends.
        self.assertTrue(ended.wait(3))


if __name__ == "__main__":
    import unittest
    unittest.main()
