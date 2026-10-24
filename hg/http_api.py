"""Authenticated, loopback-only HTTP adapter for the existing HG runtime."""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import re
import sqlite3
import threading
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from maep.core import MAEPError


class HTTPBoundaryError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(data: bytes):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("invalid JSON constant")))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HTTPBoundaryError(400, "invalid_json", "request body is not strict UTF-8 JSON") from exc


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _safe_task_steps(task, steps):
    if not isinstance(task, dict) or not isinstance(steps, list) or not steps or len(steps) > 100:
        raise HTTPBoundaryError(400, "invalid_task", "task must be an object and steps must be a non-empty array")
    scope = task.get("scope")
    if not isinstance(scope, dict) or scope.get("include") != ["out/"] or scope.get("exclude") != []:
        raise HTTPBoundaryError(403, "scope_denied", "HTTP task scope must be exactly out/")
    for step in steps:
        if not isinstance(step, dict):
            raise HTTPBoundaryError(400, "invalid_step", "every step must be an object")
        tool, action = step.get("tool"), step.get("action")
        if (tool, action) not in {("fs.write", "WRITE"), ("fs.read", "READ")}:
            raise HTTPBoundaryError(403, "tool_disabled", "HTTP service exposes only fs.read and fs.write")
        params = step.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("path"), str):
            raise HTTPBoundaryError(400, "invalid_step", "step params must include a path")
        path = params["path"]
        pp = PurePosixPath(path)
        if (pp.is_absolute() or pp.as_posix() != path or not path.startswith("out/") or
                any(part in ("", ".", "..") for part in pp.parts) or
                any(ord(char) < 32 or ord(char) == 127 for char in path) or
                "\\" in path or "\x00" in path):
            raise HTTPBoundaryError(403, "scope_denied", "step path must be a normalized path under out/")
        expected_resource = "file:" + pp.as_posix()
        if step.get("resource") != expected_resource or step.get("scope") != ["out/"]:
            raise HTTPBoundaryError(403, "scope_denied", "resource and scope must match the normalized out/ path")
        if tool == "fs.write" and (set(params) != {"path", "content"} or not isinstance(params.get("content"), str)):
            raise HTTPBoundaryError(400, "invalid_step", "fs.write accepts only path and string content")
        if tool == "fs.read" and set(params) != {"path"}:
            raise HTTPBoundaryError(400, "invalid_step", "fs.read accepts only path")
    if set(scope) != {"include", "exclude"}:
        raise HTTPBoundaryError(400, "invalid_scope", "task scope must contain only include and exclude")
    criteria = task.get("acceptance_criteria")
    if (not isinstance(criteria, list) or len(criteria) != 1 or
            not isinstance(criteria[0], dict) or criteria[0].get("criterion_id") != "AC-READBACK" or
            criteria[0].get("mandatory") is not True or
            not isinstance(criteria[0].get("evidence_types"), list) or
            "TEST_RESULT" not in criteria[0].get("evidence_types", [])):
        raise HTTPBoundaryError(400, "unsupported_acceptance",
                                "HTTP tasks require one mandatory AC-READBACK TEST_RESULT criterion")
    if not any(step.get("tool") == "fs.write" for step in steps):
        raise HTTPBoundaryError(400, "missing_write", "HTTP task requires at least one fs.write step")
    return task, steps


def planned_write_readback_verifier(root):
    """Verify each planned write by reading the actual target from the confined root."""
    root = Path(root).resolve()

    def verify(snapshot):
        writes = [s for s in snapshot.get("plan", [])
                  if s.get("tool") == "fs.write" and s.get("action") == "WRITE"]
        if not writes:
            return False, "no fs.write step was recorded"
        for step in writes:
            params = step.get("params", {})
            rel = PurePosixPath(params.get("path", ""))
            if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
                return False, "planned path is not normalized"
            target = (root / Path(*rel.parts)).resolve()
            if target != root and root not in target.parents:
                return False, "planned target escaped root"
            cursor = root
            for part in rel.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    return False, f"read-back path contains a symlink: {rel.as_posix()}"
            if not target.is_file():
                return False, f"read-back target missing or not a regular file: {rel.as_posix()}"
            try:
                actual = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                return False, f"read-back failed ({type(exc).__name__})"
            if actual != params.get("content"):
                return False, f"read-back differs from planned content: {rel.as_posix()}"
        return True, f"read-back matched {len(writes)} planned write(s)"

    verify.__name__ = "planned_write_readback"
    return verify


class IdempotencyStore:
    """SQLite-backed idempotency receipts; ambiguous crashes remain IN_DOUBT."""
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                idem_key TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                state TEXT NOT NULL,
                response_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._db.commit()

    def begin(self, key, digest):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT digest,state,response_json FROM requests WHERE idem_key=?", (key,)
                ).fetchone()
                if row:
                    self._db.commit()
                    old_digest, state, response = row
                    if old_digest != digest:
                        return "CONFLICT", None
                    if state == "COMPLETE":
                        return "REPLAY", json.loads(response)
                    return "IN_DOUBT", None
                self._db.execute(
                    "INSERT INTO requests(idem_key,digest,state) VALUES(?,?, 'STARTED')",
                    (key, digest))
                self._db.commit()
                return "NEW", None
            except Exception:
                self._db.rollback()
                raise

    def finish(self, key, response):
        raw = canonical_json(response).decode("utf-8")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._db.execute("UPDATE requests SET state='COMPLETE',response_json=? WHERE idem_key=? AND state='STARTED'",
                                          (raw, key))
                if cursor.rowcount != 1:
                    raise RuntimeError("idempotency receipt transition failed")
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def in_doubt(self, key):
        with self._lock:
            self._db.execute("UPDATE requests SET state='IN_DOUBT' WHERE idem_key=? AND state='STARTED'", (key,))
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()


class HGHTTPServer(http.server.ThreadingHTTPServer):
    # Drain active request threads before closing the persistent idempotency database.
    daemon_threads = False
    block_on_close = True
    # Allow immediate same-port restart after the previous listener enters TIME_WAIT.
    # SO_REUSEADDR does not permit a second active listener on the same address.
    allow_reuse_address = True

    def __init__(self, *, runtime, token, host="127.0.0.1", port=8765, max_body_bytes=262144,
                 release_report=None, trust_report=None, idempotency_path=None):
        if host != "127.0.0.1":
            raise ValueError("HG HTTP API must bind to IPv4 loopback 127.0.0.1")
        if isinstance(port, bool) or not isinstance(port, int) or not (0 <= port <= 65535):
            raise ValueError("port must be an integer in 0..65535 (0 is for tests only)")
        if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or not (1 <= max_body_bytes <= 1048576):
            raise ValueError("max_body_bytes must be in 1..1048576")
        if not isinstance(token, bytes) or len(token) < 32:
            raise ValueError("service token must be at least 32 bytes")
        self.runtime = runtime
        try:
            token.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("service token must be ASCII") from exc
        self.token = token
        self.max_body_bytes = max_body_bytes
        self.release_report = release_report or (lambda: {"result": "UNVERIFIED"})
        self.trust_report = trust_report or (lambda: {"result": "UNVERIFIED"})
        self.idempotency = IdempotencyStore(idempotency_path) if idempotency_path else None
        self._request_lock = threading.Lock()
        super().__init__((host, port), self._handler_type())

    def _handler_type(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.request.settimeout(5.0)

            def log_message(self, _format, *args):
                # Intentionally suppress request paths, headers, and exception text.
                return

            def _send(self, status, data):
                try:
                    raw = canonical_json(data)
                except (TypeError, ValueError):
                    status, raw = 500, b'{"error":"internal_error"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)
                self.close_connection = True

            def _fail(self, error):
                self._send(error.status, {"error": error.code, "message": str(error)})

            def _validate_host(self):
                hosts = self.headers.get_all("Host", [])
                if len(hosts) != 1:
                    raise HTTPBoundaryError(400, "invalid_host", "exactly one Host header is required")
                host = hosts[0]
                allowed = {"127.0.0.1", "localhost"}
                if not isinstance(host, str) or not host or any(ch in host for ch in "\r\n,/@"):
                    raise HTTPBoundaryError(400, "invalid_host", "invalid Host header")
                if ":" in host:
                    name, sep, port_text = host.rpartition(":")
                    if not sep or not port_text.isdecimal() or int(port_text) != outer.server_address[1]:
                        raise HTTPBoundaryError(400, "invalid_host", "Host port does not match listener")
                else:
                    name = host
                    if outer.server_address[1] not in (80, 443):
                        raise HTTPBoundaryError(400, "invalid_host", "Host header must include listener port")
                if name.lower() not in allowed:
                    raise HTTPBoundaryError(400, "invalid_host", "Host must identify loopback")

            def _authenticate(self):
                self._validate_host()
                if not self.client_address or self.client_address[0] not in ("127.0.0.1", "::1"):
                    raise HTTPBoundaryError(403, "loopback_only", "client must be loopback")
                auth_values = self.headers.get_all("Authorization", [])
                expected = ("Bearer " + outer.token.decode("ascii")).encode("ascii")
                if len(auth_values) != 1:
                    raise HTTPBoundaryError(401, "unauthorized", "exactly one Bearer Authorization header is required")
                value = auth_values[0]
                if not isinstance(value, str) or not hmac.compare_digest(value.encode("utf-8", "ignore"), expected):
                    raise HTTPBoundaryError(401, "unauthorized", "Bearer token required")
                if self.headers.get("Transfer-Encoding"):
                    raise HTTPBoundaryError(400, "transfer_encoding_denied", "Transfer-Encoding is not supported")

            def _body_length(self):
                content_types = self.headers.get_all("Content-Type", [])
                if len(content_types) != 1 or self.headers.get_content_type() != "application/json":
                    raise HTTPBoundaryError(415, "content_type", "one Content-Type: application/json header is required")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isdecimal():
                    raise HTTPBoundaryError(400, "content_length", "one valid Content-Length is required")
                size = int(lengths[0])
                if size > outer.max_body_bytes:
                    raise HTTPBoundaryError(413, "body_too_large", "request body exceeds configured limit")
                return size

            def _body(self):
                size = self._body_length()
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise HTTPBoundaryError(400, "truncated_body", "request body is incomplete")
                return strict_json(raw)

            def handle_expect_100(self):
                try:
                    self._authenticate()
                    self._body_length()
                except HTTPBoundaryError as exc:
                    self._fail(exc)
                    return False
                self.send_response_only(100)
                self.end_headers()
                return True

            def do_GET(self):
                try:
                    self._authenticate()
                    parsed = urlsplit(self.path)
                    if parsed.query or parsed.fragment or "%" in parsed.path:
                        raise HTTPBoundaryError(400, "invalid_path", "query, fragment and escaped paths are not supported")
                    if parsed.path == "/v1/health/live":
                        self._send(200, {"status": "LIVE", "repository": "OAI-GIANG/HG"})
                        return
                    if parsed.path == "/v1/integrity":
                        try:
                            release = outer.release_report()
                        except Exception:
                            release = {"result": "FAILED"}
                        self._send(200 if release.get("result") == "VERIFIED" else 503, release)
                        return
                    if parsed.path == "/v1/health/ready":
                        try:
                            release = outer.release_report()
                        except Exception:
                            release = {"result": "FAILED"}
                        try:
                            trust = outer.trust_report()
                        except Exception:
                            trust = {"result": "BLOCKED"}
                        ok = release.get("result") == "VERIFIED" and trust.get("result") == "LOADED"
                        self._send(200 if ok else 503, {
                            "status": "READY" if ok else "NOT_READY",
                            "repository": "OAI-GIANG/HG",
                            "release_id": release.get("release_id"),
                            "integrity": release.get("result"),
                            "trust": trust.get("result"),
                            "trust_commit": (trust.get("provenance") or {}).get("commit"),
                        })
                        return
                    match = re.fullmatch(r"/v1/tasks/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})", parsed.path)
                    if match:
                        snap = outer.runtime.store.snapshot(match.group(1))
                        self._send(200, snap)
                        return
                    raise HTTPBoundaryError(404, "not_found", "route not found")
                except HTTPBoundaryError as exc:
                    self._fail(exc)
                except (KeyError, MAEPError):
                    self._send(404, {"error": "task_not_found"})
                except Exception:
                    self._send(500, {"error": "internal_error"})

            def do_POST(self):
                try:
                    self._authenticate()
                    parsed = urlsplit(self.path)
                    if parsed.path != "/v1/tasks" or parsed.query or parsed.fragment:
                        raise HTTPBoundaryError(404, "not_found", "route not found")
                    idem_values = self.headers.get_all("Idempotency-Key", [])
                    if len(idem_values) != 1:
                        raise HTTPBoundaryError(400, "idempotency_key", "exactly one Idempotency-Key header is required")
                    idem = idem_values[0]
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", idem):
                        raise HTTPBoundaryError(400, "idempotency_key", "valid Idempotency-Key header required")
                    try:
                        release = outer.release_report()
                        trust = outer.trust_report()
                    except Exception:
                        raise HTTPBoundaryError(503, "service_not_ready",
                                                "release integrity or canonical authority is unavailable")
                    if release.get("result") != "VERIFIED" or trust.get("result") != "LOADED":
                        raise HTTPBoundaryError(503, "service_not_ready",
                                                "release integrity and canonical authority must be VERIFIED")
                    payload = self._body()
                    if not isinstance(payload, dict) or set(payload) != {"task", "steps"}:
                        raise HTTPBoundaryError(400, "invalid_request", "request must contain exactly task and steps")
                    task, steps = _safe_task_steps(payload["task"], payload["steps"])
                    canonical = canonical_json(payload)
                    digest = hashlib.sha256(canonical).hexdigest()
                    if outer.idempotency is None:
                        raise HTTPBoundaryError(503, "idempotency_unavailable", "durable idempotency ledger is unavailable")
                    mode, prior = outer.idempotency.begin(idem, digest)
                    if mode == "CONFLICT":
                        raise HTTPBoundaryError(409, "idempotency_conflict", "key was already used with different content")
                    if mode == "REPLAY":
                        self._send(200, {"replayed": True, "result": prior})
                        return
                    if mode == "IN_DOUBT":
                        raise HTTPBoundaryError(409, "outcome_in_doubt", "prior request outcome is ambiguous; reconcile before retry")
                    try:
                        with outer._request_lock:
                            result = outer.runtime.orch.execute_task(task, steps)
                        response = {"replayed": False, "result": result}
                        outer.idempotency.finish(idem, result)
                    except Exception:
                        outer.idempotency.in_doubt(idem)
                        raise
                    self._send(200, response)
                except HTTPBoundaryError as exc:
                    self._fail(exc)
                except Exception:
                    self._send(500, {"error": "internal_error"})

            def do_PUT(self):
                self._send(405, {"error": "method_not_allowed"})

            def do_DELETE(self):
                self._send(405, {"error": "method_not_allowed"})

            def do_PATCH(self):
                self._send(405, {"error": "method_not_allowed"})

            def do_OPTIONS(self):
                self._send(405, {"error": "method_not_allowed"})

            def send_error(self, code, message=None, explain=None):
                self._send(code, {"error": "method_not_allowed" if code in (400, 405, 501) else "http_error"})

        return Handler

    @property
    def address(self):
        return self.server_address

    def server_close(self):
        try:
            if self.idempotency is not None:
                self.idempotency.close()
        finally:
            super().server_close()
