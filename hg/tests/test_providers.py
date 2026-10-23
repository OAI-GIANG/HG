"""C-12: provider adapters and ModelRouter (retry, fallback, offline mode, accounting, no secrets)."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from maep.core import MAEPError
from hg.brain.providers import (
    AnthropicProvider, ModelRouter, OllamaProvider, ProviderError, make_request, request_digest,
)
from hg.verification.evidence import EventLog
from hg.tests.fakes import FakeHTTP, ScriptedProvider
from hg.tests.support import TempDirMixin

REQ = make_request("You plan.", [{"role": "user", "content": "hello"}], max_tokens=64)
OK_BODY = json.dumps({"model": "claude-sonnet-5-5", "stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}],
                      "usage": {"input_tokens": 7, "output_tokens": 3}})


class RequestTests(unittest.TestCase):
    def test_invalid_requests_rejected(self):
        for args in (("x", []), ("x", [{"role": "system", "content": "a"}]), ("x", [{"role": "user", "content": ""}]),
                     ("x", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]), (1, [{"role": "user", "content": "a"}])):
            with self.assertRaises(MAEPError):
                make_request(*args)
        with self.assertRaises(MAEPError):
            make_request("x", [{"role": "user", "content": "a"}], max_tokens=0)

    def test_digest_is_stable(self):
        self.assertEqual(request_digest(REQ), request_digest(make_request("You plan.", [{"role": "user", "content": "hello"}], max_tokens=64)))


class AnthropicTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-secret"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_request_shape_matches_messages_api_2026_10_21(self):
        http = FakeHTTP((200, {}, OK_BODY))
        response = AnthropicProvider(http_post=http).complete(REQ)
        call = http.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["headers"]["anthropic-version"], "2026-10-21")
        self.assertEqual(call["headers"]["x-api-key"], "sk-test-secret")
        self.assertEqual(set(call["payload"]), {"model", "max_tokens", "messages", "system"})
        self.assertNotIn("temperature", call["payload"])            # removed in 2026-10-21
        self.assertEqual((response["text"], response["usage"]["output_tokens"]), ("hi there", 3))

    def test_missing_key_is_not_configured_and_sends_nothing(self):
        http = FakeHTTP()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError) as ctx:
                AnthropicProvider(http_post=http).complete(REQ)
        self.assertEqual(ctx.exception.kind, "NOT_CONFIGURED")
        self.assertEqual(http.calls, [])

    def test_status_classification(self):
        cases = {401: "REFUSED", 402: "REFUSED", 403: "REFUSED", 400: "INVALID_REQUEST", 404: "INVALID_REQUEST",
                 500: "UNAVAILABLE", 504: "TIMEOUT", 529: "UNAVAILABLE"}
        for status, kind in cases.items():
            err = json.dumps({"type": "error", "error": {"type": "x", "message": f"m{status}"}})
            with self.assertRaises(ProviderError, msg=status) as ctx:
                AnthropicProvider(http_post=FakeHTTP((status, {}, err))).complete(REQ)
            self.assertEqual(ctx.exception.kind, kind, status)

    def test_rate_limit_retryable_only_with_retry_after(self):
        with self.assertRaises(ProviderError) as ctx:
            AnthropicProvider(http_post=FakeHTTP((429, {"Retry-After": "2"}, "{}"))).complete(REQ)
        self.assertEqual((ctx.exception.kind, ctx.exception.retry_after), ("UNAVAILABLE", "2"))
        with self.assertRaises(ProviderError) as ctx:                 # spend cap: no retry-after
            AnthropicProvider(http_post=FakeHTTP((429, {}, "{}"))).complete(REQ)
        self.assertEqual(ctx.exception.kind, "REFUSED")

    def test_refusal_stop_reason_and_garbage_body(self):
        refusal = json.dumps({"stop_reason": "refusal", "content": [], "usage": {}})
        with self.assertRaises(ProviderError) as ctx:
            AnthropicProvider(http_post=FakeHTTP((200, {}, refusal))).complete(REQ)
        self.assertEqual(ctx.exception.kind, "REFUSED")
        with self.assertRaises(ProviderError) as ctx:
            AnthropicProvider(http_post=FakeHTTP((200, {}, "<html>"))).complete(REQ)
        self.assertEqual(ctx.exception.kind, "INVALID_RESPONSE")


class OllamaTests(unittest.TestCase):
    def test_local_chat_request_and_parse(self):
        body = json.dumps({"model": "llama3.1", "message": {"role": "assistant", "content": "ok"},
                           "prompt_eval_count": 4, "eval_count": 2, "done_reason": "stop"})
        http = FakeHTTP((200, {}, body))
        response = OllamaProvider(http_post=http).complete(REQ)
        self.assertEqual(http.calls[0]["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(http.calls[0]["payload"]["messages"][0], {"role": "system", "content": "You plan."})
        self.assertFalse(http.calls[0]["payload"]["stream"])
        self.assertEqual((response["text"], response["usage"]["input_tokens"]), ("ok", 4))

    def test_missing_model_unavailable(self):
        with self.assertRaises(ProviderError) as ctx:
            OllamaProvider(http_post=FakeHTTP((404, {}, ""))).complete(REQ)
        self.assertEqual(ctx.exception.kind, "UNAVAILABLE")

    def test_unreachable_server_unavailable(self):
        with self.assertRaises(ProviderError) as ctx:
            OllamaProvider(base_url="http://127.0.0.1:9", timeout=1).complete(REQ)   # real socket, closed port
        self.assertIn(ctx.exception.kind, {"UNAVAILABLE", "TIMEOUT"})


class RouterTests(TempDirMixin):
    def router(self, *providers, **kw):
        kw.setdefault("sleep", lambda s: None)
        return ModelRouter(list(providers), **kw)

    def test_retries_retryable_then_succeeds(self):
        p = ScriptedProvider(script=[ProviderError("UNAVAILABLE", "busy"), "answer"])
        response = self.router(p).complete(REQ)
        self.assertEqual(response["text"], "answer")
        self.assertEqual([a["error"] for a in response["attempts"]], ["UNAVAILABLE", None])

    def test_missing_configuration_is_not_retried(self):
        sleeps = []
        with mock.patch.dict(os.environ, {}, clear=True):
            router = ModelRouter([AnthropicProvider(http_post=FakeHTTP()), ScriptedProvider("b", ["local"])],
                                 sleep=sleeps.append)
            response = router.complete(REQ)
        self.assertEqual((response["provider"], sleeps), ("b", []))
        self.assertEqual(response["attempts"][0]["error"], "NOT_CONFIGURED")

    def test_non_retryable_falls_back_without_retry(self):
        a = ScriptedProvider("a", [ProviderError("REFUSED", "no"), "never"])
        b = ScriptedProvider("b", ["from b"])
        response = self.router(a, b).complete(REQ)
        self.assertEqual((response["provider"], len(a.requests)), ("b", 1))

    def test_all_fail_raises_unavailable_with_attempts(self):
        a = ScriptedProvider("a", [ProviderError("TIMEOUT", "t"), ProviderError("TIMEOUT", "t")])
        with self.assertRaisesRegex(ProviderError, "a#1=TIMEOUT, a#2=TIMEOUT"):
            self.router(a).complete(REQ)

    def test_offline_mode_never_calls_remote_providers(self):
        remote = ScriptedProvider("remote", ["remote answer"], offline=False)
        local = ScriptedProvider("local", ["local answer"], offline=True)
        response = self.router(remote, local, offline=True).complete(REQ)
        self.assertEqual((response["provider"], remote.requests), ("local", []))

    def test_offline_mode_without_local_provider_is_unavailable(self):
        with self.assertRaisesRegex(ProviderError, "offline"):
            self.router(ScriptedProvider("remote", ["x"], offline=False), offline=True).complete(REQ)

    def test_routes_by_kind(self):
        a, b = ScriptedProvider("a", ["A"]), ScriptedProvider("b", ["B"])
        router = self.router(a, b, routes={"planning": ["b"], "default": ["a"]})
        self.assertEqual(router.complete(REQ, kind="planning")["provider"], "b")
        self.assertEqual(router.complete(REQ)["provider"], "a")

    def test_provider_crash_is_contained(self):
        class Broken(ScriptedProvider):
            def complete(self, request):
                raise KeyError("bug")
        b = ScriptedProvider("b", ["fine"])
        self.assertEqual(self.router(Broken("broken"), b).complete(REQ)["provider"], "b")

    def test_calls_are_ledgered_without_prompt_or_key(self):
        log = EventLog(Path(self.tmp) / "models.jsonl")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-secret"}):
            router = self.router(AnthropicProvider(http_post=FakeHTTP((200, {}, OK_BODY))), event_log=log)
            router.complete(REQ, task_id="T-1")
        raw = Path(log.path).read_text(encoding="utf-8")
        self.assertNotIn("sk-test-secret", raw)
        self.assertNotIn("hello", raw)                                # prompt text not stored
        event = log.events("MODEL_CALL")[0]
        self.assertEqual((event["task_id"], event["payload"]["status"]), ("T-1", "OK"))
        self.assertEqual(router.usage["calls"], 1)

    def test_bad_configuration_rejected(self):
        with self.assertRaises(MAEPError):
            ModelRouter([ScriptedProvider("a"), ScriptedProvider("a")])
        with self.assertRaises(MAEPError):
            ModelRouter([ScriptedProvider("a")], routes={"x": ["nope"]})
        with self.assertRaises(MAEPError):
            ModelRouter([ScriptedProvider("a")], max_retries=9)


if __name__ == "__main__":
    unittest.main()
