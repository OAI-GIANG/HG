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

Model-server bytes are read with one meaning or refused as INVALID_RESPONSE (model response
read oracle, hg/tests/test_model_response_oracle.py): bounded reads, UTF-8 only, no repeated
JSON keys, JSON objects where objects are expected, string text, non-negative integer token
counts, nothing after a stream's final message.

Router accounting reconciles with its calls (router budget reconciliation oracle,
hg/tests/test_router_budget_reconciliation_oracle.py): an answer's usage must be an object
of non-negative integer token counts or the answer is INVALID_RESPONSE; prices are checked
when the router is built; cost_usd is the exact sum of call costs, rounded once.
"""
import hashlib
import ipaddress
import json
import math
import os
import re
import time
from fractions import Fraction
import urllib.error
import urllib.parse
import urllib.request

from maep.core import MAEPError

from hg.json_depth import MAX_JSON_DEPTH, json_depth_exceeds

ERROR_KINDS = {"UNAVAILABLE", "TIMEOUT", "REFUSED", "INVALID_REQUEST", "INVALID_RESPONSE", "NOT_CONFIGURED"}
RETRYABLE = {"UNAVAILABLE", "TIMEOUT", "INVALID_RESPONSE"}

MAX_RESPONSE_BYTES = 8 * 1024 * 1024        # one non-streamed answer body
MAX_STREAM_LINE_BYTES = 1024 * 1024         # one NDJSON line of a streamed answer
MAX_STREAM_BYTES = 64 * 1024 * 1024         # a whole streamed answer (64000 tokens of small lines)
MAX_ERROR_BYTES = 64 * 1024                 # an HTTP error body (only a message is read from it)


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


def _reject_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"repeated JSON key {key!r}")
        obj[key] = value
    return obj


def _refuse_deep(text):
    if json_depth_exceeds(text):
        raise ValueError(f"JSON nests deeper than {MAX_JSON_DEPTH} levels")


def parse_json(text):
    """json.loads that refuses repeated keys (raises ValueError): one body, one reading.

    Nesting deeper than MAX_JSON_DEPTH is a ValueError before json.loads runs: the C
    parser recurses per level and a model reply parsed on a worker thread must not be
    able to overflow its stack (SIGSEGV on Termux).
    """
    _refuse_deep(text)
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


def _reject_constant(name):
    raise ValueError(f"non-standard JSON number {name}")


def parse_model_json(text):
    """Read JSON a model wrote as data HG will act on: one reading or ValueError.

    Repeated keys, NaN/Infinity and strings that are not valid Unicode text (a lone
    surrogate escape such as \\ud800, which UTF-8 cannot encode and the ledger cannot
    record) are refused, so every reader of the answer sees the same plan.
    """
    _refuse_deep(text)
    data = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    try:
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("JSON string is not valid Unicode text (lone surrogate)") from None
    return data


def read_bounded(resp, limit=MAX_RESPONSE_BYTES, what="response"):
    """Read at most `limit` bytes and decode them as UTF-8, or raise INVALID_RESPONSE."""
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise ProviderError("INVALID_RESPONSE", f"{what} is larger than {limit} bytes")
    return _utf8(data, what)


def _utf8(data, what):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderError("INVALID_RESPONSE", f"{what} is not UTF-8: {exc.reason} at byte {exc.start}")


def _error_body(exc):
    return exc.read(MAX_ERROR_BYTES).decode("utf-8", errors="replace") if exc.fp else ""


def token_count(value):
    """A token count is a non-negative int (not bool); callers pass 0 for an absent field, null is refused."""
    if value is None:
        raise ProviderError("INVALID_RESPONSE", "token count is null")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderError("INVALID_RESPONSE", f"token count must be a non-negative integer, got {value!r}")
    return value


def _optional_str(data, key, default):
    value = data.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ProviderError("INVALID_RESPONSE", f"{key} must be a string")
    return value


def urllib_post_json(url, headers, payload, timeout):
    """POST JSON; returns (status, headers_dict, text). Network errors raise ProviderError."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=dict(headers, **{"content-type": "application/json"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), read_bounded(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), _error_body(exc)
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
            return resp.status, dict(resp.headers), read_bounded(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), _error_body(exc)


def local_post_stream(url, payload, timeout, on_json):
    """POST and call on_json(obj) for each NDJSON line as it arrives. Returns the HTTP status.

    Each line must be one UTF-8 JSON object without repeated keys, at most
    MAX_STREAM_LINE_BYTES long; the whole stream at most MAX_STREAM_BYTES.
    """
    try:
        with _local_request(url, json.dumps(payload).encode("utf-8"), timeout) as resp:
            total = 0
            while True:
                raw = resp.readline(MAX_STREAM_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_STREAM_LINE_BYTES:
                    raise ProviderError("INVALID_RESPONSE", f"stream line longer than {MAX_STREAM_LINE_BYTES} bytes")
                total += len(raw)
                if total > MAX_STREAM_BYTES:
                    raise ProviderError("INVALID_RESPONSE", f"stream larger than {MAX_STREAM_BYTES} bytes")
                line = _utf8(raw, "stream line").strip()
                if line:
                    try:
                        obj = parse_json(line)
                    except ValueError as exc:
                        raise ProviderError("INVALID_RESPONSE", f"bad stream line: {exc}")
                    if not isinstance(obj, dict):
                        raise ProviderError("INVALID_RESPONSE", "stream line is not a JSON object")
                    on_json(obj)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def local_get_json(url, timeout):
    try:
        with _local_request(url, None, timeout) as resp:
            return resp.status, parse_json(read_bounded(resp))
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
            data = parse_json(body)
            if not isinstance(data, dict) or not isinstance(data["content"], list):
                raise TypeError("content must be a list in a JSON object")
            texts = [b.get("text", "") for b in data["content"] if isinstance(b, dict) and b.get("type") == "text"]
            if not all(isinstance(t, str) for t in texts):
                raise TypeError("text blocks must carry string text")
            usage = data.get("usage", {})
            if not isinstance(usage, dict):
                raise TypeError("usage must be a JSON object")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_RESPONSE", f"unparseable Messages API response: {exc}")
        finish = _optional_str(data, "stop_reason", None)
        if finish == "refusal":
            raise ProviderError("REFUSED", "the model declined the request")
        return {"text": "".join(texts), "provider": self.name, "model": _optional_str(data, "model", self.model),
                "usage": {"input_tokens": token_count(usage.get("input_tokens", 0)),
                          "output_tokens": token_count(usage.get("output_tokens", 0))},
                "finish_reason": finish}

    @staticmethod
    def _error(status, headers, body):
        try:
            message = str(parse_json(body)["error"]["message"])[:500]
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
            data = parse_json(body)
            text = data["message"]["content"]
            if not isinstance(data, dict) or not isinstance(text, str):
                raise TypeError("message.content must be a string")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_RESPONSE", f"unparseable /api/chat response: {exc}")
        return self._response(strip_thinking(text), data)

    def _complete_stream(self, request, on_delta):
        parts, final = [], {}
        visible = _ThinkFilter(on_delta)

        def on_json(obj):
            if final:
                raise ProviderError("INVALID_RESPONSE", "stream continued after its final message")
            if obj.get("error"):
                raise ProviderError("UNAVAILABLE", str(obj["error"])[:200])
            message = obj.get("message")
            message = {} if message is None else message
            done = obj.get("done", False)
            if not isinstance(message, dict) or not isinstance(done, bool):
                raise ProviderError("INVALID_RESPONSE", "stream line needs an object message and a boolean done")
            chunk = message.get("content")
            chunk = "" if chunk is None else chunk
            if not isinstance(chunk, str):
                raise ProviderError("INVALID_RESPONSE", "message.content must be a string")
            if done:
                self._response("", obj)            # refuse a bad final line before accepting it
            if chunk:
                parts.append(chunk)
                visible.feed(chunk)
            if done:
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
        return {"text": text, "provider": self.name, "model": _optional_str(data, "model", self.model),
                "usage": {"input_tokens": token_count(data.get("prompt_eval_count", 0)),
                          "output_tokens": token_count(data.get("eval_count", 0))},
                "finish_reason": _optional_str(data, "done_reason", "stop")}

    def tags(self, *, get_json=local_get_json, timeout=5):
        """Locally available models: [{name, digest, size}] (GET /api/tags)."""
        status, data = get_json(self.base_url + "/api/tags", timeout)
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ProviderError("UNAVAILABLE", f"/api/tags answered HTTP {status}")
        return [{"name": m.get("name"), "digest": m.get("digest"), "size": m.get("size")}
                for m in data["models"] if isinstance(m, dict)]


def _price(value):
    """A provider price: (input, output) USD per million tokens, finite and non-negative."""
    if not isinstance(value, tuple) or len(value) != 2 or not all(
            not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in value):
        raise MAEPError(f"cost_per_mtok must be a pair of finite non-negative numbers, got {value!r}")
    return (value[0], value[1])


def _usage_tokens(usage):
    """(input, output) tokens of one answer. Usage must be an object; an absent count is 0."""
    if not isinstance(usage, dict):
        raise ProviderError("INVALID_RESPONSE", "usage must be an object of token counts")
    return token_count(usage.get("input_tokens", 0)), token_count(usage.get("output_tokens", 0))


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
        self._prices = {name: _price(p.cost_per_mtok) for name, p in self._providers.items()}
        self._spend = {}    # (cin, cout) -> [input_tokens, output_tokens], summed exactly
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
                    tokens = _usage_tokens(response.get("usage"))
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
                    if shown:      # same rule as above: never a second answer after a partial one
                        raise ProviderError("UNAVAILABLE", "the answer stopped part-way: provider error "
                                            + type(exc).__name__)
                    break
                self._account(provider, tokens)
                self._record(task_id, kind, provider, "OK", response, started, digest, None)
                return dict(response, attempts=attempts + [{"provider": provider.name, "attempt": attempt + 1,
                                                            "error": None}], request_digest=digest)
        raise ProviderError("UNAVAILABLE", "every provider failed: "
                            + ", ".join(f"{a['provider']}#{a['attempt']}={a['error']}" for a in attempts))

    def _account(self, provider, tokens):
        """Add one successful call. Tokens are summed as integers per price, and cost_usd is
        computed from those sums exactly, then rounded once: it equals the sum of the call
        costs however many small calls there are (router budget reconciliation oracle)."""
        tin, tout = tokens
        spent = self._spend.setdefault(self._prices[provider.name], [0, 0])
        spent[0] += tin
        spent[1] += tout
        self.usage["calls"] += 1
        self.usage["input_tokens"] += tin
        self.usage["output_tokens"] += tout
        exact = sum((Fraction(cin) * i + Fraction(cout) * o for (cin, cout), (i, o) in self._spend.items()),
                    Fraction(0))
        self.usage["cost_usd"] = round(float(exact / 1_000_000), 6)

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
