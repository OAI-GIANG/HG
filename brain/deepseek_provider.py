"""Explicitly configured DeepSeek-compatible JSON provider.

Construction performs no I/O. A trusted credential callback is consulted only when
an authorized invocation reaches generate_json. No environment/disk secret discovery.
"""
from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from typing import Any, Callable

from brain.planning import PlanningError, _unique_pairs


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class DeepSeekJSONProvider:
    """Bounded adapter; retry policy is explicit and token usage is reported if present."""

    def __init__(self, *, endpoint: str, model: str, credential_provider: Callable[[], str],
                 timeout_seconds: float = 20.0, max_response_bytes: int = 256_000,
                 max_output_tokens: int = 2048, max_retries: int = 0, opener=None):
        parsed = urlsplit(endpoint if isinstance(endpoint, str) else "")
        if (parsed.scheme != "https" or parsed.hostname != "api.deepseek.com"
                or parsed.path != "/chat/completions" or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise PlanningError("DeepSeek endpoint must be the official HTTPS chat completions endpoint")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise PlanningError("DeepSeek model identifier is invalid")
        if not callable(credential_provider):
            raise PlanningError("DeepSeek requires an explicit trusted credential provider")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 60:
            raise PlanningError("DeepSeek timeout must be between 0 and 60 seconds")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not 1024 <= max_response_bytes <= 1_000_000:
            raise PlanningError("DeepSeek response byte limit is invalid")
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 8192:
            raise PlanningError("DeepSeek output token limit is invalid")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
            raise PlanningError("DeepSeek retry limit must be between 0 and 2")
        self.endpoint = endpoint
        self.model = model.strip()
        self._credential_provider = credential_provider
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = max_response_bytes
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self.last_usage: dict[str, int] | None = None
        self._retry_reservation_callback = None
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirectHandler()).open

    def set_retry_reservation_callback(self, callback) -> None:
        """Install the runtime's reservation hook for each additional HTTP attempt."""
        if not callable(callback):
            raise PlanningError("retry reservation callback must be callable")
        self._retry_reservation_callback = callback

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if not isinstance(system_prompt, str) or not system_prompt.strip() or not isinstance(user_prompt, str) or not user_prompt.strip():
            raise PlanningError("DeepSeek prompts must be non-empty")
        try:
            credential = self._credential_provider()
        except Exception as exc:
            raise PlanningError("DeepSeek credential source unavailable; request blocked") from exc
        if not isinstance(credential, str) or not credential.strip() or any(ord(c) < 32 or ord(c) == 127 for c in credential):
            raise PlanningError("DeepSeek credential source returned an invalid credential")
        body = json.dumps({
            "model": self.model, "temperature": 0, "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
        }, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = Request(self.endpoint, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": "Bearer " + credential,
        }, method="POST")
        self.last_usage = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                if not callable(self._retry_reservation_callback):
                    raise PlanningError("DeepSeek retry blocked: runtime reservation hook is required")
                self._retry_reservation_callback()
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    raw = response.read(self.max_response_bytes + 1)
                break
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt >= self.max_retries:
                    raise PlanningError("DeepSeek request failed; no result was accepted") from exc
            except (URLError, OSError, TimeoutError, socket.timeout) as exc:
                if attempt >= self.max_retries:
                    raise PlanningError("DeepSeek endpoint unavailable; no result was accepted") from exc
        if not isinstance(raw, (bytes, bytearray)) or len(raw) > self.max_response_bytes:
            raise PlanningError("DeepSeek response exceeds size limit")
        try:
            envelope = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_unique_pairs)
            content = envelope["choices"][0]["message"]["content"]
            usage = envelope.get("usage")
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise PlanningError("DeepSeek returned an invalid response envelope") from exc
        if not isinstance(content, str) or not content.strip():
            raise PlanningError("DeepSeek returned empty message content")
        if isinstance(usage, dict):
            normalized = {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    normalized[key] = value
            self.last_usage = normalized or None
        return content
