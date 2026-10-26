"""End-to-end through runtime.production_config.compose_service and real HTTP.

Production code path: HGHTTPServer -> TokenSessionSource (D3 candidate, real) ->
MemoryStore -> MemoryNativeAuthorityAdapter -> NativePolicyEngine (LocalRootStore,
LocalPolicyProvider, GitCandidateProvider, LocalPrincipalProvider) -> TrustedApplicability
over AuthorityEvidenceReader -> MemoryLedgerProvenanceVerifier -> LocalEvidenceSink.
Owner-decision seams (D2, D4, adapter, live-state, acceptance) are test fixtures from
e2e_fixture_factory. Nothing outside a temporary directory is touched.
"""
import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread

from maep.local_authority_store import LocalEvidenceSink
from memory import AuthorityEvidenceReader
from runtime.errors import RuntimeStartupError
from runtime.production_config import compose_service
from runtime.session_auth import TokenSessionSource, revoke_session

fixture = __import__("e2e_fixture_factory")
REPO_ROOT = str(Path(__file__).resolve().parents[2])


class CompositionE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-")
        self.addCleanup(self.tmp.cleanup)
        self.state = fixture.provision(self.tmp.name)
        self.config = self.state["config"]
        self.token = Path(self.state["token_path"]).read_text().strip()
        self.session = TokenSessionSource(**self.state["session"])

    def start(self, **overrides):
        server = compose_service(self.config, fixture.bindings(self.session, self.config, **overrides))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), thread.join(timeout=2)))
        return server

    def call(self, server, method, path, *, token=True, body=None):
        conn = http.client.HTTPConnection(*server.address[:2], timeout=10)
        headers = {"Authorization": "Bearer " + self.token} if token is True else (
            {"Authorization": "Bearer " + token} if isinstance(token, str) else {})
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw))})
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def decisions(self):
        sink = LocalEvidenceSink(self.config["evidence_dir"])
        self.assertTrue(sink.verify_integrity())
        return [(e["event_type"], e["payload"].get("reason_codes")) for e in sink._read_events()
                if e["event_type"].startswith("authorization.")]

    def test_authenticated_memory_read_is_authorized_end_to_end(self):
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["task"]["task_id"], fixture.READ_TASK)
        self.assertEqual(body["result"]["candidate_ref"], self.state["candidate_ref"])
        # policy evaluation + fresh evaluation at the pre-effect recheck, both durable
        self.assertEqual(self.decisions(), [("authorization.decision", ["AUTHORIZED"])] * 2)

    def test_unauthenticated_requests_never_reach_authority(self):
        server = self.start()
        for token in (False, "x" * 64, self.token[:-1] + ("A" if self.token[-1] != "A" else "B")):
            status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}", token=token)
            self.assertEqual(status, 401, body)
        revoke_session(revocation_path=self.state["session"]["revocation_path"],
                       session_id=self.session.authenticated_context().session_id)
        self.assertEqual(self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")[0], 401)
        self.assertEqual(self.decisions(), [])

    def test_unapproved_memory_record_blocks_the_read(self):
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.UNAPPROVED_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])

    def test_candidate_change_blocks_reads_bound_to_the_old_candidate(self):
        server = self.start()
        Path(self.config["checkout"], "README.md").write_text("changed\n", encoding="utf-8")
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertIn(status, (403,), body)
        self.assertNotIn(("authorization.decision", ["AUTHORIZED"]), self.decisions())

    def test_n1_no_task_can_be_created_through_the_production_graph(self):
        # N1 (owner decision pending): authorizing WRITE memory:task/<new> needs an
        # applicability record referenced by that task's own inputs, which cannot
        # exist before the task. Policy and session both allow this write.
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        status, body = self.call(server, "POST", "/api/tasks", body={"task": task})
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])
        reader = AuthorityEvidenceReader(self.config["memory_db"])
        self.assertNotIn(fixture.NEW_TASK, reader.list_canonical_task_ids())

    # -- N10: exact resource/scope matching ------------------------------------------
    def test_n10_task_not_enumerated_in_policy_and_session_is_denied(self):
        # Approved applicability record, same candidate, but neither the policy rules nor
        # the session list this task's resource: exact matching denies it.
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.UNLISTED_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.deny", ["PRINCIPAL_SCOPE_DENIED"])])

    def test_n10_memory_restored_to_a_new_path_loses_every_authorization(self):
        # Memory resources embed the database path ("memory:task/T [store:/path]"), so a
        # backup restored elsewhere no longer matches its own applicability records,
        # the policy rules or the session scopes.
        provisioner = fixture.MemoryStore(self.config["memory_db"], principal_provider=lambda: "provisioner",
                                          policy_evaluator=fixture.store_fixtures.policy_decision,
                                          applicability_provider=fixture.store_fixtures.applicability_provider_for_test)
        restored = Path(self.tmp.name) / "restored" / "hg.sqlite3"
        restored.parent.mkdir(mode=0o700)
        provisioner.backup_to(restored, task_id=fixture.READ_TASK)
        self.config = dict(self.config, memory_db=str(restored))
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])

    # -- N1: dispatch through the production graph ---------------------------------
    def dispatch(self, server, task_id, adapter):
        request = {"task_ref": task_id, "action": fixture.DISPATCH_ACTION,
                   "resource": fixture.DISPATCH_RESOURCE, "scope": [fixture.DISPATCH_RESOURCE]}
        return self.call(server, "POST", "/api/dispatch",
                         body={"request": request, "adapter_name": "fixture", "idempotency_key": "e2e-k-1"})

    def receipts(self):
        from maep.local_runtime_providers import LocalReceiptSink
        sink = LocalReceiptSink(self.config["receipts_dir"])
        self.assertTrue(sink.verify_integrity())
        return sink.read_all()

    def test_n1_dispatch_blocked_when_the_task_record_binds_the_task_read(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.dispatch(server, fixture.RUN_READ_TASK, adapter)
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)
        # canonical task read ALLOWed (+ recheck), then the dispatch decision is BLOCKED
        self.assertEqual(self.decisions(), [("authorization.decision", ["AUTHORIZED"])] * 2
                         + [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])
        self.assertEqual([r.get("payload", r).get("outcome") for r in self.receipts()], ["BLOCKED"])

    def test_n1_dispatch_blocked_when_the_task_record_binds_the_dispatch(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.dispatch(server, fixture.RUN_EXEC_TASK, adapter)
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)
        # the canonical task read itself is BLOCKED: the one record binds the dispatch
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])
        self.assertEqual(self.receipts(), [])

    # -- policy version compatibility -----------------------------------------------
    def test_active_policy_with_another_version_blocks_memory_access(self):
        # Memory records are bound to the policy version they were written under, and
        # MemoryLedgerProvenanceVerifier requires that version to equal the active
        # policy's. A policy version change therefore invalidates every existing
        # applicability record until it is re-assessed under the new version.
        from maep.core import POLICY_VERSION
        from maep.local_runtime_providers import _digest
        raw = json.loads(Path(self.config["policy_path"]).read_text())
        raw["policy"]["version"] = POLICY_VERSION + "-next"
        raw["policy_digest"] = _digest(raw["policy"])
        Path(self.config["policy_path"]).write_text(json.dumps(raw))
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])

    def test_policy_source_rejection_blocks_startup(self):
        class Reject:
            def verify_policy_source(self, record, *, root, policy):
                return False
        with self.assertRaisesRegex(RuntimeStartupError, "production composition blocked"):
            compose_service(self.config, fixture.bindings(self.session, self.config, policy_verifier=Reject()))
        self.assertFalse(Path(self.config["idempotency_db"]).exists())

    def test_unprovisioned_memory_and_misbound_reader_block_startup(self):
        bindings = fixture.bindings(self.session, self.config)
        other = dict(self.config, memory_db=str(Path(self.tmp.name) / "other.sqlite3"))
        with self.assertRaisesRegex(RuntimeStartupError, "another Memory database"):
            compose_service(other, bindings)
        bindings["maep022-record-reader"] = AuthorityEvidenceReader(other["memory_db"])
        with self.assertRaisesRegex(RuntimeStartupError, "not provisioned"):
            compose_service(other, bindings)
        missing = dict(fixture.bindings(self.session, self.config))
        missing.pop("acceptance-provider")
        with self.assertRaisesRegex(RuntimeStartupError, "acceptance-provider"):
            compose_service(self.config, missing)


class MemoryApplicabilityRulesE2ETests(CompositionE2ETests):
    """N1 fixed: the approved policy carries a narrow memory: applicability rule."""
    for _name in [n for n in dir(CompositionE2ETests) if n.startswith("test_")]:
        locals()[_name] = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-n1-")
        self.addCleanup(self.tmp.cleanup)
        self.state = fixture.provision(self.tmp.name, memory_rules=True)
        self.config = self.state["config"]
        self.token = Path(self.state["token_path"]).read_text().strip()
        self.session = TokenSessionSource(**self.state["session"])

    def evidence(self, evidence_id):
        item = fixture.store_fixtures.MemoryStoreTests.evidence(evidence_id, self.state["candidate_ref"])
        item["source_ref"] = "test://created-over-http"
        return item

    def test_task_is_created_read_and_given_evidence_over_http(self):
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        status, body = self.call(server, "POST", "/api/tasks", body={"task": task})
        self.assertEqual(status, 200, body)
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.NEW_TASK}")
        self.assertEqual((status, body["result"]["task"]["state"]), (200, "DRAFT"), body)
        status, body = self.call(server, "POST", "/api/evidence",
                                 body={"task_id": fixture.NEW_TASK, "evidence": self.evidence(fixture.NEW_EVIDENCE)})
        self.assertEqual(status, 200, body)
        reader = AuthorityEvidenceReader(self.config["memory_db"])
        self.assertIn(fixture.NEW_TASK, reader.list_canonical_task_ids())
        self.assertIsNotNone(reader.get_evidence(fixture.NEW_TASK, fixture.NEW_EVIDENCE))
        decisions = self.decisions()
        self.assertTrue(decisions and all(d == ("authorization.decision", ["AUTHORIZED"]) for d in decisions))

    def test_rule_does_not_bypass_policy_rules_or_session_scopes(self):
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task("T-E2E-NOT-IN-POLICY")
        status, body = self.call(server, "POST", "/api/tasks", body={"task": task})
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.deny", ["PRINCIPAL_SCOPE_DENIED"])])
        status, body = self.call(server, "POST", "/api/evidence",
                                 body={"task_id": fixture.READ_TASK, "evidence": self.evidence("EV-NOT-LISTED")})
        self.assertEqual(status, 403, body)

    def test_unapproved_task_record_still_blocks_memory_reads(self):
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.UNAPPROVED_TASK}")
        self.assertEqual(status, 403, body)

    def test_dispatch_runs_when_the_task_record_binds_it(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.dispatch(server, fixture.RUN_EXEC_TASK, adapter)
        self.assertEqual(status, 200, body)
        self.assertEqual(adapter.calls, 1)
        outcomes = [r.get("payload", r).get("outcome") for r in self.receipts()]
        self.assertEqual(outcomes, ["SUCCESS"])

    def test_dispatch_without_its_own_record_stays_blocked(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.dispatch(server, fixture.RUN_READ_TASK, adapter)
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)

    def test_capability_affecting_dispatch_without_gate_is_blocked(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        status, body = self.dispatch(server, fixture.RUN_REQ_TASK, adapter)
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)
        self.assertIn(("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"]), self.decisions())

    def test_dispatch_naming_a_memory_resource_is_refused(self):
        adapter = fixture.FixtureAdapter()
        server = self.start(adapter=adapter)
        request = {"task_ref": fixture.RUN_EXEC_TASK, "action": "WRITE",
                   "resource": f"memory:task/{fixture.RUN_EXEC_TASK}", "scope": [fixture.DISPATCH_RESOURCE]}
        status, body = self.call(server, "POST", "/api/dispatch",
                                 body={"request": request, "adapter_name": "fixture", "idempotency_key": "e2e-mem"})
        self.assertEqual(status, 403, body)
        self.assertEqual(adapter.calls, 0)


class ServiceProcessE2ETests(unittest.TestCase):
    """python -m runtime.service lifecycle on its own port and state directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-proc-")
        self.addCleanup(self.tmp.cleanup)
        self.port = fixture.free_port()
        self.state = fixture.provision(self.tmp.name, port=self.port)
        self.token = Path(self.state["token_path"]).read_text().strip()
        self.env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": REPO_ROOT,
                    "PYTHONDONTWRITEBYTECODE": "1", "HOME": self.tmp.name,
                    "HG_RUNTIME_FACTORY": "runtime.tests.e2e_fixture_factory:create_service",
                    fixture.FIXTURE_ENV: self.tmp.name}

    def run_service(self):
        proc = subprocess.Popen([sys.executable, "-u", "-m", "runtime.service"], cwd=REPO_ROOT, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        line = proc.stdout.readline()
        self.assertTrue(line.startswith("HG_RUNTIME_READY"), line + proc.stderr.read() if not line else line)
        self.assertIn(f"port={self.port}", line)
        return proc

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers={"Authorization": "Bearer " + self.token})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def stop(self, proc):
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=20), 0)
        proc.stdout.close()
        proc.stderr.close()

    def test_start_serve_stop_restart_keeps_state_intact(self):
        proc = self.run_service()
        self.assertEqual(self.get(f"/api/tasks/{fixture.READ_TASK}")[0], 200)
        self.stop(proc)
        sink = LocalEvidenceSink(self.state["config"]["evidence_dir"])
        self.assertTrue(sink.verify_integrity())
        first = len(sink._read_events())
        proc = self.run_service()
        status, body = self.get(f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 200, body)
        self.stop(proc)
        self.assertTrue(LocalEvidenceSink(self.state["config"]["evidence_dir"]).verify_integrity())
        self.assertEqual(len(LocalEvidenceSink(self.state["config"]["evidence_dir"])._read_events()), first + 2)
        integrity = AuthorityEvidenceReader(self.state["config"]["memory_db"]).check_integrity(task_id=fixture.READ_TASK)
        self.assertEqual(integrity["status"], "PASS")


class CompositionLiveStateTests(CompositionE2ETests):
    """compose_service wires the production LocalLiveStateProvider into Memory."""
    for _name in [n for n in dir(CompositionE2ETests) if n.startswith("test_")]:
        locals()[_name] = None

    def test_memory_observes_live_state_through_the_composed_provider(self):
        server = self.start()
        observed = server.runtime.memory._live_state(fixture.READ_TASK)
        self.assertEqual(observed["candidate_ref"], self.state["candidate_ref"])
        self.assertEqual(observed["resources"][0]["resource_id"], "repo:OAI-GIANG/HG")
        Path(self.config["checkout"], "README.md").write_text("drift\n", encoding="utf-8")
        self.assertNotEqual(server.runtime.memory._live_state(fixture.READ_TASK)["candidate_ref"],
                            self.state["candidate_ref"])


if __name__ == "__main__":
    unittest.main()
