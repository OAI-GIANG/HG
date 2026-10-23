"""C-12 Model provider abstraction for HG Brain (MIID layer 4).

HG reasons through `ModelRouter`, never through a vendor SDK. A provider turns one
request -- system text, messages, max_tokens -- into one response with text, usage and a
finish reason. Errors are classified so the router can decide whether to retry, fall
back or stop:

    UNAVAILABLE      not configured, unreachable, overloaded, rate limited (retryable)
    TIMEOUT          no answer in time (retryable)
    REFUSED          the provider rejected credentials or permission (not retryable)
    INVALID_REQUEST  the request itself is wrong (not retryable)
    INVALID_RESPONSE the provider answered with something unusable (retryable once)

Claude is one optional provider (MIID §4, §13): nothing in HG requires it. With
`offline=True` the router uses only providers marked offline (a local model).

Providers here:
- AnthropicProvider: Claude Messages API, `POST /v1/messages`, header
  `anthropic-version: 2026-10-21` (that version removed temperature/top_p/top_k, so they
  are never sent). Key from ANTHROPIC_API_KEY; never logged.
- OllamaProvider: a local model server (`POST /api/chat`), offline.

Every call is recorded as a MODEL_CALL event (provider, model, kind, status, usage,
duration, a hash of the request) -- never the prompt text or any key.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from maep.core import MAEPError

ERROR_KINDS = {"UNAVAILABLE", "TIMEOUT", "REFUSED", "INVALID_REQUEST", "INVALID_RESPONSE"}
RETRYABLE = {"UNAVAILABLE", "TIMEOUT", "INVALID_RESPONSE"}


class ProviderError(Exception):
    def __init__(self, kind, message, *, retry_after=None):
        if kind not in ERROR_KINDS:
            kind = "UNAVAILABLE"
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.retry_after = retry_after


def make_request(system, messages, *, max_tokens=1024):
    """Validate and normalise one model request."""
    if not isinstance(system, str):
        raise MAEPError("system must be a string")
    if (not isinstance(messages, list) or not messages
            or not all(isinstance(m, dict) and m.get("role") in {"user", "assistant"}
                       and isinstance(m.get("content"), str) and m["content"] for m in messages)):
        raise MAEPError("messages must be a non-empty list of {role: user|assistant, content: text}")
    if messages[-1]["role"] != "user":
        raise MAEPError("the last message must come from the user")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 64000:
        raise MAEPError("max_tokens must be an integer between 1 and 64000")
    return {"system": system, "messages": [dict(m) for m in messages], "max_tokens": max_tokens}


def request_digest(request):
    material = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def urllib_post_json(url, headers, payload, timeout):
    """POST JSON; returns (status, headers_dict, text). Network errors raise ProviderError."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=dict(headers, **{"content-type": "application/json"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, dict(exc.headers or {}), body
    except TimeoutError as exc:
        raise ProviderError("TIMEOUT", str(exc))
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise ProviderError("TIMEOUT", str(reason))
        raise ProviderError("UNAVAILABLE", f"cannot reach {url}: {reason}")


class ModelProvider:
    """Interface. Subclasses set name/model/offline and implement complete()."""

    name = None
    model = None
    offline = False
    cost_per_mtok = (0.0, 0.0)     # (input, output) in USD per million tokens; 0 for local

    def complete(self, request):
        raise NotImplementedError


class AnthropicProvider(ModelProvider):
    name = "anthropic"
    offline = False
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2026-10-21"

    def __init__(self, model="claude-sonnet-5-5", *, api_key_env="ANTHROPIC_API_KEY", http_post=urllib_post_json,
                 timeout=60, cost_per_mtok=(0.0, 0.0)):
        self.model = model
        self._key_env = api_key_env
        self._post = http_post
        self._timeout = timeout
        self.cost_per_mtok = cost_per_mtok

    def complete(self, request):
        key = os.environ.get(self._key_env)
        if not key:
            raise ProviderError("UNAVAILABLE", f"{self._key_env} is not set")
        payload = {"model": self.model, "max_tokens": request["max_tokens"], "messages": request["messages"]}
        if request["system"]:
            payload["system"] = request["system"]
        status, headers, body = self._post(self.API_URL, {"x-api-key": key, "anthropic-version": self.API_VERSION},
                                           payload, self._timeout)
        if status != 200:
            raise self._error(status, headers, body)
        try:
            data = json.loads(body)
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            usage = data.get("usage") or {}
            finish = data.get("stop_reason")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_RESPONSE", f"unparseable Messages API response: {exc}")
        if finish == "refusal":
            raise ProviderError("REFUSED", "the model declined the request")
        return {"text": text, "provider": self.name, "model": data.get("model", self.model),
                "usage": {"input_tokens": int(usage.get("input_tokens", 0)),
                          "output_tokens": int(usage.get("output_tokens", 0))},
                "finish_reason": finish}

    @staticmethod
    def _error(status, headers, body):
        try:
            message = json.loads(body)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = f"HTTP {status}"
        retry_after = {k.lower(): v for k, v in (headers or {}).items()}.get("retry-after")
        if status in (401, 402, 403):
            return ProviderError("REFUSED", message)
        if status == 429:
            # A spend-cap 429 carries no retry-after and keeps failing: do not retry it.
            return ProviderError("UNAVAILABLE" if retry_after else "REFUSED", message, retry_after=retry_after)
        if status in (500, 504, 529):
            return ProviderError("TIMEOUT" if status == 504 else "UNAVAILABLE", message, retry_after=retry_after)
        return ProviderError("INVALID_REQUEST", message)


class OllamaProvider(ModelProvider):
    name = "ollama"
    offline = True

    def __init__(self, model="llama3.1", *, base_url="http://127.0.0.1:11434", http_post=urllib_post_json, timeout=120):
        self.model = model
        self._url = base_url.rstrip("/") + "/api/chat"
        self._post = http_post
        self._timeout = timeout

    def complete(self, request):
        messages = ([{"role": "system", "content": request["system"]}] if request["system"] else []) + request["messages"]
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"num_predict": request["max_tokens"], "temperature": 0}}
        status, _headers, body = self._post(self._url, {}, payload, self._timeout)
        if status == 404:
            raise ProviderError("UNAVAILABLE", f"model {self.model} is not available locally")
        if status != 200:
            raise ProviderError("UNAVAILABLE" if status >= 500 else "INVALID_REQUEST", f"HTTP {status}")
        try:
            data = json.loads(body)
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_RESPONSE", f"unparseable /api/chat response: {exc}")
        return {"text": text, "provider": self.name, "model": data.get("model", self.model),
                "usage": {"input_tokens": int(data.get("prompt_eval_count", 0)),
                          "output_tokens": int(data.get("eval_count", 0))},
                "finish_reason": data.get("done_reason", "stop")}


class ModelRouter:
    """Route a request to providers by task kind, with bounded retry and ordered fallback."""

    def __init__(self, providers, *, routes=None, offline=False, max_retries=1, event_log=None,
                 sleep=time.sleep, monotonic=time.monotonic):
        self._providers = {}
        for provider in providers:
            if not provider.name or provider.name in self._providers:
                raise MAEPError("providers need unique names")
            self._providers[provider.name] = provider
        self._routes = {k: list(v) for k, v in (routes or {}).items()}
        for names in self._routes.values():
            unknown = [n for n in names if n not in self._providers]
            if unknown:
                raise MAEPError("route names unknown providers: " + ", ".join(unknown))
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 3:
            raise MAEPError("max_retries must be 0..3")
        self.offline = offline is True
        self._max_retries = max_retries
        self._log = event_log
        self._sleep = sleep
        self._monotonic = monotonic
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def candidates(self, kind):
        names = self._routes.get(kind) or self._routes.get("default") or list(self._providers)
        return [self._providers[n] for n in names if not self.offline or self._providers[n].offline]

    def available(self, kind="default"):
        return [p.name for p in self.candidates(kind)]

    def complete(self, request, *, kind="default", task_id=None):
        """Return the first successful response; raise ProviderError(UNAVAILABLE) with attempts otherwise."""
        request = make_request(request.get("system", ""), request.get("messages"),
                               max_tokens=request.get("max_tokens", 1024))
        digest = request_digest(request)
        attempts = []
        providers = self.candidates(kind)
        if not providers:
            raise ProviderError("UNAVAILABLE", "no provider configured for this kind"
                                + (" in offline mode" if self.offline else ""))
        for provider in providers:
            for attempt in range(self._max_retries + 1):
                started = self._monotonic()
                try:
                    response = provider.complete(request)
                    if not isinstance(response, dict) or not isinstance(response.get("text"), str):
                        raise ProviderError("INVALID_RESPONSE", "provider returned no text")
                except ProviderError as exc:
                    attempts.append({"provider": provider.name, "attempt": attempt + 1, "error": exc.kind})
                    self._record(task_id, kind, provider, "ERROR", None, started, digest, exc.kind)
                    if exc.kind not in RETRYABLE:
                        break
                    if attempt < self._max_retries:
                        self._sleep(min(float(exc.retry_after or 0.5 * (attempt + 1)), 5.0))
                    continue
                except Exception as exc:  # a provider bug is an unavailable provider, never a crash
                    attempts.append({"provider": provider.name, "attempt": attempt + 1, "error": "UNAVAILABLE"})
                    self._record(task_id, kind, provider, "ERROR", None, started, digest,
                                 f"UNAVAILABLE:{type(exc).__name__}")
                    break
                self._account(provider, response)
                self._record(task_id, kind, provider, "OK", response, started, digest, None)
                return dict(response, attempts=attempts + [{"provider": provider.name, "attempt": attempt + 1,
                                                            "error": None}], request_digest=digest)
        raise ProviderError("UNAVAILABLE", "every provider failed: "
                            + ", ".join(f"{a['provider']}#{a['attempt']}={a['error']}" for a in attempts))

    def _account(self, provider, response):
        usage = response.get("usage") or {}
        tin, tout = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        cin, cout = provider.cost_per_mtok
        self.usage["calls"] += 1
        self.usage["input_tokens"] += tin
        self.usage["output_tokens"] += tout
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + (tin * cin + tout * cout) / 1e6, 6)

    def _record(self, task_id, kind, provider, status, response, started, digest, error):
        if self._log is None:
            return
        payload = {"provider": provider.name, "model": provider.model, "kind": kind, "status": status,
                   "error": error, "duration_ms": int((self._monotonic() - started) * 1000),
                   "request_digest": digest, "offline": provider.offline}
        if response is not None:
            payload["usage"] = response.get("usage")
            payload["finish_reason"] = response.get("finish_reason")
        try:
            self._log.append("MODEL_CALL", task_id, payload)
        except Exception:
            pass   # call accounting must not turn a good answer into a failure
