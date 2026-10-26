import http.client
import json
from threading import Thread
from types import SimpleNamespace
import unittest

from runtime.http_server import HGHTTPServer, HTTPBoundaryError
from brain.orchestrator import OrchestrationError
from brain.tests.test_orchestrator import BrainTests


class MemoryStub:
    def __init__(self):
        self.calls = []

    def create_task(self, task, *, candidate_ref):
        self.calls.append(("create_task", task, candidate_ref))
        return {"task": task, "candidate_ref": candidate_ref, "row_version": 1}

    def get_task(self, task_id):
        self.calls.append(("get_task", task_id))
        return {"task": {"task_id": task_id, "state": "DRAFT"}}

    def list_tasks(self, *, index_scope_task_id, limit=100, offset=0):
        self.calls.append(("list_tasks", index_scope_task_id, limit, offset))
        return {"tasks": [], "limit": limit, "offset": offset, "integrity_status": "PASS"}

    def transition_task(self, task_id, target, **kwargs):
        self.calls.append(("transition_task", task_id, target, kwargs))
        return {"task_id": task_id, "state": target}

    def record_evidence(self, task_id, evidence):
        self.calls.append(("record_evidence", task_id, evidence))
        return {"evidence_id": evidence["evidence_id"]}


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BrainTests()
        self.fixture.setUp()
        self.memory = MemoryStub()
        self.context = "fixture-session"
        self.runtime = SimpleNamespace(
            brain=self.fixture.brain,
            memory=self.memory,
            authority=self.fixture.brain.authority,
            authenticated_context_provider=lambda: self.context,
            candidate_target_provider=lambda request: "candidate-target",
        )
        self.server = HGHTTPServer(
            runtime=self.runtime,
            authenticate_request=self.authenticate,
            host="127.0.0.1",
            port=0,
            max_body_bytes=4096,
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.address[:2]

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.fixture.tearDown()

    def authenticate(self, headers):
        if headers.get("Authorization") != "Bearer test-only":
            raise PermissionError("not authenticated")
        return self.context

    def request(self, method, path, body=None, token=True, raw=None, content_type="application/json"):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
        headers = {}
        if token:
            headers["Authorization"] = "Bearer test-only"
        if body is not None:
            raw = json.dumps(body).encode()
        if raw is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(raw))
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        result = json.loads(payload.decode()) if payload else None
        status = response.status
        conn.close()
        return status, result

    def test_wp0_unauthenticated_malformed_query_is_auth_first(self):
        status, body = self.request("GET", "/api/tasks?bad", token=False)
        self.assertEqual(status, 401)
        self.assertEqual(body.get("error"), "authentication_unavailable_or_denied")

    def test_wp0_authorized_malformed_query_gets_validation_error(self):
        status, body = self.request("GET", "/api/tasks?bad", token=True)
        self.assertEqual(status, 400)
        self.assertIn(body.get("error"), {"task_index_query_invalid", "task_index_scope_required"})

    def test_wp0_unauthenticated_malformed_json_is_auth_first(self):
        status, body = self.request(
            "POST", "/api/dispatch", token=False, raw=b"{", content_type="application/json"
        )
        self.assertEqual(status, 401)
        self.assertEqual(body.get("error"), "authentication_unavailable_or_denied")

    def test_wp0_authorized_malformed_json_gets_validation_error(self):
        status, body = self.request(
            "POST", "/api/dispatch", token=True, raw=b"{", content_type="application/json"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "invalid_json")

    def test_wp0_unsupported_method_is_json_405_with_allow_header(self):
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            with self.subTest(method=method):
                conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
                conn.request(method, "/api/tasks/unused")
                response = conn.getresponse()
                payload = json.loads(response.read().decode())
                allow = response.getheader("Allow")
                content_type = response.getheader("Content-Type")
                conn.close()
                self.assertEqual(response.status, 405)
                self.assertEqual(payload.get("status"), "BLOCKED")
                self.assertEqual(payload.get("error"), "METHOD_NOT_ALLOWED")
                self.assertEqual(content_type, "application/json; charset=utf-8")
                self.assertEqual(allow, "GET, POST")

    def test_wp0_unsupported_method_with_unapproved_host_is_host_rejected(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
        conn.request("PUT", "/api/tasks/unused", headers={"Host": "attacker.invalid"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        conn.close()
        self.assertEqual(response.status, 400)
        self.assertEqual(payload.get("error"), "host_header_invalid")

    def test_wp0_wrong_host_is_rejected(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
        conn.request("GET", "/health", headers={"Host": "attacker.invalid"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        conn.close()
        self.assertEqual(response.status, 400)
        self.assertEqual(payload.get("error"), "host_header_invalid")

    def test_wp0_missing_host_is_rejected(self):
        import socket
        with socket.create_connection((self.host, self.port), timeout=2) as sock:
            sock.sendall(b"GET /health HTTP/1.1\r\nConnection: close\r\n\r\n")
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
        self.assertIn(b" 400 ", data.split(b"\r\n", 1)[0])
        self.assertIn(b"host_header_invalid", data)

    def test_wp0_duplicate_host_is_rejected(self):
        import socket
        with socket.create_connection((self.host, self.port), timeout=2) as sock:
            sock.sendall(
                b"GET /health HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Host: attacker.invalid\r\n"
                b"Connection: close\r\n\r\n"
            )
            data = sock.recv(4096)
        self.assertIn(b" 400 ", data.split(b"\r\n", 1)[0])

    def test_wp0_health_is_liveness_not_readiness(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "LIVE")
        status, body = self.request("GET", "/health/ready", token=False)
        self.assertEqual(status, 401)
        self.assertEqual(body.get("error"), "authentication_unavailable_or_denied")
        status, body = self.request("GET", "/health/ready", token=True)
        self.assertEqual(status, 503)
        self.assertEqual(body.get("status"), "NOT_READY")
        self.runtime.readiness_provider = lambda: {"release": "VERIFIED", "trust": "LOADED"}
        status, body = self.request("GET", "/health/ready", token=True)
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "READY")
        self.assertEqual((body.get("release"), body.get("trust")), ("VERIFIED", "LOADED"))
        self.runtime.readiness_provider = lambda: {"release": "UNKNOWN", "trust": "LOADED"}
        status, body = self.request("GET", "/health/ready", token=True)
        self.assertEqual(status, 503)

    def test_review_and_simulate_route_fails_closed_without_critique_provider(self):
        status, body = self.request(
            "POST", "/api/tasks/HTTP-REVIEW-1/review-and-simulate",
            {"plan": {"task_id": "HTTP-REVIEW-1"}},
        )
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "critique_provider_unavailable")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_review_and_simulate_route_uses_protected_brain_read_only(self):
        calls = []
        self.fixture.brain.critique_engine = object()
        self.fixture.brain.scenario_engine = object()
        def review(**kwargs):
            calls.append(kwargs)
            return {
                "status": "REVIEW_COMPLETE",
                "authority_effect": "NONE",
                "side_effects_performed": False,
            }
        self.fixture.brain.review_and_simulate = review
        plan = {"task_id": "HTTP-REVIEW-2"}
        payload = {
            "plan": plan,
            "claims": [],
            "evidence_refs": [],
            "assumptions": [],
            "constraints": [],
        }
        status, body = self.request(
            "POST", "/api/tasks/HTTP-REVIEW-2/review-and-simulate", payload,
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["status"], "REVIEW_COMPLETE")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["task_ref"], "HTTP-REVIEW-2")
        self.assertEqual(calls[0]["plan"], plan)
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_review_and_simulate_route_rejects_unknown_request_fields(self):
        self.fixture.brain.critique_engine = object()
        status, body = self.request(
            "POST", "/api/tasks/HTTP-REVIEW-3/review-and-simulate",
            {"plan": {"task_id": "HTTP-REVIEW-3"}, "shell_command": "not-allowed"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "review_fields_invalid")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_review_route_requires_existing_authentication(self):
        calls = []
        self.fixture.brain.critique_engine = object()
        self.fixture.brain.review_and_simulate = lambda **kwargs: calls.append(kwargs)
        status, body = self.request(
            "POST", "/api/tasks/HTTP-REVIEW-AUTH/review-and-simulate",
            {"plan": {"task_id": "HTTP-REVIEW-AUTH"}}, token=False,
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "authentication_unavailable_or_denied")
        self.assertEqual(calls, [])
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_missing_authentication_denies_before_brain_or_adapter(self):
        status, body = self.request("POST", "/api/dispatch", {
            "request": self.fixture.request, "adapter_name": "test", "idempotency_key": "http-deny-1"
        }, token=False)
        self.assertEqual(status, 401)
        self.assertEqual(body["status"], "BLOCKED")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_wp0_idempotency_states_map_to_explicit_conflict_responses(self):
        cases = (
            ("IN_PROGRESS: concurrent request", "IN_PROGRESS", "IDEMPOTENCY_IN_PROGRESS"),
            ("CONFLICT: request digest changed", "BLOCKED", "IDEMPOTENCY_CONFLICT"),
            ("OUTCOME_UNKNOWN: reconcile before retry", "UNKNOWN", "IDEMPOTENCY_RECONCILIATION_REQUIRED"),
        )
        for message, expected_status, expected_error in cases:
            with self.subTest(message=message):
                def fail_dispatch(**_kwargs):
                    raise OrchestrationError(message)
                self.fixture.brain.dispatch = fail_dispatch
                payload = {"request": self.fixture.request, "adapter_name": "test",
                           "idempotency_key": "http-state-test"}
                status, body = self.request("POST", "/api/dispatch", payload)
                self.assertEqual(status, 409)
                self.assertEqual(body.get("status"), expected_status)
                self.assertEqual(body.get("error"), expected_error)

    def test_dispatch_uses_existing_brain_and_idempotency(self):
        payload = {"request": self.fixture.request, "adapter_name": "test", "idempotency_key": "http-allow-1"}
        status, body = self.request("POST", "/api/dispatch", payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["outcome"], "SUCCESS")
        self.assertEqual(self.fixture.adapter.calls, 1)
        status, replay = self.request("POST", "/api/dispatch", payload)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["result"]["replayed"])
        self.assertEqual(self.fixture.adapter.calls, 1)

    def test_unverified_candidate_denies_before_effect(self):
        self.fixture.candidate.verified = False
        status, body = self.request("POST", "/api/dispatch", {
            "request": self.fixture.request, "adapter_name": "test", "idempotency_key": "http-candidate-deny"
        })
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "candidate_identity_unverified")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_authenticated_context_must_match_runtime_context(self):
        self.runtime.authenticated_context_provider = lambda: "different-context"
        status, body = self.request("POST", "/api/dispatch", {
            "request": self.fixture.request, "adapter_name": "test", "idempotency_key": "http-context-deny"
        })
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "authenticated_context_not_bound_to_runtime")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_task_create_uses_verified_candidate_and_existing_memory_store(self):
        task = {
            "task_id": "HTTP-TASK-1", "objective": "test HTTP task",
            "scope": {"include": ["memory/"], "exclude": []}, "inputs": [],
            "outputs": [{"name": "result", "description": "test"}],
            "acceptance_criteria": [{"criterion_id": "AC-1", "description": "test", "mandatory": True, "evidence_types": ["TEST_RESULT"]}],
            "evidence_requirements": ["test evidence"], "risks": [], "stop_conditions": ["deny"],
            "next_action": "verify", "state": "DRAFT", "policy_version": "MAEP-1.2.0"
        }
        status, body = self.request("POST", "/api/tasks", {"task": task})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.memory.calls[0][0], "create_task")
        self.assertEqual(self.memory.calls[0][2], "candidate:1")

    def test_task_index_routes_through_authorized_memory_boundary(self):
        status, body = self.request("GET", "/api/tasks?index_scope_task_id=HTTP-TASK-1&limit=25&offset=5")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["integrity_status"], "PASS")
        self.assertEqual(self.memory.calls[0], ("list_tasks", "HTTP-TASK-1", 25, 5))

    def test_task_index_end_to_end_uses_real_memory_store(self):
        import tempfile
        from pathlib import Path
        from datetime import datetime, timezone
        from maep.core import POLICY_VERSION
        from memory import MemoryStore
        from memory.tests.test_store import policy_decision, applicability_provider_for_test, MemoryStoreTests

        with tempfile.TemporaryDirectory(prefix="hg-http-memory-index-") as temp:
            def live_state(task_id):
                return {
                    "task_id": task_id, "candidate_ref": "candidate-1",
                    "policy_version": POLICY_VERSION,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "resources": [{"resource_id": "repo/OAI-GIANG/HG", "version": "candidate-1"}],
                }

            memory = MemoryStore(
                Path(temp) / "memory.sqlite3",
                principal_provider=lambda: "test-runtime-principal",
                policy_evaluator=policy_decision,
                live_state_provider=live_state,
                applicability_provider=applicability_provider_for_test,
            )
            memory.initialize(task_id="T-BOOT")
            memory.create_task(MemoryStoreTests.task("HTTP-INDEX-TASK"), candidate_ref="candidate-1")
            self.runtime.memory = memory

            status, body = self.request(
                "GET", "/api/tasks?index_scope_task_id=HTTP-INDEX-TASK&limit=10&offset=0"
            )
            self.assertEqual(status, 200, body)
            page = body["result"]
            self.assertEqual(page["integrity_status"], "PASS")
            self.assertEqual(page["returned"], 1)
            self.assertEqual(
                [item["task"]["task_id"] for item in page["tasks"]],
                ["HTTP-INDEX-TASK"],
            )
            self.assertTrue(all(item["policy_status"] == "CURRENT" for item in page["tasks"]))

    def test_task_index_requires_explicit_authorization_scope(self):
        status, body = self.request("GET", "/api/tasks")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "task_index_scope_required")
        self.assertEqual(self.memory.calls, [])

    def test_task_index_rejects_invalid_pagination(self):
        status, body = self.request("GET", "/api/tasks?index_scope_task_id=HTTP-TASK-1&limit=501")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "task_index_pagination_invalid")
        self.assertEqual(self.memory.calls, [])

    def test_task_index_rejects_malformed_query_without_dropping_connection(self):
        status, body = self.request("GET", "/api/tasks?index_scope_task_id")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "task_index_query_invalid")
        self.assertEqual(self.memory.calls, [])

    def test_task_transition_routes_only_to_existing_memory_api(self):
        status, body = self.request("POST", "/api/tasks/HTTP-TASK-1/transition", {
            "target": "READY", "expected_version": 1
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(self.memory.calls[0][0], "transition_task")
        self.assertEqual(self.memory.calls[0][2], "READY")

    def test_duplicate_json_keys_are_rejected(self):
        raw = b'{"request": {}, "request": {}, "adapter_name": "test", "idempotency_key": "dup"}'
        status, body = self.request("POST", "/api/dispatch", raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_json")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_oversized_body_is_rejected(self):
        raw = b'{"x":"' + (b'a' * 5000) + b'"}'
        status, body = self.request("POST", "/api/dispatch", raw=raw)
        self.assertEqual(status, 413)
        self.assertEqual(body["error"], "request_body_size_invalid")
        self.assertEqual(self.fixture.adapter.calls, 0)

    def _stalled_connection_closes(self, payload):
        import socket
        import time
        server = HGHTTPServer(runtime=self.runtime, authenticate_request=self.authenticate,
                              host="127.0.0.1", port=0, max_body_bytes=4096,
                              request_timeout_seconds=0.3)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = socket.create_connection(server.address[:2], timeout=5)
            try:
                client.sendall(payload)
                started = time.monotonic()
                data = b""
                while True:            # server must answer/close on its own, not wait forever
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                return data, time.monotonic() - started
            finally:
                client.close()
        finally:
            server.shutdown()
            thread.join(timeout=2)

    def test_stalled_request_line_is_closed_by_server_timeout(self):
        data, elapsed = self._stalled_connection_closes(b"GET /api/tasks/T-1 HTTP/1.1\r\nHost: x")
        self.assertLess(elapsed, 4)
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_stalled_request_body_times_out_with_408(self):
        head = (b"POST /api/dispatch HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer test-only\r\n"
                b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{\"request\"")
        data, elapsed = self._stalled_connection_closes(head)
        self.assertLess(elapsed, 4)
        self.assertIn(b" 400 ", data.split(b"\r\n", 1)[0])
        self.assertIn(b"host_header_invalid", data)
        self.assertEqual(self.fixture.adapter.calls, 0)

    def test_request_timeout_must_be_bounded(self):
        for value in (0, -1, 61, True, "5"):
            with self.assertRaisesRegex(HTTPBoundaryError, "invalid_request_timeout"):
                HGHTTPServer(runtime=self.runtime, authenticate_request=self.authenticate,
                             host="127.0.0.1", port=0, request_timeout_seconds=value)

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaisesRegex(HTTPBoundaryError, "only_loopback_bind_is_supported"):
            HGHTTPServer(runtime=self.runtime, authenticate_request=self.authenticate, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
