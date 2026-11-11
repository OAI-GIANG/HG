"""Model response read oracle (WS-04): ambiguous or malformed model-server bytes are refused.

A real loopback HTTP server stands in for Ollama and answers with exact bytes; the Anthropic
adapter gets scripted bodies. Each case asserts that the adapter raises
ProviderError(INVALID_RESPONSE) within a few seconds instead of returning a reading of the bytes,
and that once any text has been shown the router never hands the call to another provider (the
reader would see two different answers). Controls: a canonical answer still succeeds.
"""
import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from hg.brain.providers import (
    MAX_RESPONSE_BYTES, MAX_STREAM_LINE_BYTES, AnthropicProvider, ModelProvider, ModelRouter,
    OllamaProvider, ProviderError, make_request,
)
from hg.tests.fakes import FakeHTTP, ScriptedProvider

REQ = make_request("", [{"role": "user", "content": "hello"}], max_tokens=64)
DEADLINE_S = 5.0


def line(obj):
    return json.dumps(obj).encode("utf-8") + b"\n"


CHUNK = line({"model": "m", "message": {"role": "assistant", "content": "Hello. "}, "done": False})
DONE = line({"model": "m", "message": {"role": "assistant", "content": ""}, "done": True,
             "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 2})


class _Server:
    """Loopback HTTP server: POST /api/chat answers with self.body (bytes or a callable(wfile))."""

    def __init__(self):
        outer = self
        self.body = b""

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                try:
                    if callable(outer.body):
                        outer.body(self.wfile)
                    else:
                        self.wfile.write(outer.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class _Oracle(unittest.TestCase):
    def setUp(self):
        self.server = _Server()
        self.addCleanup(self.server.close)

    def provider(self):
        return OllamaProvider("m", base_url=self.server.url, timeout=DEADLINE_S)

    def assert_invalid(self, call):
        started = time.monotonic()
        with self.assertRaises(ProviderError) as ctx:
            call()
        self.assertLess(time.monotonic() - started, DEADLINE_S)
        self.assertEqual(ctx.exception.kind, "INVALID_RESPONSE", str(ctx.exception))
        return ctx.exception


class OllamaStreamOracle(_Oracle):
    def stream(self, body):
        self.server.body = body
        shown = []
        self.assert_invalid(lambda: self.provider().complete(REQ, on_delta=shown.append))
        return "".join(shown)

    def test_control_canonical_stream(self):
        self.server.body = CHUNK + DONE
        shown = []
        response = self.provider().complete(REQ, on_delta=shown.append)
        self.assertEqual((response["text"], "".join(shown)), ("Hello.", "Hello. "))
        self.assertEqual(response["usage"], {"input_tokens": 3, "output_tokens": 2})

    def test_non_utf8_line_refused(self):
        self.stream(CHUNK + b'{"message": {"content": "\xff\xfe"}, "done": false}\n' + DONE)

    def test_non_object_line_refused(self):
        for bad in (b"[1, 2]\n", b'"text"\n', b"7\n", b"null\n"):
            with self.subTest(bad=bad):
                self.stream(CHUNK + bad + DONE)

    def test_duplicate_key_line_refused(self):
        shown = self.stream(b'{"message": {"content": "A"}, "message": {"content": "B"}, "done": false}\n' + DONE)
        self.assertEqual(shown, "")

    def test_malformed_message_or_content_refused(self):
        for bad in ({"message": ["x"], "done": False}, {"message": {"content": ["x"]}, "done": False},
                    {"message": {"content": 7}, "done": False}, {"message": {"content": "x"}, "done": "yes"}):
            with self.subTest(bad=bad):
                self.stream(CHUNK + line(bad) + DONE)

    def test_data_after_final_message_refused(self):
        shown = self.stream(CHUNK + DONE + line({"message": {"content": "LATE"}, "done": False}))
        self.assertNotIn("LATE", shown)

    def test_second_final_message_refused(self):
        self.stream(CHUNK + DONE + DONE)

    def test_invalid_usage_counts_refused(self):
        for key, value in (("eval_count", -1), ("eval_count", True), ("prompt_eval_count", "3"),
                           ("eval_count", 1.5), ("prompt_eval_count", None)):
            with self.subTest(key=key, value=value):
                final = {"message": {"content": ""}, "done": True, "eval_count": 2, "prompt_eval_count": 3}
                final[key] = value
                self.stream(CHUNK + line(final))

    def test_oversized_line_refused_without_waiting(self):
        def write(wfile):
            wfile.write(CHUNK + b'{"message": {"content": "' + b"a" * (MAX_STREAM_LINE_BYTES + 16))
            wfile.flush()
            time.sleep(DEADLINE_S + 2)       # keep the connection open: the reader must not wait for EOF
        self.stream(write)

    def test_endless_stream_refused(self):
        def write(wfile):
            piece = line({"message": {"content": "x" * 60000}, "done": False})
            for _ in range(MAX_RESPONSE_BYTES // len(piece) * 2 + 2):
                wfile.write(piece)
            wfile.write(DONE)                # a well-formed end: only the size bound can refuse it
        self.server.body = write
        with mock.patch("hg.brain.providers.MAX_STREAM_BYTES", MAX_RESPONSE_BYTES):
            self.assert_invalid(lambda: self.provider().complete(REQ, on_delta=lambda t: None))


class OllamaBodyOracle(_Oracle):
    def body(self, body):
        self.server.body = body
        return self.assert_invalid(lambda: self.provider().complete(REQ))

    def test_control_canonical_body(self):
        self.server.body = json.dumps({"model": "m", "message": {"content": "ok"}, "prompt_eval_count": 4,
                                       "eval_count": 2, "done_reason": "stop"}).encode("utf-8")
        response = self.provider().complete(REQ)
        self.assertEqual((response["text"], response["usage"]["output_tokens"]), ("ok", 2))

    def test_duplicate_key_body_refused(self):
        self.body(b'{"message": {"content": "A"}, "message": {"content": "B"}}')
        self.body(b'{"message": {"content": "A", "content": "B"}}')

    def test_non_utf8_body_refused(self):
        self.body(b'{"message": {"content": "\xff"}}')

    def test_non_string_content_refused(self):
        for content in (["x"], 7, None, {"t": "x"}):
            with self.subTest(content=content):
                self.body(json.dumps({"message": {"content": content}}).encode("utf-8"))

    def test_invalid_usage_counts_refused(self):
        for value in (-5, True, "4", 2.0):
            with self.subTest(value=value):
                self.body(json.dumps({"message": {"content": "ok"}, "eval_count": value}).encode("utf-8"))

    def test_oversized_body_refused_without_waiting(self):
        def write(wfile):
            wfile.write(b'{"message": {"content": "' + b"a" * (MAX_RESPONSE_BYTES + 16))
            wfile.flush()
            time.sleep(DEADLINE_S + 2)
        self.body(write)

    def test_tags_duplicate_digest_refused(self):
        """The digest pin reads /api/tags: a repeated key must not pick one of two digests."""
        self.server.body = (b'{"models": [{"name": "m:latest", "digest": "aaaa", "digest": "bbbb", "size": 1}]}')
        with self.assertRaises(ProviderError) as ctx:
            self.provider().tags(timeout=DEADLINE_S)
        self.assertEqual(ctx.exception.kind, "INVALID_RESPONSE")

    def test_tags_control(self):
        self.server.body = b'{"models": [{"name": "m:latest", "digest": "aaaa", "size": 1}]}'
        self.assertEqual(self.provider().tags(timeout=DEADLINE_S)[0]["digest"], "aaaa")


class AnthropicBodyOracle(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def complete(self, body):
        return AnthropicProvider(http_post=FakeHTTP((200, {}, body))).complete(REQ)

    def test_control(self):
        body = json.dumps({"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
        self.assertEqual(self.complete(body)["text"], "hi")

    def test_refused(self):
        for body in ('{"content": [{"type": "text", "text": "A"}], "content": [{"type": "text", "text": "B"}]}',
                     '{"content": [{"type": "text", "text": "A", "text": "B"}]}',
                     json.dumps({"content": [{"type": "text", "text": ["x"]}]}),
                     json.dumps({"content": [{"type": "text", "text": "x"}], "usage": {"output_tokens": -3}}),
                     json.dumps({"content": [{"type": "text", "text": "x"}], "usage": {"input_tokens": "9"}}),
                     json.dumps({"content": [{"type": "text", "text": "x"}], "usage": []})):
            with self.subTest(body=body):
                with self.assertRaises(ProviderError) as ctx:
                    self.complete(body)
                self.assertEqual(ctx.exception.kind, "INVALID_RESPONSE")


class _ShowsThenCrashes(ModelProvider):
    name, model, offline, supports_stream = "first", "f-1", True, True

    def complete(self, request, on_delta=None):
        if on_delta is not None:
            on_delta("Partial answer. ")
        raise KeyError("provider bug after output")


class RouterShownTextOracle(unittest.TestCase):
    def test_no_fallback_after_text_shown_on_provider_bug(self):
        second = ScriptedProvider("second", ["A different answer."])
        shown = []
        router = ModelRouter([_ShowsThenCrashes(), second], max_retries=1, sleep=lambda s: None)
        with self.assertRaisesRegex(ProviderError, "part-way"):
            router.complete(REQ, on_delta=shown.append)
        self.assertEqual(("".join(shown), second.requests), ("Partial answer. ", []))

    def test_no_fallback_after_text_shown_on_bad_final_line(self):
        server = _Server()
        self.addCleanup(server.close)
        server.body = CHUNK + line({"message": {"content": ""}, "done": True, "eval_count": -1})
        second = ScriptedProvider("second", ["A different answer."])
        shown = []
        router = ModelRouter([OllamaProvider("m", base_url=server.url, timeout=DEADLINE_S), second],
                             max_retries=1, sleep=lambda s: None)
        with self.assertRaisesRegex(ProviderError, "part-way"):
            router.complete(REQ, on_delta=shown.append)
        self.assertEqual(("".join(shown), second.requests), ("Hello. ", []))

    def test_control_bug_before_any_text_still_falls_back(self):
        class Silent(_ShowsThenCrashes):
            def complete(self, request, on_delta=None):
                raise KeyError("bug")
        second = ScriptedProvider("second", ["fine"])
        response = ModelRouter([Silent(), second], sleep=lambda s: None).complete(REQ, on_delta=lambda t: None)
        self.assertEqual(response["provider"], "second")


if __name__ == "__main__":
    unittest.main()
