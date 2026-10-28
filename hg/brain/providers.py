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
    NOT_CONFIGURED   a required setting (e.g. an API key) is missing (not retryable)

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
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from maep.core import MAEPError

ERROR_KINDS = {"UNAVAILABLE", "TIMEOUT", "REFUSED", "INVALID_REQUEST", "INVALID_RESPONSE", "NOT_CONFIGURED"}
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# A local model must never be reached through HTTP(S)_PROXY (urllib honours those variables
# by default, and 127.0.0.1 is only exempt if NO_PROXY says so) or be redirected elsewhere.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def is_loopback_url(url):
    """True only for http://<literal loopback IP>:<port>/... with no user info."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        if parts.scheme != "http" or parts.username or parts.password or host is None:
            return False
        return ipaddress.ip_address(host).is_loopback and parts.port is not None
    except ValueError:
        return False


def _local_request(url, data, timeout):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"content-type": "application/json"} if data is not None else {})
    try:
        return _LOCAL_OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except TimeoutError as exc:
        raise ProviderError("TIMEOUT", str(exc))
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise ProviderError("TIMEOUT", str(reason))
        raise ProviderError("UNAVAILABLE", f"cannot reach {url}: {reason}")


def local_post_json(url, headers, payload, timeout):
    """Like urllib_post_json, but never through a proxy and never following redirects."""
    try:
        with _local_request(url, json.dumps(payload).encode("utf-8"), timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read().decode("utf-8", errors="replace") if exc.fp else ""


def local_post_stream(url, payload, timeout, on_json):
    """POST and call on_json(obj) for each NDJSON line as it arrives. Returns the HTTP status."""
    try:
        with _local_request(url, json.dumps(payload).encode("utf-8"), timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line:
                    try:
                        on_json(json.loads(line))
                    except ValueError as exc:
                        raise ProviderError("INVALID_RESPONSE", f"bad stream line: {exc}")
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def local_get_json(url, timeout):
    try:
        with _local_request(url, None, timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except ValueError as exc:
        raise ProviderError("INVALID_RESPONSE", f"unparseable JSON from {url}: {exc}")


_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)


def strip_thinking(text):
    """Drop <think>...</think> blocks some local models emit before the answer."""
    return _THINK.sub("", text).strip()


class _ThinkFilter:
    """Streaming counterpart of strip_thinking: forwards only text outside <think> blocks.

    A tag may arrive split across chunks ("<thi" + "nk>"), so a trailing fragment that could
    still become a tag is held back until the next chunk decides it.
    """
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self, sink):
        self._sink, self._buf, self._inside = sink, "", False

    @staticmethod
    def _pending(buf, tag):
        """Length of the longest suffix of buf that is a proper prefix of tag."""
        for n in range(min(len(buf), len(tag) - 1), 0, -1):
            if tag.startswith(buf[-n:]):
                return n
        return 0

    def feed(self, text):
        self._buf += text
        out = []
        while self._buf:
            tag = self.CLOSE if self._inside else self.OPEN
            at = self._buf.find(tag)
            if at >= 0:
                if not self._inside:
                    out.append(self._buf[:at])
                self._buf, self._inside = self._buf[at + len(tag):], not self._inside
                continue
            hold = self._pending(self._buf, tag)
            if not self._inside:
                out.append(self._buf[:len(self._buf) - hold])
            self._buf = self._buf[len(self._buf) - hold:] if hold else ""
            break
        text = "".join(out)
        if text:
            self._sink(text)

    def flush(self):
        if self._buf and not self._inside:
            self._sink(self._buf)
        self._buf = ""


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
            raise ProviderError("NOT_CONFIGURED", f"{self._key_env} is not set")
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
    """A local Ollama server. Loopback only unless allow_remote=True is passed explicitly.

    options: Ollama runtime options (num_ctx, num_thread, ...); temperature 0 and num_predict
    come from the request. think: True/False is sent as Ollama's "think" flag when set; any
    <think> block in the output is removed either way. keep_alive: how long Ollama keeps the
    model loaded after the call (e.g. "30m").
    """
    name = "ollama"
    offline = True
    supports_stream = True

    def __init__(self, model="llama3.1", *, base_url="http://127.0.0.1:11434", http_post=local_post_json,
                 stream_post=local_post_stream, timeout=120, options=None, think=None, keep_alive=None,
                 allow_remote=False):
        if not allow_remote and not is_loopback_url(base_url.rstrip("/") + "/"):
            raise MAEPError("Ollama base_url must be http://<loopback IP>:<port> (pass allow_remote=True to override)")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._url = self.base_url + "/api/chat"
        self._post = http_post
        self._stream_post = stream_post
        self._timeout = timeout
        self._options = dict(options or {})
        self._think = think
        self._keep_alive = keep_alive

    def _payload(self, request, stream):
        messages = ([{"role": "system", "content": request["system"]}] if request["system"] else []) + request["messages"]
        payload = {"model": self.model, "messages": messages, "stream": stream,
                   "options": dict(self._options, num_predict=request["max_tokens"], temperature=0)}
        if self._think is not None:
            payload["think"] = self._think
        if self._keep_alive is not None:
            payload["keep_alive"] = self._keep_alive
        return payload

    def complete(self, request, on_delta=None):
        if on_delta is not None:
            return self._complete_stream(request, on_delta)
        status, _headers, body = self._post(self._url, {}, self._payload(request, False), self._timeout)
        self._check_status(status)
        try:
            data = json.loads(body)
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_RESPONSE", f"unparseable /api/chat response: {exc}")
        return self._response(strip_thinking(text), data)

    def _complete_stream(self, request, on_delta):
        parts, final = [], {}
        visible = _ThinkFilter(on_delta)

        def on_json(obj):
            if obj.get("error"):
                raise ProviderError("UNAVAILABLE", str(obj["error"])[:200])
            chunk = (obj.get("message") or {}).get("content") or ""
            if chunk:
                parts.append(chunk)
                visible.feed(chunk)
            if obj.get("done"):
                final.update(obj)

        status = self._stream_post(self._url, self._payload(request, True), self._timeout, on_json)
        self._check_status(status)
        visible.flush()
        if not final:
            raise ProviderError("INVALID_RESPONSE", "stream ended without a final message")
        return self._response(strip_thinking("".join(parts)), final)

    def _check_status(self, status):
        if status == 404:
            raise ProviderError("UNAVAILABLE", f"model {self.model} is not available locally")
        if status != 200:
            raise ProviderError("UNAVAILABLE" if status >= 500 else "INVALID_REQUEST", f"HTTP {status}")

    def _response(self, text, data):
        return {"text": text, "provider": self.name, "model": data.get("model", self.model),
                "usage": {"input_tokens": int(data.get("prompt_eval_count", 0)),
                          "output_tokens": int(data.get("eval_count", 0))},
                "finish_reason": data.get("done_reason", "stop")}

    def tags(self, *, get_json=local_get_json, timeout=5):
        """Locally available models: [{name, digest, size}] (GET /api/tags)."""
        status, data = get_json(self.base_url + "/api/tags", timeout)
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ProviderError("UNAVAILABLE", f"/api/tags answered HTTP {status}")
        return [{"name": m.get("name"), "digest": m.get("digest"), "size": m.get("size")}
                for m in data["models"] if isinstance(m, dict)]


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

    def complete(self, request, *, kind="default", task_id=None, on_delta=None):
        """Return the first successful response; raise ProviderError(UNAVAILABLE) with attempts otherwise.

        on_delta(text) receives visible text as it is produced. A provider without streaming
        gets one call with the whole text. Once any text has been shown, the call is never
        retried or handed to another provider: the reader would see two different answers.
        """
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
                shown = []

                def relay(text, _shown=shown):
                    _shown.append(text)
                    on_delta(text)
                try:
                    if on_delta is not None and getattr(provider, "supports_stream", False):
                        response = provider.complete(request, on_delta=relay)
                    else:
                        response = provider.complete(request)
                    if not isinstance(response, dict) or not isinstance(response.get("text"), str):
                        raise ProviderError("INVALID_RESPONSE", "provider returned no text")
                    if on_delta is not None and not getattr(provider, "supports_stream", False):
                        on_delta(response["text"])
                except ProviderError as exc:
                    attempts.append({"provider": provider.name, "attempt": attempt + 1, "error": exc.kind})
                    self._record(task_id, kind, provider, "ERROR", None, started, digest, exc.kind)
                    if shown:
                        raise ProviderError(exc.kind, "the answer stopped part-way: " + str(exc))
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
