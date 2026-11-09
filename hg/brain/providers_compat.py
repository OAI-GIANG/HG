"""OpenAI Chat Completions-compatible provider adapter for HG ModelRouter.

This adapter deliberately declares text-only input/output until a provider profile is
explicitly tested for additional modalities. It uses the Python standard library only.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from maep.core import MAEPError
from hg.brain.providers import ModelProvider, ProviderError

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _post_json_no_redirect(url, headers, payload, timeout):
    """Send one bounded JSON request; never forward credentials across a redirect."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers=dict(headers, **{"content-type": "application/json"}),
    )
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError("INVALID_RESPONSE", "provider response exceeds the size limit")
            return response.status, dict(response.headers), raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1) if exc.fp else b""
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("INVALID_RESPONSE", "provider error response exceeds the size limit")
        return exc.code, dict(exc.headers or {}), raw.decode("utf-8", errors="replace")
    except ProviderError:
        raise
    except TimeoutError as exc:
        raise ProviderError("TIMEOUT", "provider request timed out") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ProviderError("TIMEOUT", "provider request timed out") from exc
        raise ProviderError("UNAVAILABLE", f"provider endpoint unavailable ({type(reason).__name__})") from exc


class OpenAICompatibleProvider(ModelProvider):
    """Text-only adapter for OpenAI Chat Completions-compatible endpoints.

    The endpoint, model and API-key environment-variable *name* are configuration, never
    task input. No SDK is required. Compatibility with this wire format does not imply
    vision, audio, video, function-calling, structured-output or streaming support.
    """

    name = "openai-compatible"
    offline = False
    cost_per_mtok = None  # unknown until the owner supplies a current price card
    capabilities = {
        "input_modalities": ("text",),
        "output_modalities": ("text",),
        "streaming": False,
        "tool_calling": False,
        "structured_output": False,
    }

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "https://api.deepseek.com",
        api_key_env: str = "DEEPSEEK_API_KEY",
        provider_name: str = "openai-compatible",
        http_post=_post_json_no_redirect,
        timeout: float = 60,
    ):
        if not isinstance(model, str) or not model.strip() or len(model) > 160:
            raise MAEPError("compatible provider model must be a non-empty string of at most 160 characters")
        if not isinstance(api_key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", api_key_env):
            raise MAEPError("api_key_env must be an environment-variable name")
        if not isinstance(provider_name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", provider_name):
            raise MAEPError("provider_name must be a lowercase identifier")
        try:
            parts = urllib.parse.urlsplit(base_url)
            host = parts.hostname
            loopback_http = (
                parts.scheme == "http" and host is not None
                and ipaddress.ip_address(host).is_loopback
            )
            if (parts.scheme != "https" and not loopback_http) or not host or parts.username or parts.password:
                raise ValueError("endpoint must use HTTPS (or HTTP on a literal loopback IP) without user info")
            if parts.query or parts.fragment or ".." in parts.path.split("/"):
                raise ValueError("endpoint path, query or fragment is invalid")
            _ = parts.port
        except (ValueError, TypeError) as exc:
            raise MAEPError("invalid OpenAI-compatible base_url") from exc
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
            raise MAEPError("provider timeout must be in 1..600 seconds")

        self.name = provider_name
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self._post = http_post
        self._timeout = float(timeout)
        self._url = self.base_url + "/chat/completions"

    def complete(self, request):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError("NOT_CONFIGURED", f"{self.api_key_env} is not set")

        messages = []
        if request["system"]:
            messages.append({"role": "system", "content": request["system"]})
        messages.extend(request["messages"])
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request["max_tokens"],
            "stream": False,
        }
        status, headers, body = self._post(
            self._url, {"Authorization": f"Bearer {key}"}, payload, self._timeout
        )
        if status != 200:
            raise self._error(status, headers)

        try:
            data = json.loads(body)
            choices = data["choices"]
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("choices must be a non-empty array")
            choice = choices[0]
            message = choice.get("message")
            text = message.get("content") if isinstance(message, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError("first choice contains no text content")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise ValueError("usage must be an object")
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            if (
                isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0
                or isinstance(completion_tokens, bool) or not isinstance(completion_tokens, int)
                or completion_tokens < 0
            ):
                raise ValueError("usage token counts must be non-negative integers")
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError("INVALID_RESPONSE", "provider returned an invalid chat-completion response") from exc

        return {
            "text": text,
            "provider": self.name,
            "model": data.get("model", self.model),
            "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
            "finish_reason": choice.get("finish_reason"),
        }

    @staticmethod
    def _error(status, headers):
        # Never surface provider bodies: they may contain echoed prompt content.
        retry_after = {str(k).lower(): v for k, v in (headers or {}).items()}.get("retry-after")
        try:
            retry_after = max(0.0, float(retry_after))
        except (TypeError, ValueError):
            retry_after = None
        if status in (401, 402, 403):
            return ProviderError("REFUSED", f"provider refused credentials or permission (HTTP {status})")
        if status == 429:
            return ProviderError("UNAVAILABLE", "provider rate limit (HTTP 429)", retry_after=retry_after)
        if status in (408, 504):
            return ProviderError("TIMEOUT", f"provider timeout (HTTP {status})", retry_after=retry_after)
        if status in (500, 502, 503, 529):
            return ProviderError("UNAVAILABLE", f"provider unavailable (HTTP {status})", retry_after=retry_after)
        return ProviderError("INVALID_REQUEST", f"provider rejected request (HTTP {status})")
