"""WS-04: JSON nesting depth is bounded before any recursive parser sees it.

CPython's json scanner (and json.dumps, used right after it) recurse in C once per
nesting level. On Termux/Android, Python 3.14, a worker thread with the platform default
stack is killed by SIGSEGV on a 20 000-level body (5 000 levels parse), and `hg serve`
parses request bodies and model replies on worker threads: one authenticated request
could kill the whole service. A RecursionError (Linux) is not a ValueError either, so it
escaped the boundary's error mapping.

Oracle: a body deeper than MAX_JSON_DEPTH is refused as invalid JSON without json.loads
being called on it; brackets inside strings do not count; depth up to the limit parses
exactly as before; a live server answers 400 and keeps serving.
"""
import json
import socket
import unittest
from unittest import mock

from hg.brain import providers
from hg.http_api import HTTPBoundaryError, strict_json
from hg.json_depth import MAX_JSON_DEPTH, json_depth_exceeds
from hg.tests import test_http_request_parse_oracle as parse_oracle


def nested(depth, open_="[", close="]", inner="0"):
    return open_ * depth + inner + close * depth


def nested_objects(depth):
    text = "0"
    for _ in range(depth):
        text = '{"a":' + text + "}"
    return text


class DepthScanner(unittest.TestCase):
    def test_depth_at_limit_is_allowed_and_one_more_is_not(self):
        self.assertFalse(json_depth_exceeds(nested(MAX_JSON_DEPTH)))
        self.assertTrue(json_depth_exceeds(nested(MAX_JSON_DEPTH + 1)))
        self.assertFalse(json_depth_exceeds(nested_objects(MAX_JSON_DEPTH)))
        self.assertTrue(json_depth_exceeds(nested_objects(MAX_JSON_DEPTH + 1)))

    def test_brackets_inside_strings_do_not_count(self):
        deep_text = json.dumps({"content": "[" * 20000 + "{" * 20000})
        self.assertFalse(json_depth_exceeds(deep_text))
        escaped = json.dumps({"content": '\\"' + "[" * 200 + '\\\\"'})
        self.assertFalse(json_depth_exceeds(escaped))

    def test_escaped_quote_does_not_end_a_string(self):
        # '"\"[[[..."' is one string; a scanner that stopped at \" would count 200 levels.
        text = '["\\"' + "[" * 200 + '"]'
        self.assertEqual(json.loads(text), ['"' + "[" * 200])
        self.assertFalse(json_depth_exceeds(text))

    def test_mixed_nesting_counts_both_kinds(self):
        text = '{"a":' * 40 + "[" * 30 + "1" + "]" * 30 + "}" * 40
        self.assertTrue(json_depth_exceeds(text))

    def test_bytes_and_str_agree(self):
        text = nested(MAX_JSON_DEPTH + 1)
        self.assertTrue(json_depth_exceeds(text.encode()))
        self.assertFalse(json_depth_exceeds(nested(3).encode()))


class StrictJSONBoundary(unittest.TestCase):
    def test_deep_body_is_invalid_json_and_never_parsed(self):
        for body in (nested(20000), nested_objects(2000), nested(MAX_JSON_DEPTH + 1)):
            with self.subTest(depth=body[:8]), \
                    mock.patch("hg.http_api.json.loads", side_effect=AssertionError("parsed")) as loads:
                with self.assertRaises(HTTPBoundaryError) as ctx:
                    strict_json(body.encode())
                self.assertEqual((ctx.exception.status, ctx.exception.code), (400, "invalid_json"))
                loads.assert_not_called()

    def test_depth_at_limit_parses_as_before(self):
        self.assertEqual(strict_json(nested(MAX_JSON_DEPTH).encode()), json.loads(nested(MAX_JSON_DEPTH)))
        content = "[" * 5000
        self.assertEqual(strict_json(json.dumps({"c": content}).encode()), {"c": content})


class ProviderJSONBoundary(unittest.TestCase):
    def test_deep_model_reply_is_a_value_error_and_never_parsed(self):
        for parse in (providers.parse_json, providers.parse_model_json):
            with self.subTest(parse=parse.__name__), \
                    mock.patch("hg.brain.providers.json.loads", side_effect=AssertionError("parsed")) as loads:
                with self.assertRaises(ValueError):
                    parse(nested(20000))
                loads.assert_not_called()

    def test_deep_stream_line_is_invalid_response(self):
        line = json.dumps({"message": {"content": "x"}})[:-1] + ',"d":' + nested(MAX_JSON_DEPTH + 1) + "}"
        with self.assertRaises(ValueError):
            providers.parse_json(line)

    def test_shallow_replies_parse_as_before(self):
        reply = {"model": "m", "message": {"role": "assistant", "content": "[[[ not structure"}}
        text = json.dumps(reply)
        self.assertEqual(providers.parse_json(text), reply)
        self.assertEqual(providers.parse_model_json(text), reply)


class LiveServerDeepBody(parse_oracle.HTTPRequestParseOracle):
    """A real HGHTTPServer answers 400 to a deep body, with no effect, and keeps serving."""

    def send_for_error(self, method, target, headers, body):
        lines = [f"{method} {target} HTTP/1.1"] + [f"{n}: {v}" for n, v in headers]
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
        with socket.create_connection(("127.0.0.1", self.port), timeout=5.0) as sock:
            sock.sendall(raw)
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        head, _, payload = b"".join(chunks).partition(b"\r\n\r\n")
        return int(head.split(b" ", 2)[1]), json.loads(payload).get("error")

    def test_deep_body_is_400_without_effect_and_server_keeps_serving(self):
        body = nested(2000).encode()           # fits the oracle server's 4096-byte limit
        key = "json-depth-deep-1"
        headers = self.base_headers(body, key=key)
        status, error = self.send_for_error("POST", "/v1/tasks", headers, body)
        # invalid_json, not invalid_task: the body was refused before it was parsed.
        self.assertEqual((status, error), (400, "invalid_json"))
        self.assertFalse((self.root / "out/hello.txt").exists())
        self.assertNotIn(key, self.claimed_keys())
        good = self.body(tag="after-deep")
        status, _ = self.send("POST", "/v1/tasks", self.base_headers(good, key="json-depth-good-1"), good)
        self.assertEqual(status, 200)


# Run only the live-server case here; the inherited parse-oracle cases run in their own module.
for _name in [n for n in dir(parse_oracle.HTTPRequestParseOracle) if n.startswith("test_")]:
    if _name not in LiveServerDeepBody.__dict__:
        setattr(LiveServerDeepBody, _name, None)
del _name

if __name__ == "__main__":
    unittest.main()
