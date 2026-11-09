"""WP1: OpenAI-compatible provider contract, redaction and capability declaration."""
import json
import os
import unittest
from unittest import mock

from maep.core import MAEPError
from hg.brain.providers import ModelRouter, ProviderError, make_request
from hg.brain.providers_compat import OpenAICompatibleProvider
from hg.tests.fakes import FakeHTTP


REQ = make_request("You are a planner.", [{"role": "user", "content": "write a file"}], max_tokens=80)


def ok_body():
    return json.dumps({
        "id": "chatcmpl-test",
        "model": "deepseek-flash",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": '{"steps": []}'},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 14, "completion_tokens": 5, "total_tokens": 19},
    })


class OpenAICompatibleProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_request_shape_and_response_usage(self):
        http = FakeHTTP((200, {}, ok_body()))
        provider = OpenAICompatibleProvider(
            "deepseek-flash", provider_name="deepseek", http_post=http
        )
        response = provider.complete(REQ)
        call = http.calls[0]
        self.assertEqual(call["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test-secret")
        self.assertEqual(call["payload"]["model"], "deepseek-flash")
        self.assertEqual(call["payload"]["messages"][0],
                         {"role": "system", "content": "You are a planner."})
        self.assertFalse(call["payload"]["stream"])
        self.assertEqual(response["provider"], "deepseek")
        self.assertEqual(response["usage"], {"input_tokens": 14, "output_tokens": 5})

    def test_missing_key_sends_no_request(self):
        http = FakeHTTP((200, {}, ok_body()))
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = OpenAICompatibleProvider("deepseek-flash", http_post=http)
            with self.assertRaises(ProviderError) as ctx:
                provider.complete(REQ)
        self.assertEqual(ctx.exception.kind, "NOT_CONFIGURED")
        self.assertEqual(http.calls, [])

    def test_api_error_mapping_and_response_body_is_not_disclosed(self):
        cases = {
            400: "INVALID_REQUEST",
            401: "REFUSED",
            403: "REFUSED",
            429: "UNAVAILABLE",
            500: "UNAVAILABLE",
            502: "UNAVAILABLE",
            503: "UNAVAILABLE",
            504: "TIMEOUT",
        }
        for status, kind in cases.items():
            with self.subTest(status=status):
                http = FakeHTTP((status, {"Retry-After": "2"}, '{"error":{"message":"echo secret prompt"}}'))
                with self.assertRaises(ProviderError) as ctx:
                    OpenAICompatibleProvider("deepseek-flash", http_post=http).complete(REQ)
                self.assertEqual(ctx.exception.kind, kind)
                self.assertNotIn("echo secret prompt", str(ctx.exception))

    def test_rate_limit_retry_after_is_bounded_by_router(self):
        http = FakeHTTP((429, {"Retry-After": "2"}, "{}"))
        provider = OpenAICompatibleProvider("deepseek-flash", http_post=http)
        sleeps = []
        router = ModelRouter([provider], sleep=sleeps.append)
        with self.assertRaises(ProviderError):
            router.complete(REQ)
        self.assertEqual(sleeps, [2.0])

    def test_bad_response_is_rejected(self):
        for body in ("<html>", "{}", json.dumps({"choices": []}),
                     json.dumps({"choices": [{"message": {"content": None}}]}),
                     json.dumps({"choices": [{"message": {"content": "ok"}}],
                                 "usage": {"prompt_tokens": -1}})):
            with self.subTest(body=body[:20]):
                with self.assertRaises(ProviderError) as ctx:
                    OpenAICompatibleProvider(
                        "deepseek-flash", http_post=FakeHTTP((200, {}, body))
                    ).complete(REQ)
                self.assertEqual(ctx.exception.kind, "INVALID_RESPONSE")

    def test_endpoint_must_be_https_or_literal_loopback_http(self):
        for url in (
            "http://api.example.test",
            "https://user:password@api.example.test",
            "https://api.example.test/v1?redirect=1",
            "https://api.example.test/../evil",
        ):
            with self.subTest(url=url), self.assertRaises(MAEPError):
                OpenAICompatibleProvider("model", base_url=url)

        local = OpenAICompatibleProvider("model", base_url="http://127.0.0.1:9000/v1",
                                         http_post=FakeHTTP((200, {}, ok_body())))
        self.assertEqual(local.base_url, "http://127.0.0.1:9000/v1")

    def test_invalid_key_variable_name_and_model(self):
        for kwargs in ({"api_key_env": "not-a-var"}, {"api_key_env": "sk-secret-value"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(MAEPError):
                OpenAICompatibleProvider("model", **kwargs)
        with self.assertRaises(MAEPError):
            OpenAICompatibleProvider("")

    def test_router_catalog_does_not_claim_unconfigured_modalities(self):
        provider = OpenAICompatibleProvider("deepseek-flash", provider_name="deepseek")
        catalog = ModelRouter([provider]).catalog()
        self.assertEqual(catalog, [{
            "provider": "deepseek",
            "model": "deepseek-flash",
            "offline": False,
            "capabilities": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "streaming": False,
                "tool_calling": False,
                "structured_output": False,
            },
            "cost_known": False,
        }])

    def test_unknown_price_is_not_reported_as_zero_cost(self):
        provider = OpenAICompatibleProvider(
            "deepseek-flash", http_post=FakeHTTP((200, {}, ok_body()))
        )
        router = ModelRouter([provider])
        router.complete(REQ)
        self.assertIsNone(router.usage["cost_usd"])
        self.assertFalse(router.usage["cost_known"])


if __name__ == "__main__":
    unittest.main()
