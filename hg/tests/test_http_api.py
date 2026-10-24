"""Real loopback HTTP tests through HGHTTPServer and the existing GitHub trust fake."""
import http.client
import hashlib
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.http_api import HGHTTPServer, canonical_json, planned_write_readback_verifier
from hg.runtime import build_runtime
from hg.tests.support import TempDirMixin, grant, make_task, write_step


TOKEN = b"test-token-that-is-long-enough-for-the-boundary"


class HTTPAPITests(TempDirMixin):
    def setUp(self):
        super().setUp()
        gh = FakeGitHub()
        authority = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0, clock=self.clock)
        self.runtime = build_runtime(self.workdir, [], authority=authority, issue_task_grants=True,
                                     clock=self.clock,
                                     verifiers={"AC-READBACK": planned_write_readback_verifier(self.root)})
        self.server = HGHTTPServer(
            runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0,
            max_body_bytes=2048,
            release_report=lambda: {"result": "VERIFIED", "release_id": "a" * 64},
            trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "b" * 40}},
            idempotency_path=self.workdir / "http-idempotency.sqlite3",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.address

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        super().tearDown()

    def request(self, method, path, *, body=None, raw=None, token=True, headers=None, content_type="application/json"):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
        out = dict(headers or {})
        if token:
            out["Authorization"] = "Bearer " + TOKEN.decode()
        if body is not None:
            raw = json.dumps(body, separators=(",", ":")).encode()
        if raw is not None:
            out.setdefault("Content-Type", content_type)
            out.setdefault("Content-Length", str(len(raw)))
        conn.request(method, path, body=raw, headers=out)
        response = conn.getresponse()
        status = response.status
        payload = response.read()
        conn.close()
        try:
            value = json.loads(payload.decode("utf-8"))
        except ValueError:
            value = payload.decode("utf-8", "replace")
        return status, value

    def payload(self, content="xin chao"):
        task = make_task(task_id="HTTP-T-1")
        task["acceptance_criteria"] = [{
            "criterion_id": "AC-READBACK", "description": "write content can be read back exactly",
            "mandatory": True, "evidence_types": ["TEST_RESULT"],
        }]
        return {"task": task, "steps": [write_step(authorization_id="HTTP-A-1", content=content)]}

    def test_live_and_readiness_require_token_and_report_verification(self):
        self.assertEqual(self.request("GET", "/v1/health/live", token=False)[0], 401)
        status, body = self.request("GET", "/v1/health/live")
        self.assertEqual((status, body["status"]), (200, "LIVE"))
        status, body = self.request("GET", "/v1/health/ready")
        self.assertEqual((status, body["status"], body["integrity"], body["trust"]),
                         (200, "READY", "VERIFIED", "LOADED"))
        self.assertEqual(self.request("GET", "/v1/integrity")[1]["release_id"], "a" * 64)

    def test_integrity_route_still_reports_release_when_trust_is_unavailable(self):
        self.server.trust_report = lambda: (_ for _ in ()).throw(RuntimeError("trust unavailable"))
        status, body = self.request("GET", "/v1/integrity")
        self.assertEqual((status, body["result"]), (200, "VERIFIED"))
        status, body = self.request("GET", "/v1/health/ready")
        self.assertEqual((status, body["status"], body["integrity"], body["trust"]),
                         (503, "NOT_READY", "VERIFIED", "BLOCKED"))

    def test_host_header_is_bound_to_loopback_listener(self):
        status, body = self.request("GET", "/v1/health/live",
                                    headers={"Host": "attacker.example"})
        self.assertEqual((status, body["error"]), (400, "invalid_host"))

    def test_duplicate_host_header_is_rejected(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
        conn.putrequest("GET", "/v1/health/live", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.putheader("Host", f"localhost:{self.port}")
        conn.putheader("Authorization", "Bearer " + TOKEN.decode())
        conn.endheaders()
        response = conn.getresponse()
        status = response.status
        body = json.loads(response.read().decode("utf-8"))
        conn.close()
        self.assertEqual((status, body["error"]), (400, "invalid_host"))

    def test_duplicate_authorization_header_is_rejected(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=3)
        conn.putrequest("GET", "/v1/health/live", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.putheader("Authorization", "Bearer " + TOKEN.decode())
        conn.putheader("Authorization", "Bearer invalid")
        conn.endheaders()
        response = conn.getresponse()
        status = response.status
        body = json.loads(response.read().decode("utf-8"))
        conn.close()
        self.assertEqual((status, body["error"]), (401, "unauthorized"))

    def test_request_body_size_is_bounded(self):
        status, body = self.request("POST", "/v1/tasks", raw=b"x" * 2050,
                                    headers={"Idempotency-Key": "too-big"})
        self.assertEqual((status, body["error"]), (413, "body_too_large"))

    def test_duplicate_json_keys_are_rejected_before_dispatch(self):
        raw = b'{"task":{},"task":{},"steps":[]}'
        status, body = self.request("POST", "/v1/tasks", raw=raw,
                                    headers={"Idempotency-Key": "duplicate"})
        self.assertEqual((status, body["error"]), (400, "invalid_json"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_non_json_content_type_is_rejected(self):
        status, body = self.request("POST", "/v1/tasks", raw=b"{}",
                                    headers={"Idempotency-Key": "bad-type"},
                                    content_type="text/plain")
        self.assertEqual((status, body["error"]), (415, "content_type"))

    def test_post_is_denied_when_release_integrity_is_not_verified(self):
        self.server.release_report = lambda: {"result": "FAILED"}
        status, body = self.request("POST", "/v1/tasks", body=self.payload(),
                                    headers={"Idempotency-Key": "bad-release"})
        self.assertEqual((status, body["error"]), (503, "service_not_ready"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_post_is_denied_when_canonical_authority_is_unavailable(self):
        self.server.trust_report = lambda: (_ for _ in ()).throw(RuntimeError("authority unavailable"))
        status, body = self.request("POST", "/v1/tasks", body=self.payload(),
                                    headers={"Idempotency-Key": "bad-authority"})
        self.assertEqual((status, body["error"]), (503, "service_not_ready"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_disabled_tool_is_denied_before_runtime(self):
        payload = self.payload()
        payload["steps"][0]["tool"] = "test.run"
        payload["steps"][0]["action"] = "EXECUTE"
        status, body = self.request("POST", "/v1/tasks", body=payload,
                                    headers={"Idempotency-Key": "tool-disabled"})
        self.assertEqual((status, body["error"]), (403, "tool_disabled"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_non_normalized_path_is_denied_before_runtime(self):
        payload = self.payload()
        payload["steps"][0]["params"]["path"] = "out//hello.txt"
        payload["steps"][0]["resource"] = "file:out/hello.txt"
        status, body = self.request("POST", "/v1/tasks", body=payload,
                                    headers={"Idempotency-Key": "non-normalized"})
        self.assertEqual((status, body["error"]), (403, "scope_denied"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_path_traversal_is_denied_before_runtime(self):
        payload = self.payload()
        payload["steps"][0]["params"]["path"] = "out/../escaped.txt"
        payload["steps"][0]["resource"] = "file:out/../escaped.txt"
        status, body = self.request("POST", "/v1/tasks", body=payload,
                                    headers={"Idempotency-Key": "traversal"})
        self.assertEqual((status, body["error"]), (403, "scope_denied"))
        self.assertFalse((self.workdir / "escaped.txt").exists())

    def test_task_closes_and_idempotent_replay_does_not_repeat_effect(self):
        payload = self.payload()
        status, result = self.request("POST", "/v1/tasks", body=payload,
                                      headers={"Idempotency-Key": "smoke-1"})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual((self.root / "out/hello.txt").read_text(), "xin chao")
        actions_before = len(self.runtime.actions.events("ACTION_STARTED"))
        status, replay = self.request("POST", "/v1/tasks", body=payload,
                                      headers={"Idempotency-Key": "smoke-1"})
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["result"], result["result"])
        self.assertEqual(len(self.runtime.actions.events("ACTION_STARTED")), actions_before)

    def test_same_idempotency_key_with_changed_payload_conflicts(self):
        status, _ = self.request("POST", "/v1/tasks", body=self.payload(),
                                 headers={"Idempotency-Key": "same-key"})
        self.assertEqual(status, 200)
        status, body = self.request("POST", "/v1/tasks", body=self.payload("changed"),
                                    headers={"Idempotency-Key": "same-key"})
        self.assertEqual((status, body["error"]), (409, "idempotency_conflict"))
        self.assertEqual((self.root / "out/hello.txt").read_text(), "xin chao")

    def test_in_doubt_idempotency_is_not_replayed(self):
        payload = self.payload()
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        self.server.idempotency.begin("in-doubt", digest)
        status, body = self.request("POST", "/v1/tasks", body=payload,
                                    headers={"Idempotency-Key": "in-doubt"})
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertFalse((self.root / "out/hello.txt").exists())

    def test_unknown_routes_and_methods_fail_closed(self):
        self.assertEqual(self.request("GET", "/v1/unknown")[0], 404)
        status, body = self.request("DELETE", "/v1/tasks")
        self.assertEqual((status, body["error"]), (405, "method_not_allowed"))


if __name__ == "__main__":
    unittest.main()
