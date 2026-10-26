"""Fail-closed HTTP transport for the existing HG runtime.

This module is only a transport adapter: BrainOrchestrator remains the sole task
coordinator, MemoryStore remains the task/state owner, and NativePolicyEngine remains
the authority. No authentication, trust-root, policy, evidence or ledger defaults exist.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import re
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from brain.orchestrator import OrchestrationError
from maep.core import MAEPError
from maep.native_authority import AuthorityError

MAX_BODY_BYTES = 1_048_576
# Two different limits on reading a request (request line, headers, body):
# - REQUEST_TIMEOUT_SECONDS bounds each socket read (silence). Same value as hg serve.
# - REQUEST_DEADLINE_SECONDS bounds the whole read on the monotonic clock, so a client
#   that sends a byte just before every per-read timeout ("slow drip") cannot hold a
#   handler thread indefinitely. No HG contract fixes a value; 15 s is three read
#   timeouts, far above a loopback client sending at most MAX_BODY_BYTES.
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_REQUEST_TIMEOUT_SECONDS = 60.0
REQUEST_DEADLINE_SECONDS = 15.0
MAX_REQUEST_DEADLINE_SECONDS = 120.0
# Concurrent connections (one handler thread each). The deadline bounds how long a
# connection lasts; this bounds how many exist. Beyond it the server answers 503.
MAX_CONNECTIONS = 32
MAX_CONNECTIONS_LIMIT = 256
_BUSY_BODY = b'{"error":"server_busy","status":"BLOCKED"}'
_BUSY_RESPONSE = (b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
                  b"Content-Length: " + str(len(_BUSY_BODY)).encode() + b"\r\nCache-Control: no-store\r\n"
                  b"Connection: close\r\n\r\n" + _BUSY_BODY)
_TASK_PATH = re.compile(r"^/api/tasks/([^/]+)$")
_TRANSITION_PATH = re.compile(r"^/api/tasks/([^/]+)/transition$")
_REVIEW_PATH = re.compile(r"^/api/tasks/([^/]+)/review-and-simulate$")
_EVIDENCE_PATH = "/api/evidence"


class _DeadlineSocketReader(io.RawIOBase):
    """Raw reader: every recv is bounded by the per-read timeout and the request deadline."""

    def __init__(self, sock, *, read_timeout, deadline):
        super().__init__()
        self._sock = sock
        self._read_timeout = read_timeout
        self._deadline = deadline
        self.deadline_exceeded = False

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.deadline_exceeded = True
            raise TimeoutError("request deadline exceeded")
        self._sock.settimeout(min(self._read_timeout, remaining))
        try:
            return self._sock.recv_into(buffer)
        except TimeoutError:
            if time.monotonic() >= self._deadline:
                self.deadline_exceeded = True
            raise


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a fixed number of concurrent handler threads."""
    daemon_threads = True

    def __init__(self, address, handler, *, max_connections):
        self._slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(1.0)
                request.sendall(_BUSY_RESPONSE)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class HTTPBoundaryError(RuntimeError):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class HGHTTPServer:
    """Loopback-first HTTP wrapper around an explicitly composed HGRuntime.

    authenticate_request(headers) must be an owner-approved authenticator returning
    the authenticated context. That context must match the runtime's context provider;
    otherwise all protected routes fail closed. The candidate-target provider is the
    same dependency used by the existing runtime composition.
    """

    def __init__(self, *, runtime, authenticate_request, host="127.0.0.1", port=0,
                 max_body_bytes=MAX_BODY_BYTES, request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                 request_deadline_seconds=REQUEST_DEADLINE_SECONDS, max_connections=MAX_CONNECTIONS):
        if runtime is None or not callable(authenticate_request):
            raise HTTPBoundaryError(503, "runtime_and_authenticator_required")
        if host != "127.0.0.1":
            raise HTTPBoundaryError(400, "only_loopback_bind_is_supported")
        if not callable(getattr(runtime, "authenticated_context_provider", None)):
            raise HTTPBoundaryError(503, "runtime_context_provider_unavailable")
        if not callable(getattr(runtime, "candidate_target_provider", None)):
            raise HTTPBoundaryError(503, "candidate_target_provider_unavailable")
        if not callable(getattr(getattr(runtime, "brain", None), "dispatch", None)):
            raise HTTPBoundaryError(503, "brain_dispatch_unavailable")
        memory = getattr(runtime, "memory", None)
        if memory is None or not all(callable(getattr(memory, name, None)) for name in (
            "create_task", "get_task", "transition_task", "record_evidence"
        )):
            raise HTTPBoundaryError(503, "canonical_memory_task_api_unavailable")
        if not isinstance(max_body_bytes, int) or isinstance(max_body_bytes, bool) or not 1 <= max_body_bytes <= MAX_BODY_BYTES:
            raise HTTPBoundaryError(400, "invalid_request_size_limit")
        if (not isinstance(request_timeout_seconds, (int, float)) or isinstance(request_timeout_seconds, bool)
                or not 0 < request_timeout_seconds <= MAX_REQUEST_TIMEOUT_SECONDS):
            raise HTTPBoundaryError(400, "invalid_request_timeout")
        self.request_timeout_seconds = float(request_timeout_seconds)
        if (not isinstance(request_deadline_seconds, (int, float)) or isinstance(request_deadline_seconds, bool)
                or not self.request_timeout_seconds <= request_deadline_seconds <= MAX_REQUEST_DEADLINE_SECONDS):
            raise HTTPBoundaryError(400, "invalid_request_deadline")
        self.request_deadline_seconds = float(request_deadline_seconds)
        if (not isinstance(max_connections, int) or isinstance(max_connections, bool)
                or not 1 <= max_connections <= MAX_CONNECTIONS_LIMIT):
            raise HTTPBoundaryError(400, "invalid_connection_limit")
        self.max_connections = max_connections
        self.runtime = runtime
        self.authenticate_request = authenticate_request
        self.max_body_bytes = max_body_bytes
        self.httpd = _BoundedThreadingHTTPServer((host, port), self._handler_type(),
                                                 max_connections=max_connections)

    @property
    def address(self):
        return self.httpd.server_address

    def serve_forever(self):
        self.httpd.serve_forever(poll_interval=0.2)

    def shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _validate_host(self, headers):
        try:
            values = headers.get_all("Host", [])
        except Exception as exc:
            raise HTTPBoundaryError(400, "host_header_invalid") from exc
        if not isinstance(values, list) or len(values) != 1:
            raise HTTPBoundaryError(400, "host_header_invalid")
        # Exact canonical values reject userinfo, path/query suffixes, empty ports,
        # malformed numeric ports, trailing dots and duplicate/ambiguous host syntax.
        if values[0] != f"127.0.0.1:{self.address[1]}":
            raise HTTPBoundaryError(400, "host_header_invalid")

    def _context(self, headers):
        self._validate_host(headers)
        try:
            context = self.authenticate_request(headers)
            current = self.runtime.authenticated_context_provider()
        except Exception as exc:
            raise HTTPBoundaryError(401, "authentication_unavailable_or_denied") from exc
        if context is None or current is None or context != current:
            raise HTTPBoundaryError(403, "authenticated_context_not_bound_to_runtime")
        return context

    def _candidate(self, request):
        try:
            target = self.runtime.candidate_target_provider(request)
            candidate = self.runtime.authority.candidate_provider.inspect(target)
        except Exception as exc:
            raise HTTPBoundaryError(503, "candidate_identity_unavailable") from exc
        if (not isinstance(candidate, dict) or candidate.get("verified") is not True
                or candidate.get("repository") != "OAI-GIANG/HG"
                or not isinstance(candidate.get("candidate_ref"), str)
                or not candidate.get("candidate_ref")):
            raise HTTPBoundaryError(403, "candidate_identity_unverified")
        return target, candidate["candidate_ref"]

    def _handler_type(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HG-HTTP"
            sys_version = ""
            # StreamRequestHandler.setup() applies this to the connection socket; a stalled
            # request line/headers raises TimeoutError, which closes the connection.
            timeout = service.request_timeout_seconds

            def setup(self):
                super().setup()
                # Replace the buffered reader so every read of request line, headers and
                # body also honours the total deadline. A deadline hit while reading the
                # request line or headers closes the connection without a response (the
                # request never completed); a hit while reading the body answers 408.
                self.rfile.close()          # releases the makefile() reference, not the socket
                self._request_reader = _DeadlineSocketReader(
                    self.connection, read_timeout=service.request_timeout_seconds,
                    deadline=time.monotonic() + service.request_deadline_seconds)
                self.rfile = io.BufferedReader(self._request_reader)

            def log_message(self, fmt, *args):
                # Avoid leaking request bodies, bearer material or provider details.
                return

            def send_error(self, code, message=None, explain=None):
                # Never expose BaseHTTPRequestHandler's default HTML error pages.
                if code in (400, 501, 405):
                    try:
                        service._validate_host(self.headers)
                    except HTTPBoundaryError as exc:
                        self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                        return
                    if code in (501, 405):
                        self._send(405, {"status": "BLOCKED", "error": "METHOD_NOT_ALLOWED"},
                                   extra_headers={"Allow": "GET, POST"})
                        return
                    self._send(400, {"status": "BLOCKED", "error": "HTTP_REQUEST_REJECTED"})
                    return
                self._send(code, {"status": "BLOCKED", "error": "HTTP_REQUEST_REJECTED"})

            def _send(self, status, value, extra_headers=None):
                raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
                # Reads may have left a near-zero timeout on the socket; writes get the
                # normal per-operation timeout.
                self.connection.settimeout(service.request_timeout_seconds)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    for header_name, header_value in (extra_headers or {}).items():
                        self.send_header(header_name, header_value)
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    # The client went away or stopped reading; nothing left to tell it.
                    self.close_connection = True

            def _body(self):
                if self.headers.get_content_type() != "application/json":
                    raise HTTPBoundaryError(415, "application_json_required")
                length = self.headers.get("Content-Length")
                try:
                    size = int(length)
                except (TypeError, ValueError) as exc:
                    raise HTTPBoundaryError(411, "content_length_required") from exc
                if size < 1 or size > service.max_body_bytes:
                    raise HTTPBoundaryError(413, "request_body_size_invalid")
                try:
                    raw = self.rfile.read(size)
                except TimeoutError as exc:
                    self.close_connection = True
                    code = ("request_deadline_exceeded" if self._request_reader.deadline_exceeded
                            else "request_body_timeout")
                    raise HTTPBoundaryError(408, code) from exc
                if len(raw) != size:
                    raise HTTPBoundaryError(400, "incomplete_request_body")
                try:
                    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    raise HTTPBoundaryError(400, "invalid_json") from exc
                if not isinstance(value, dict):
                    raise HTTPBoundaryError(400, "json_object_required")
                return value

            def _protected(self):
                return service._context(self.headers)

            def _run(self, method, *, key_error_status=400):
                try:
                    result = method()
                    self._send(200, {"status": "OK", "result": result})
                except HTTPBoundaryError as exc:
                    self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                except OrchestrationError as exc:
                    message = str(exc)
                    if message.startswith("IN_PROGRESS:"):
                        self._send(409, {"status": "IN_PROGRESS", "error": "IDEMPOTENCY_IN_PROGRESS"})
                    elif message.startswith("CONFLICT:"):
                        self._send(409, {"status": "BLOCKED", "error": "IDEMPOTENCY_CONFLICT"})
                    elif message.startswith("OUTCOME_UNKNOWN:"):
                        self._send(409, {"status": "UNKNOWN", "error": "IDEMPOTENCY_RECONCILIATION_REQUIRED"})
                    else:
                        self._send(403, {"status": "BLOCKED", "error": "MAEP_AUTHORIZATION_OR_CONTRACT_DENIED"})
                except (MAEPError, AuthorityError):
                    self._send(403, {"status": "BLOCKED", "error": "MAEP_AUTHORIZATION_OR_CONTRACT_DENIED"})
                except KeyError:
                    self._send(key_error_status, {"status": "BLOCKED", "error": "NOT_FOUND" if key_error_status == 404 else "INVALID_REQUEST"})
                except (TypeError, ValueError):
                    self._send(400, {"status": "BLOCKED", "error": "INVALID_REQUEST"})
                except Exception:
                    self._send(500, {"status": "BLOCKED", "error": "RUNTIME_OPERATION_FAILED"})

            def do_GET(self):
                try:
                    service._validate_host(self.headers)
                except HTTPBoundaryError as exc:
                    return self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                parsed = urlsplit(self.path)
                if parsed.path == "/health":
                    return self._send(200, {"status": "LIVE", "policy_version": "MAEP-1.2.0"})
                if parsed.path == "/health/ready":
                    try:
                        service._context(self.headers)
                    except HTTPBoundaryError as exc:
                        return self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                    provider = getattr(service.runtime, "readiness_provider", None)
                    if not callable(provider):
                        return self._send(503, {"status": "NOT_READY", "error": "readiness_evidence_unavailable"})
                    try:
                        readiness = provider()
                    except Exception:
                        readiness = None
                    if not isinstance(readiness, dict) or readiness.get("release") != "VERIFIED" or readiness.get("trust") != "LOADED":
                        return self._send(503, {"status": "NOT_READY", "error": "release_or_trust_not_ready"})
                    return self._send(200, {"status": "READY", "release": "VERIFIED", "trust": "LOADED"})
                if parsed.path == "/api/tasks":
                    try:
                        service._context(self.headers)
                        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                        if set(query) - {"index_scope_task_id", "limit", "offset"}:
                            raise HTTPBoundaryError(400, "task_index_query_fields_invalid")
                        scope_values = query.get("index_scope_task_id", [])
                        if len(scope_values) != 1 or not scope_values[0].strip():
                            raise HTTPBoundaryError(400, "task_index_scope_required")
                        def integer_query(name, default):
                            values = query.get(name, [str(default)])
                            if len(values) != 1 or not re.fullmatch(r"(?:0|[1-9][0-9]*)", values[0]):
                                raise HTTPBoundaryError(400, "task_index_pagination_invalid")
                            return int(values[0])
                        limit = integer_query("limit", 100)
                        offset = integer_query("offset", 0)
                        if not 1 <= limit <= 500:
                            raise HTTPBoundaryError(400, "task_index_pagination_invalid")
                    except HTTPBoundaryError as exc:
                        return self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                    except ValueError:
                        return self._send(400, {"status": "BLOCKED", "error": "task_index_query_invalid"})
                    scope_task_id = scope_values[0]
                    return self._run(lambda: service.runtime.memory.list_tasks(
                        index_scope_task_id=scope_task_id, limit=limit, offset=offset))
                # All non-public GET paths authenticate before route recognition so
                # protected route existence and path validation are not disclosed.
                try:
                    context = service._context(self.headers)
                except HTTPBoundaryError as exc:
                    return self._send(exc.status, {"status": "BLOCKED", "error": exc.code})
                if parsed.query or parsed.fragment or "%" in parsed.path:
                    return self._send(400, {"status": "BLOCKED", "error": "invalid_path"})
                match = _TASK_PATH.fullmatch(parsed.path)
                if match is None:
                    return self._send(404, {"status": "BLOCKED", "error": "NOT_FOUND"})
                task_id = unquote(match.group(1))
                return self._run(lambda: service.runtime.memory.get_task(task_id), key_error_status=404)

            def do_POST(self):
                try:
                    service._validate_host(self.headers)
                    context = self._protected()
                    body = self._body()
                    parsed = urlsplit(self.path)
                    if parsed.path == "/api/dispatch":
                        if set(body) != {"request", "adapter_name", "idempotency_key"}:
                            raise HTTPBoundaryError(400, "dispatch_fields_invalid")
                        request = body["request"]
                        if not isinstance(request, dict):
                            raise HTTPBoundaryError(400, "dispatch_request_object_required")
                        target, _ = service._candidate(request)
                        return self._run(lambda: service.runtime.brain.dispatch(
                            request=request, authenticated_context=context,
                            candidate_target=target, adapter_name=body["adapter_name"],
                            idempotency_key=body["idempotency_key"]))
                    if parsed.path == "/api/reconcile":
                        if (set(body) != {"task_ref", "idempotency_key"}
                                or not all(isinstance(body[k], str) and body[k] for k in body)):
                            raise HTTPBoundaryError(400, "reconcile_fields_invalid")
                        request = {"action": "READ", "resource": "reconcile", "scope": [],
                                   "task_ref": body["task_ref"]}
                        target, _ = service._candidate(request)
                        return self._run(lambda: service.runtime.brain.reconcile(
                            task_ref=body["task_ref"], idempotency_key=body["idempotency_key"],
                            authenticated_context=context, candidate_target=target))
                    if parsed.path == "/api/tasks":
                        if set(body) != {"task"} or not isinstance(body["task"], dict):
                            raise HTTPBoundaryError(400, "task_fields_invalid")
                        task = body["task"]
                        task_id = task.get("task_id")
                        if not isinstance(task_id, str) or not task_id.strip():
                            raise HTTPBoundaryError(400, "task_id_required")
                        request = {"action": "WRITE", "resource": f"memory:task/{task_id}",
                                   "scope": [f"memory:task:{task_id}:write"], "task_ref": task_id}
                        _, candidate_ref = service._candidate(request)
                        return self._run(lambda: service.runtime.memory.create_task(task, candidate_ref=candidate_ref))
                    review_match = _REVIEW_PATH.fullmatch(parsed.path)
                    if review_match is not None:
                        allowed = {"plan", "claims", "evidence_refs", "assumptions", "constraints", "scenario_request"}
                        if not {"plan"}.issubset(body) or set(body) - allowed or not isinstance(body.get("plan"), dict):
                            raise HTTPBoundaryError(400, "review_fields_invalid")
                        brain = service.runtime.brain
                        if not callable(getattr(brain, "review_and_simulate", None)) or getattr(brain, "critique_engine", None) is None:
                            raise HTTPBoundaryError(503, "critique_provider_unavailable")
                        scenario_request = body.get("scenario_request")
                        if scenario_request is not None and getattr(brain, "scenario_engine", None) is None:
                            raise HTTPBoundaryError(503, "scenario_engine_unavailable")
                        task_id = unquote(review_match.group(1))
                        if not task_id.strip() or body["plan"].get("task_id") != task_id:
                            raise HTTPBoundaryError(400, "review_task_identity_mismatch")
                        request = {
                            "action": "READ", "resource": f"memory:task/{task_id}",
                            "scope": [], "task_ref": task_id,
                        }
                        target, _ = service._candidate(request)
                        return self._run(lambda: brain.review_and_simulate(
                            task_ref=task_id, candidate_target=target, plan=body["plan"],
                            scenario_request=scenario_request, claims=body.get("claims"),
                            evidence_refs=body.get("evidence_refs"), assumptions=body.get("assumptions"),
                            constraints=body.get("constraints"),
                        ))
                    match = _TRANSITION_PATH.fullmatch(parsed.path)
                    if match is not None:
                        allowed = {"target", "expected_version", "resolution_evidence_ref", "action_request", "trigger"}
                        if not {"target", "expected_version"}.issubset(body) or not set(body).issubset(allowed):
                            raise HTTPBoundaryError(400, "transition_fields_invalid")
                        task_id = unquote(match.group(1))
                        return self._run(lambda: service.runtime.memory.transition_task(
                            task_id, body["target"], expected_version=body["expected_version"],
                            resolution_evidence_ref=body.get("resolution_evidence_ref"),
                            action_request=body.get("action_request"), trigger=body.get("trigger", "http")))
                    if parsed.path == _EVIDENCE_PATH:
                        if set(body) != {"task_id", "evidence"} or not isinstance(body["task_id"], str) or not isinstance(body["evidence"], dict):
                            raise HTTPBoundaryError(400, "evidence_fields_invalid")
                        return self._run(lambda: service.runtime.memory.record_evidence(body["task_id"], body["evidence"]))
                    raise HTTPBoundaryError(404, "NOT_FOUND")
                except HTTPBoundaryError as exc:
                    self._send(exc.status, {"status": "BLOCKED", "error": exc.code})

        return Handler
