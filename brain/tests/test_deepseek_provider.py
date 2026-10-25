import json
import socket
import unittest
from urllib.error import HTTPError

from brain.deepseek_provider import DeepSeekJSONProvider
from brain.planning import PlanningError
from brain.provider_factory import build_reasoning_provider
from brain.provider_guard import GuardedJSONProvider, authorize_provider_calls
from brain.routing_budget import SQLiteRoutingBudgetLedger
import tempfile
from pathlib import Path


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1): return self.payload[:size]


class DeepSeekProviderTests(unittest.TestCase):
    def test_construction_does_not_read_credentials_or_network(self):
        calls = []
        provider = DeepSeekJSONProvider(
            endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
            credential_provider=lambda: calls.append("credential") or "fake-key",
            opener=lambda *args, **kwargs: calls.append("network"),
        )
        self.assertEqual(calls, [])
        self.assertIsNone(provider.last_usage)

    def test_success_uses_bounded_output_and_records_actual_token_usage(self):
        calls = []
        payload = json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}],
                              "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26}}).encode()
        def opener(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(payload)
        provider = DeepSeekJSONProvider(
            endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
            credential_provider=lambda: "test-key", max_output_tokens=123, opener=opener,
        )
        self.assertEqual(provider.generate_json(system_prompt="s", user_prompt="u"), '{"ok":true}')
        request, timeout = calls[0]
        body = json.loads(request.data)
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(timeout, 20.0)
        self.assertEqual(provider.last_usage, {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26})
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_retry_is_bounded_and_only_retries_transient_http_error(self):
        calls = []
        payload = b'{"choices":[{"message":{"content":"{}"}}]}'
        def opener(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 429, "limited", {}, None)
            return FakeResponse(payload)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SQLiteRoutingBudgetLedger(Path(tmp) / "budget.sqlite3")
            provider = GuardedJSONProvider(DeepSeekJSONProvider(
                endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
                credential_provider=lambda: "key", max_retries=1, opener=opener,
            ))
            with authorize_provider_calls(
                ledger=ledger, task_ref="task:retry-basic", candidate_ref="candidate:1",
                policy_version="policy:1", route="L4_DEEPSEEK", category="reasoning", limit=2,
            ):
                self.assertEqual(provider.generate_json(system_prompt="s", user_prompt="u"), "{}")
            self.assertEqual(len(calls), 2)
            self.assertEqual(ledger.get_usage("task:retry-basic")["reasoning"], 2)

    def test_each_paid_retry_requires_and_consumes_another_runtime_reservation(self):
        calls = []
        payload = b'{"choices":[{"message":{"content":"{}"}}]}'
        def opener(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 429, "limited", {}, None)
            return FakeResponse(payload)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SQLiteRoutingBudgetLedger(Path(tmp) / "budget.sqlite3")
            raw = DeepSeekJSONProvider(
                endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
                credential_provider=lambda: "key", max_retries=1, opener=opener,
            )
            guarded = GuardedJSONProvider(raw)
            with authorize_provider_calls(
                ledger=ledger, task_ref="task:retry", candidate_ref="candidate:1",
                policy_version="policy:1", route="L4_DEEPSEEK", category="reasoning", limit=2,
            ):
                self.assertEqual(guarded.generate_json(system_prompt="s", user_prompt="u"), "{}")
            self.assertEqual(len(calls), 2)
            self.assertEqual(ledger.get_usage("task:retry")["reasoning"], 2)
            with authorize_provider_calls(
                ledger=ledger, task_ref="task:retry", candidate_ref="candidate:1",
                policy_version="policy:1", route="L4_DEEPSEEK", category="reasoning", limit=2,
            ):
                with self.assertRaises(Exception):
                    guarded.generate_json(system_prompt="s", user_prompt="u")
            self.assertEqual(len(calls), 2)

    def test_no_retry_by_default_and_bad_credential_fail_closed(self):
        calls = []
        def opener(request, timeout):
            calls.append(1)
            raise HTTPError(request.full_url, 429, "limited", {}, None)
        provider = DeepSeekJSONProvider(
            endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
            credential_provider=lambda: "key", opener=opener,
        )
        with self.assertRaises(PlanningError):
            provider.generate_json(system_prompt="s", user_prompt="u")
        self.assertEqual(len(calls), 1)
        invalid = DeepSeekJSONProvider(
            endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
            credential_provider=lambda: "\n",
        )
        with self.assertRaises(PlanningError):
            invalid.generate_json(system_prompt="s", user_prompt="u")

    def test_timeout_fails_closed_without_retry_by_default(self):
        calls = []
        def opener(request, timeout):
            calls.append(timeout)
            raise socket.timeout("simulated timeout")
        provider = DeepSeekJSONProvider(
            endpoint="https://api.deepseek.com/chat/completions", model="deepseek-chat",
            credential_provider=lambda: "key", opener=opener,
        )
        with self.assertRaisesRegex(PlanningError, "endpoint unavailable"):
            provider.generate_json(system_prompt="s", user_prompt="u")
        self.assertEqual(calls, [20.0])

    def test_factory_requires_runtime_credential_provider_and_official_endpoint(self):
        with self.assertRaises(PlanningError):
            build_reasoning_provider({"provider_type": "deepseek", "endpoint": "https://api.deepseek.com/chat/completions", "model": "deepseek-chat"})
        provider = build_reasoning_provider({
            "provider_type": "deepseek", "endpoint": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat", "credential_provider": lambda: "key",
        })
        self.assertIsInstance(provider, DeepSeekJSONProvider)
        with self.assertRaises(PlanningError):
            build_reasoning_provider({
                "provider_type": "deepseek", "endpoint": "https://example.com/chat/completions",
                "model": "deepseek-chat", "credential_provider": lambda: "key",
            })


if __name__ == "__main__":
    unittest.main()
