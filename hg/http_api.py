"""Authenticated, loopback-only HTTP adapter for the existing HG runtime."""
from __future__ import annotations

import hashlib
import hmac
import http.server
import io
import json
import re
import sqlite3
import stat
import threading
import time
import unicodedata
from pathlib import Path, PurePosixPath

from maep.core import MAEPError
from maep.sqlite_nofollow import connect_nofollow
from maep.admission import require_writer_session
from hg.tools.gateway import read_regular_file


# Reading one request (request line, headers, body) is bounded twice:
# - REQUEST_TIMEOUT_SECONDS per socket read (silence), the value hg serve always used;
# - REQUEST_DEADLINE_SECONDS in total on the monotonic clock, so a client sending a byte
#   just before every read timeout cannot hold a handler thread -- and, because handler
#   threads are joined on close, service shutdown -- open. No contract fixes a value;
#   15 s is three read timeouts on a loopback-only API with bodies of at most 1 MiB.
REQUEST_TIMEOUT_SECONDS = 5.0
REQUEST_DEADLINE_SECONDS = 15.0
MAX_REQUEST_DEADLINE_SECONDS = 120.0
# Concurrent connections, one handler thread each; beyond this the server answers 503.
MAX_CONNECTIONS = 32
_BUSY_BODY = b'{"error":"server_busy"}'
_BUSY_RESPONSE = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
                  b"Content-Length: " + str(len(_BUSY_BODY)).encode() + b"\r\nCache-Control: no-store\r\n"
                  b"Connection: close\r\n\r\n" + _BUSY_BODY)


# Web UI shipped inside the release (hg/ui/). These four exact request targets are the only
# ones answered without a bearer token: static files with no data and no effect, so a browser
# can open the page. Host and loopback-client checks still apply; every other route,
# including any other /ui/... path, still answers 401 before routing (HG_SERVICE_V1 §5).
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_FILES = {
    "/ui/": ("index.html", "text/html; charset=utf-8"),
    "/ui/index.html": ("index.html", "text/html; charset=utf-8"),
    "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/ui/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
UI_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
          "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
UI_HEADERS = (
    ("Content-Security-Policy", UI_CSP),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)
MAX_CHAT_MESSAGE_CHARS = 2000


def load_ui_assets(ui_dir=UI_DIR):
    """Read the UI files once at startup: {request target: (bytes, content type)}; regular files only."""
    assets = {}
    for target, (name, content_type) in UI_FILES.items():
        path = Path(ui_dir) / name
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            assets[target] = (path.read_bytes(), content_type)
        except OSError:
            continue
    return assets


class _DeadlineSocketReader(io.RawIOBase):
    """Raw reader: each recv is bounded by the per-read timeout and the request deadline."""

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
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("invalid JSON constant")))
        # A lone surrogate escape (\\ud800) decodes to a string UTF-8 cannot encode: it would
        # fail later at canonical_json/the ledger as a 500. It is not valid text: refuse it here.
        json.dumps(value, ensure_ascii=False).encode("utf-8")
        return value
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
            content = params.get("content")
            try:
                expected = content.encode("utf-8") if isinstance(content, str) else None
            except UnicodeError:
                expected = None
            if expected is None:
                return False, f"planned content is not UTF-8 text: {rel.as_posix()}"
            # Compare the exact bytes fs.write produced. Text mode would translate CRLF/CR to LF,
            # accepting a file that differs from the plan and refusing a correct write of CR.
            try:
                actual = read_regular_file(target, max_bytes=len(expected))
            except OSError as exc:
                return False, (f"read-back target missing, not a regular file or unreadable "
                               f"({type(exc).__name__}): {rel.as_posix()}")
            if actual != expected:
                return False, f"read-back differs from planned content: {rel.as_posix()}"
        return True, f"read-back matched {len(writes)} planned write(s)"

    verify.__name__ = "planned_write_readback"
    return verify


class IdempotencyUnavailable(RuntimeError):
    """The store cannot record a new request (closed or failed closed); nothing was executed."""


class IdempotencyStateError(RuntimeError):
    """A receipt owned by an active request is no longer STARTED: the durable state is unknown."""


class IdempotencyStore:
    """SQLite-backed idempotency receipts; ambiguous outcomes remain IN_DOUBT.

    Receipt states: STARTED (durable before execution), COMPLETE (response stored), IN_DOUBT.

    Ownership. ``begin()`` returning NEW makes the calling request the owner of the key in this
    process (``_active_keys``) until it calls ``finish()`` (success) or ``in_doubt()``. The caller
    must call ``in_doubt()`` on every other exit -- Exception or BaseException, including a
    failed ``finish()``; ``in_doubt()`` always releases ownership and never raises. Ownership is
    process-local, not a lease: one store instance per database per process (the service's
    writer flock admits one process per state directory). After a restart every durable STARTED
    receipt is an orphan and answers IN_DOUBT.

    Failures. Every write is one explicit BEGIN IMMEDIATE transaction, ended by COMMIT or, on any
    failure, ROLLBACK. The store fails closed (``status == "UNUSABLE"``: no new request, no
    further write, until the process restarts) when the outcome is unknown: the rollback failed,
    the connection still reports an open transaction, a transaction was found open before BEGIN,
    or the failure is not a ``sqlite3.OperationalError`` (database binding broken, corruption,
    a closed connection, an owned receipt that is no longer STARTED). An OperationalError that
    rolled back cleanly (e.g. "database is locked") leaves the store usable.
    """
    def __init__(self, path, *, writer_session=None):
        self._writer_session = require_writer_session(path, writer_session)
        self.path = str(path)
        self._lock = threading.Lock()
        # Keys claimed by requests currently executing in this service process.
        # This is intentionally process-local: after a restart the set is empty,
        # so a durable STARTED receipt is treated as an orphan and fails closed.
        self._active_keys = set()
        self._unusable = None            # reason, once the store has failed closed or closed
        self._closed = False
        self._db = connect_nofollow(sqlite3, self.path, timeout=5, check_same_thread=False)
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

    @property
    def status(self):
        """USABLE, or UNUSABLE once the store has failed closed or been closed."""
        return "USABLE" if self._unusable is None else "UNUSABLE"

    @property
    def unusable_reason(self):
        return self._unusable

    def _fail_closed(self, reason):
        if self._unusable is None:
            self._unusable = reason

    def _write(self, operation):
        """Run operation() in one BEGIN IMMEDIATE transaction. The caller holds self._lock."""
        if self._unusable is not None:
            raise IdempotencyUnavailable("idempotency store is unusable")
        if self._db.in_transaction:
            # No write leaves a transaction open; one found here has unknown content.
            self._fail_closed("transaction found open")
            raise IdempotencyUnavailable("idempotency store is unusable")
        try:
            self._db.execute("BEGIN IMMEDIATE")
            result = operation()
            self._db.commit()
            return result
        except BaseException as exc:
            self._end_failed_transaction(exc)
            raise

    def _end_failed_transaction(self, exc):
        """Roll back after a failed step, or fail closed if the outcome is unknown.

        Never replaces `exc`: a rollback failure is absorbed into the UNUSABLE state.
        """
        clean = False
        try:
            if self._db.in_transaction:
                self._db.rollback()
            clean = not self._db.in_transaction
        except Exception:
            clean = False
        finally:
            if not clean:
                self._fail_closed("rollback failed or transaction still open")
            elif not isinstance(exc, sqlite3.OperationalError):
                self._fail_closed(type(exc).__name__)

    def begin(self, key, digest):
        """NEW (this request now owns `key`), REPLAY, CONFLICT, IN_PROGRESS or IN_DOUBT."""
        def claim():
            row = self._db.execute(
                "SELECT digest,state,response_json FROM requests WHERE idem_key=?", (key,)
            ).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO requests(idem_key,digest,state) VALUES(?,?, 'STARTED')",
                    (key, digest))
                return "NEW", None
            old_digest, state, response = row
            if old_digest != digest:
                return "CONFLICT", None
            if state == "COMPLETE":
                return "REPLAY", response
            if state == "STARTED":
                # The same store instance is shared by all handler threads
                # in the one admitted service process. A key absent from
                # this process-local set is an orphaned durable claim.
                return ("IN_PROGRESS" if key in self._active_keys else "IN_DOUBT"), None
            return "IN_DOUBT", None

        with self._lock:
            mode, prior = self._write(claim)
            if mode == "NEW":
                # Add while still holding _lock: another handler cannot observe
                # STARTED between the durable commit and active registration.
                self._active_keys.add(key)
        return mode, (json.loads(prior) if mode == "REPLAY" else None)

    def finish(self, key, response):
        """STARTED -> COMPLETE and release ownership. On failure ownership is kept: call in_doubt()."""
        raw = canonical_json(response).decode("utf-8")

        def complete():
            cursor = self._db.execute(
                "UPDATE requests SET state='COMPLETE',response_json=? WHERE idem_key=? AND state='STARTED'",
                (raw, key))
            if cursor.rowcount != 1:
                raise IdempotencyStateError("idempotency receipt transition failed")

        with self._lock:
            self._write(complete)
            self._active_keys.discard(key)

    def in_doubt(self, key):
        """STARTED -> IN_DOUBT if possible; always release ownership; never raise an Exception.

        Called while another exception may be propagating, so it must not replace it. Returns
        True if the transition (or an already-final state) is durable, False if not recorded:
        the durable STARTED receipt then answers IN_DOUBT to every later begin() because no
        request owns it, and a store that could not end its transaction is UNUSABLE.
        """
        with self._lock:
            try:
                if self._unusable is not None:
                    return False
                self._write(lambda: self._db.execute(
                    "UPDATE requests SET state='IN_DOUBT' WHERE idem_key=? AND state='STARTED'", (key,)))
                return True
            except Exception:
                return False
            finally:
                self._active_keys.discard(key)

    def close(self):
        """Close the connection; idempotent. Only after every request that may use it has ended."""
        with self._lock:
            self._active_keys.clear()
            if self._closed:
                return
            self._closed = True
            self._fail_closed("closed")
            self._db.close()


class HGHTTPServer(http.server.ThreadingHTTPServer):
    # Drain active request threads before closing the persistent idempotency database.
    daemon_threads = False
    block_on_close = True
    # Allow immediate same-port restart after the previous listener enters TIME_WAIT.
    # SO_REUSEADDR does not permit a second active listener on the same address.
    allow_reuse_address = True

    def __init__(self, *, runtime, token, host="127.0.0.1", port=8765, max_body_bytes=262144,
                 release_report=None, trust_report=None, idempotency_path=None, writer_session=None,
                 request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                 request_deadline_seconds=REQUEST_DEADLINE_SECONDS, max_connections=MAX_CONNECTIONS,
                 chat=None, ui_dir=UI_DIR):
        if host != "127.0.0.1":
            raise ValueError("HG HTTP API must bind to IPv4 loopback 127.0.0.1")
        if isinstance(port, bool) or not isinstance(port, int) or not (0 <= port <= 65535):
            raise ValueError("port must be an integer in 0..65535 (0 is for tests only)")
        if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or not (1 <= max_body_bytes <= 1048576):
            raise ValueError("max_body_bytes must be in 1..1048576")
        if (isinstance(request_timeout_seconds, bool) or not isinstance(request_timeout_seconds, (int, float))
                or not 0 < request_timeout_seconds <= 60):
            raise ValueError("request_timeout_seconds must be in (0, 60]")
        if (isinstance(request_deadline_seconds, bool) or not isinstance(request_deadline_seconds, (int, float))
                or not request_timeout_seconds <= request_deadline_seconds <= MAX_REQUEST_DEADLINE_SECONDS):
            raise ValueError("request_deadline_seconds must be in [request_timeout_seconds, 120]")
        if isinstance(max_connections, bool) or not isinstance(max_connections, int) or not 1 <= max_connections <= 256:
            raise ValueError("max_connections must be in 1..256")
        if not isinstance(token, bytes) or len(token) < 32:
            raise ValueError("service token must be at least 32 bytes")
        if chat is not None and not callable(chat):
            raise ValueError("chat must be callable(message, general=bool) -> dict")
        self.runtime = runtime
        try:
            token.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("service token must be ASCII") from exc
        self.token = token
        self.max_body_bytes = max_body_bytes
        self.release_report = release_report or (lambda: {"result": "UNVERIFIED"})
        self.trust_report = trust_report or (lambda: {"result": "UNVERIFIED"})
        self.idempotency = (IdempotencyStore(idempotency_path, writer_session=writer_session)
                            if idempotency_path else None)
        self.chat = chat                       # hg.chat.ChatService in production (hg/service.py)
        self.ui_assets = load_ui_assets(ui_dir) if ui_dir is not None else {}
        self._request_lock = threading.Lock()
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.request_deadline_seconds = float(request_deadline_seconds)
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        super().__init__((host, port), self._handler_type())

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
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
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()

    def _handler_type(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            timeout = outer.request_timeout_seconds

            def setup(self):
                super().setup()
                # Every read of request line, headers and body also honours the total
                # deadline. Past it, an incomplete request line/headers closes the
                # connection without a response; an incomplete body answers 408.
                self.rfile.close()      # drops the makefile() reference, not the socket
                self._request_reader = _DeadlineSocketReader(
                    self.request, read_timeout=outer.request_timeout_seconds,
                    deadline=time.monotonic() + outer.request_deadline_seconds)
                self.rfile = io.BufferedReader(self._request_reader)

            def log_message(self, _format, *args):
                # Intentionally suppress request paths, headers, and exception text.
                return

            def _send(self, status, data):
                try:
                    raw = canonical_json(data)
                except (TypeError, ValueError):
                    status, raw = 500, b'{"error":"internal_error"}'
                self.request.settimeout(outer.request_timeout_seconds)   # reads may have shortened it
                self.close_connection = True
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return              # client gone or not reading; nothing left to tell it

            def _fail(self, error):
                self._send(error.status, {"error": error.code, "message": str(error)})

            def _send_static(self, data, content_type):
                self.request.settimeout(outer.request_timeout_seconds)
                self.close_connection = True
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    for name, value in UI_HEADERS:
                        self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return

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

            def _require_loopback_client(self):
                if not self.client_address or self.client_address[0] not in ("127.0.0.1", "::1"):
                    raise HTTPBoundaryError(403, "loopback_only", "client must be loopback")

            def _authenticate(self):
                self._validate_host()
                self._require_loopback_client()
                auth_values = self.headers.get_all("Authorization", [])
                expected = ("Bearer " + outer.token.decode("ascii")).encode("ascii")
                if len(auth_values) != 1:
                    raise HTTPBoundaryError(401, "unauthorized", "exactly one Bearer Authorization header is required")
                value = auth_values[0]
                if not isinstance(value, str) or not hmac.compare_digest(value.encode("utf-8", "ignore"), expected):
                    raise HTTPBoundaryError(401, "unauthorized", "Bearer token required")
                # Any Transfer-Encoding field, even an empty one first in a list, is refused:
                # Content-Length is the only framing this service reads.
                if self.headers.get_all("Transfer-Encoding"):
                    raise HTTPBoundaryError(400, "transfer_encoding_denied", "Transfer-Encoding is not supported")

            def _origin_path(self):
                """The route is the origin-form target itself (RFC 9112 3.2.1), with no query or fragment.

                urlsplit() would drop an absolute-form authority or scheme ("http://other/v1/tasks",
                "x:/v1/tasks") and an empty "?" or "#", so those targets would reach a route.
                """
                target = self.path
                if (not target.startswith("/") or target.startswith("//")
                        or any(ch in target for ch in "?#")):
                    raise HTTPBoundaryError(400, "invalid_path",
                                            "only an origin-form path without query or fragment is accepted")
                return target

            def _body_length(self):
                content_types = self.headers.get_all("Content-Type", [])
                if len(content_types) != 1 or self.headers.get_content_type() != "application/json":
                    raise HTTPBoundaryError(415, "content_type", "one Content-Type: application/json header is required")
                # The body is decoded as UTF-8, so the only parameter allowed is charset=utf-8.
                params = (self.headers.get_params() or [])[1:]
                if params and (len(params) != 1 or params[0][0] != "charset"
                               or params[0][1].lower() != "utf-8"):
                    raise HTTPBoundaryError(415, "content_type", "Content-Type parameters other than charset=utf-8 are not supported")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or not lengths[0].isdecimal():
                    raise HTTPBoundaryError(400, "content_length", "one valid Content-Length is required")
                size = int(lengths[0])
                if size > outer.max_body_bytes:
                    raise HTTPBoundaryError(413, "body_too_large", "request body exceeds configured limit")
                return size

            def _body(self):
                size = self._body_length()
                try:
                    raw = self.rfile.read(size)
                except TimeoutError as exc:
                    if self._request_reader.deadline_exceeded:
                        raise HTTPBoundaryError(408, "request_deadline_exceeded",
                                                "request was not received within the deadline") from exc
                    raise HTTPBoundaryError(408, "request_timeout", "request body stalled") from exc
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
                    asset = outer.ui_assets.get(self.path)     # exact request target only
                    if asset is not None:
                        self._validate_host()
                        self._require_loopback_client()
                        self._send_static(*asset)
                        return
                    self._authenticate()
                    path = self._origin_path()
                    if "%" in path:
                        raise HTTPBoundaryError(400, "invalid_path", "query, fragment and escaped paths are not supported")
                    if path == "/v1/health/live":
                        self._send(200, {"status": "LIVE", "repository": "OAI-GIANG/HG"})
                        return
                    if path == "/v1/integrity":
                        try:
                            release = outer.release_report()
                        except Exception:
                            release = {"result": "FAILED"}
                        self._send(200 if release.get("result") == "VERIFIED" else 503, release)
                        return
                    if path == "/v1/health/ready":
                        try:
                            release = outer.release_report()
                        except Exception:
                            release = {"result": "FAILED"}
                        try:
                            trust = outer.trust_report()
                        except Exception:
                            trust = {"result": "BLOCKED"}
                        # A store that failed closed cannot accept a task: not ready. Without a
                        # configured store the service keeps its prior readiness (POST answers 503).
                        idempotency = ("NOT_CONFIGURED" if outer.idempotency is None
                                       else outer.idempotency.status)
                        ok = (release.get("result") == "VERIFIED" and trust.get("result") == "LOADED"
                              and idempotency != "UNUSABLE")
                        self._send(200 if ok else 503, {
                            "status": "READY" if ok else "NOT_READY",
                            "repository": "OAI-GIANG/HG",
                            "release_id": release.get("release_id"),
                            "integrity": release.get("result"),
                            "trust": trust.get("result"),
                            "trust_commit": (trust.get("provenance") or {}).get("commit"),
                            "idempotency": idempotency,
                        })
                        return
                    match = re.fullmatch(r"/v1/tasks/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})", path)
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

            def _chat(self):
                """POST /v1/chat (contract revision 2026-10-29): one message -> outer.chat -> answer."""
                if outer.chat is None:
                    raise HTTPBoundaryError(503, "chat_unavailable", "chat is not configured on this service")
                try:
                    release = outer.release_report()
                except Exception:
                    raise HTTPBoundaryError(503, "service_not_ready", "release integrity is unavailable")
                if release.get("result") != "VERIFIED":
                    raise HTTPBoundaryError(503, "service_not_ready", "release integrity must be VERIFIED")
                payload = self._body()
                if not isinstance(payload, dict) or set(payload) != {"message", "general"}:
                    raise HTTPBoundaryError(400, "invalid_request", "request must contain exactly message and general")
                message, general = payload["message"], payload["general"]
                if not isinstance(message, str) or not isinstance(general, bool):
                    raise HTTPBoundaryError(400, "invalid_request", "message must be a string and general a boolean")
                message = unicodedata.normalize("NFC", message).strip()
                if not message or len(message) > MAX_CHAT_MESSAGE_CHARS:
                    raise HTTPBoundaryError(400, "invalid_message",
                                            f"message must have 1..{MAX_CHAT_MESSAGE_CHARS} characters")
                self._send(200, outer.chat(message, general=general))

            def do_POST(self):
                try:
                    self._authenticate()
                    path = self._origin_path()
                    if path == "/v1/chat":
                        self._chat()
                        return
                    if path != "/v1/tasks":
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
                    try:
                        mode, prior = outer.idempotency.begin(idem, digest)
                    except Exception as exc:
                        # STARTED was not recorded (or not with certainty): nothing is executed.
                        raise HTTPBoundaryError(503, "idempotency_unavailable",
                                                "durable idempotency ledger is unavailable") from exc
                    if mode == "CONFLICT":
                        raise HTTPBoundaryError(409, "idempotency_conflict", "key was already used with different content")
                    if mode == "REPLAY":
                        self._send(200, {"replayed": True, "result": prior})
                        return
                    if mode == "IN_PROGRESS":
                        raise HTTPBoundaryError(409, "request_in_progress",
                                                "matching request is still being processed; retry with the same key later")
                    if mode != "NEW":
                        raise HTTPBoundaryError(409, "outcome_in_doubt", "prior request outcome is ambiguous; reconcile before retry")
                    # This request owns the key until finish() succeeds. Every other exit --
                    # Exception or BaseException, from execute_task or from finish() -- runs
                    # in_doubt(), which releases ownership and never raises, so the original
                    # exception is the one that propagates (BaseException is not answered).
                    completed = False
                    try:
                        with outer._request_lock:
                            result = outer.runtime.orch.execute_task(task, steps)
                        outer.idempotency.finish(idem, result)
                        completed = True
                    finally:
                        if not completed:
                            outer.idempotency.in_doubt(idem)
                    self._send(200, {"replayed": False, "result": result})
                except HTTPBoundaryError as exc:
                    self._fail(exc)
                except Exception:
                    self._send(500, {"error": "internal_error"})

            def _unsupported_method(self):
                """Every route requires the bearer token, including a route that only refuses.

                HG_SERVICE_V1 §5: "All routes require Authorization: Bearer token". Answering 405
                before authenticating would tell an unauthenticated caller which methods exist.
                """
                try:
                    self._authenticate()
                except HTTPBoundaryError as exc:
                    self._fail(exc)
                    return
                self._send(405, {"error": "method_not_allowed"})

            def do_PUT(self):
                self._unsupported_method()

            def do_DELETE(self):
                self._unsupported_method()

            def do_PATCH(self):
                self._unsupported_method()

            def do_OPTIONS(self):
                self._unsupported_method()

            def send_error(self, code, message=None, explain=None):
                # Protocol-level parse errors (malformed request line, unsupported HTTP version)
                # are answered before any header can be authenticated; they never perform work.
                self._send(code, {"error": "method_not_allowed" if code in (400, 405, 501) else "http_error"})

        return Handler

    @property
    def address(self):
        return self.server_address

    def server_close(self):
        """Close the listener, wait for every handler thread, then close the idempotency store.

        ThreadingMixIn.server_close() closes the listening socket and, with block_on_close,
        joins all handler threads. Only then is the store closed, so a running request can
        still record its outcome. If the join is interrupted the store is left open (closed at
        process exit) rather than closed under a running handler.
        """
        super().server_close()
        if self.idempotency is not None:
            self.idempotency.close()
