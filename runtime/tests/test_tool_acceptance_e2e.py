"""Full task lifecycle over HTTP with the real fs.write adapter and acceptance provider.

compose_service + HGHTTPServer + D3 TokenSessionSource + D2-a LocalPolicyApprovalVerifier +
D4-a AuthorizedWriteRecordVerifier + RootedFileWriteAdapter + ReadbackAcceptanceProvider.
No fixture seam is left in the path: every task, record, transition and effect below
goes through authority. The owner steps (policy, approval, session) are done the way
the owner tooling does them, inside a temporary directory.

create -> applicability/support evidence -> READY..PLANNED -> AUTHORIZED/RUNNING (action
authority) -> dispatch fs.write -> result evidence -> VERIFYING -> ACCEPTED (approved
evidence + independent read-back) -> CLOSED_VERIFIED, plus the refusals around it.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from maep.core import POLICY_VERSION
from maep.local_authority_store import LocalEvidenceSink
from maep.local_runtime_providers import LocalReceiptSink, _digest, _write_new_json
from memory import AuthorityEvidenceReader
from runtime.acceptance import build_acceptance_provider
from runtime.owner_approvals import AuthorizedWriteRecordVerifier, LocalPolicyApprovalVerifier, approve_policy
from runtime.session_auth import TokenSessionSource, issue_session
from tools_automation.file_write_adapter import RootedFileWriteAdapter

fixture = __import__("e2e_fixture_factory")
composition = __import__("test_production_composition_e2e")
TASK = "T-E2E-LIFE"
APP, SUP, RESULT = "EV-LIFE-APP", "EV-LIFE-SUP", "EV-LIFE-RESULT"
PATH = "out/result.txt"
FILE_RESOURCE, FILE_SCOPE = "file:" + PATH, "file:out"
CONTENT = "hello from runtime.service\n"


class ToolAcceptanceLifecycleE2ETests(composition.CompositionE2ETests):
    for _name in [n for n in dir(composition.CompositionE2ETests) if n.startswith("test_")]:
        locals()[_name] = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-life-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.tmp.name, memory_rules=True)
        self.config = self.state["config"]
        self.tool_root = self.base / "tool-root"
        self.tool_root.mkdir(mode=0o700)
        self._owner_grants_lifecycle()

    # -- owner steps (policy rules, D2-a approval, D3 session) -------------------------
    def _owner_grants_lifecycle(self):
        res = self.state["resource"]
        rules = [
            {"action": "READ", "resource": res("task", TASK), "scope": [f"memory:task:{TASK}:read"]},
            {"action": "WRITE", "resource": res("task", TASK),
             "scope": [f"memory:task:{TASK}:write", f"memory:task:{TASK}:transition"]},
            {"action": "WRITE", "resource": FILE_RESOURCE, "scope": [FILE_SCOPE]},
        ] + [{"action": "WRITE", "resource": res("evidence", ev), "scope": [f"memory:task:{TASK}:evidence:write"]}
             for ev in (APP, SUP, RESULT)]
        rules = [dict(rule, effect="ALLOW") for rule in rules]
        policy_path = Path(self.config["policy_path"])
        raw = json.loads(policy_path.read_text())
        policy = dict(raw["policy"], rules=raw["policy"]["rules"] + rules,
                      approval_evidence_refs=["owner:lifecycle-approval"])
        policy_path.unlink()
        _write_new_json(policy_path, {"policy": policy, "policy_digest": _digest(policy)})
        self.approval = self.base / "authority" / "policy-approval.json"
        approve_policy(policy_path=str(policy_path), authority_dir=self.config["authority_dir"],
                       approval_path=self.approval, approval_ref="owner:lifecycle-approval")
        resources = sorted({rule["resource"] for rule in rules})
        scopes = sorted({scope for rule in rules for scope in rule["scope"]})
        session_dir = self.base / "life-session"
        issue_session(session_path=session_dir / "session.json", token_path=session_dir / "token",
                      revocation_path=session_dir / "revocations.json", principal_id="STT", valid_days=1,
                      capabilities=["READ", "WRITE"], resource_scopes=resources, allowed_scopes=scopes)
        self.session = TokenSessionSource(session_path=session_dir / "session.json",
                                          revocation_path=session_dir / "revocations.json")
        self.token = (session_dir / "token").read_text().strip()

    def start(self, *, adapter=None):
        policy_verifier = LocalPolicyApprovalVerifier(self.approval)
        memory_verifier = AuthorizedWriteRecordVerifier(
            evidence_sink=LocalEvidenceSink(self.config["evidence_dir"]), memory_store_path=self.config["memory_db"])
        self.adapter = adapter or RootedFileWriteAdapter(self.tool_root)
        bindings = fixture.bindings(self.session, self.config, policy_verifier=policy_verifier,
                                    memory_verifier=memory_verifier)
        bindings["tool-adapter-registry"] = {"fs.write": self.adapter}
        bindings["acceptance-provider"] = build_acceptance_provider(
            config=self.config, policy_verifier=policy_verifier, memory_verifier=memory_verifier,
            file_adapters={"fs.write": RootedFileWriteAdapter(self.tool_root)})
        from runtime.production_config import compose_service
        from threading import Thread
        server = compose_service(self.config, bindings)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), thread.join(timeout=2)))
        return server

    # -- lifecycle helpers -------------------------------------------------------------
    def ok(self, server, method, path, body=None):
        status, data = self.call(server, method, path, body=body)
        self.assertEqual(status, 200, data)
        return data

    def evidence(self, evidence_id, evidence_type, result):
        item = fixture.store_fixtures.MemoryStoreTests.evidence(evidence_id, self.state["candidate_ref"])
        item.update(evidence_type=evidence_type, source_ref="hg://runtime/lifecycle",
                    result=result if isinstance(result, str) else json.dumps(result, sort_keys=True,
                                                                              separators=(",", ":")))
        return {"task_id": TASK, "evidence": item}

    def version(self, server):
        return self.ok(server, "GET", f"/api/tasks/{TASK}")["result"]["row_version"]

    def transition(self, server, target, *, expect=200, action=False):
        body = {"target": target, "expected_version": self.version(server)}
        if action:
            body["action_request"] = {
                "principal": "STT", "action": "WRITE", "resource": FILE_RESOURCE, "scope": [FILE_SCOPE],
                "task_id": TASK, "policy_version": POLICY_VERSION, "capability_affecting": False,
                "capability_gate": {"applies": False, "reason": "file write inside the configured tool root"}}
        status, data = self.call(server, "POST", f"/api/tasks/{TASK}/transition", body=body)
        self.assertEqual(status, expect, data)
        return data

    def state_of(self, server):
        return self.ok(server, "GET", f"/api/tasks/{TASK}")["result"]["task"]["state"]

    def dispatch(self, server, key="life-k-1", path=PATH):
        request = {"task_ref": TASK, "action": "WRITE", "resource": FILE_RESOURCE, "scope": [FILE_SCOPE],
                   "params": {"path": path, "content": CONTENT}}
        return self.call(server, "POST", "/api/dispatch",
                         body={"request": request, "adapter_name": "fs.write", "idempotency_key": key})

    def run_to_running(self, server):
        task = fixture.store_fixtures.MemoryStoreTests.task(TASK)
        task["scope"]["include"] += [FILE_RESOURCE, FILE_SCOPE]
        task["inputs"] = [{"ref_id": APP, "kind": "EVIDENCE", "description": "maep022:applicability"},
                          {"ref_id": SUP, "kind": "EVIDENCE", "description": "support"}]
        self.ok(server, "POST", "/api/tasks", {"task": task})
        self.ok(server, "POST", "/api/evidence", self.evidence(SUP, "OBSERVATION", "file write is the planned effect"))
        self.ok(server, "POST", "/api/evidence", self.evidence(APP, "OTHER", {
            "candidate_ref": self.state["candidate_ref"], "action": "WRITE", "resource": FILE_RESOURCE,
            "classification": "NOT_REQUIRED", "facts_used": ["file-effect-inside-tool-root"],
            "evidence_refs": [SUP], "rule_version": "MAEP-022-v1", "applicability_id": "APP-LIFE"}))
        for target in ("READY", "ASSESSED", "PLANNED"):
            self.transition(server, target)
        self.transition(server, "AUTHORIZED", action=True)
        self.transition(server, "RUNNING", action=True)
        self.assertEqual(self.state_of(server), "RUNNING")

    def record_result(self, server, status="PASS"):
        self.ok(server, "POST", "/api/evidence", self.evidence(RESULT, "TEST_RESULT", {
            "status": status, "criterion_refs": ["AC-MK-1"],
            "observed": "sha256:" + hashlib.sha256(CONTENT.encode()).hexdigest()}))

    def effect_receipts(self):
        return [r["payload"] for r in LocalReceiptSink(self.config["receipts_dir"]).read_all()
                if str(r["payload"].get("receipt_id", "")).startswith("effect:")]

    # -- tests ---------------------------------------------------------------------------
    def test_full_lifecycle_reaches_closed_verified_with_independent_readback(self):
        server = self.start()
        self.run_to_running(server)
        status, body = self.dispatch(server)
        self.assertEqual(status, 200, body)
        self.assertEqual((self.tool_root / PATH).read_text(), CONTENT)
        [receipt] = self.effect_receipts()
        self.assertEqual((receipt["outcome"], receipt["task_ref"]), ("SUCCESS", TASK))
        self.record_result(server)
        self.transition(server, "VERIFYING")
        self.transition(server, "ACCEPTED")
        self.transition(server, "CLOSED_VERIFIED")
        self.assertEqual(self.state_of(server), "CLOSED_VERIFIED")
        events = AuthorityEvidenceReader(self.config["memory_db"]).get_events(TASK, limit=1000)
        path = [e["payload"]["to_state"] for e in events if e["event_type"] == "task.transitioned"]
        self.assertEqual(path, ["READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING", "VERIFYING",
                                "ACCEPTED", "CLOSED_VERIFIED"])
        closing = [e["payload"] for e in events if e["event_type"] == "task.transitioned"][-1]
        self.assertTrue(closing["transition_authorization_id"].startswith("sha256:"))
        [gate] = closing["acceptance"]["mandatory_gates"]
        self.assertEqual((gate["status"], gate["evidence_refs"], gate["readback"]["checked"]), ("PASS", [RESULT], 1))
        self.assertEqual(closing["acceptance"]["closure"]["verifier"], "hg.runtime.acceptance.readback-v1")
        # every authority decision in the run is durable and none was a fixture bypass
        self.assertNotIn("authorization.blocked", [d[0] for d in self.decisions()])

    def test_file_changed_after_the_effect_blocks_acceptance(self):
        server = self.start()
        self.run_to_running(server)
        self.assertEqual(self.dispatch(server)[0], 200)
        self.record_result(server)
        self.transition(server, "VERIFYING")
        (self.tool_root / PATH).write_text("tampered\n")
        self.transition(server, "ACCEPTED", expect=403)
        self.assertEqual(self.state_of(server), "VERIFYING")

    def test_failing_or_missing_result_evidence_blocks_acceptance(self):
        server = self.start()
        self.run_to_running(server)
        self.assertEqual(self.dispatch(server)[0], 200)
        self.transition(server, "VERIFYING")              # support/applicability evidence exist
        self.transition(server, "ACCEPTED", expect=403)   # no TEST_RESULT naming the criterion
        self.record_result(server, status="FAIL")
        self.transition(server, "ACCEPTED", expect=403)
        self.assertEqual(self.state_of(server), "VERIFYING")

    def reconcile(self, server, key="life-k-1"):
        return self.call(server, "POST", "/api/reconcile", body={"task_ref": TASK, "idempotency_key": key})

    def test_unknown_effect_blocks_effects_and_acceptance_until_reconciled_applied(self):
        class WritesThenCrashes(RootedFileWriteAdapter):
            def execute(self, **kwargs):
                super().execute(**kwargs)
                raise TimeoutError("connection lost after the write")
        server = self.start(adapter=WritesThenCrashes(self.tool_root))
        self.run_to_running(server)
        status, body = self.dispatch(server)
        self.assertNotEqual(status, 200, body)
        self.assertEqual([r["outcome"] for r in self.effect_receipts()], ["UNKNOWN"])
        self.assertEqual(self.dispatch(server, key="life-k-2")[0], 403)     # MAEP-018: pending blocks
        self.assertEqual(len(self.effect_receipts()), 1)
        self.record_result(server)
        self.transition(server, "VERIFYING")
        self.transition(server, "ACCEPTED", expect=403)                    # unreconciled
        self.assertEqual(self.reconcile(server, key="no-such-key")[0], 403)
        status, body = self.reconcile(server)
        self.assertEqual((status, body["result"]["finding"]), (200, "APPLIED"), body)
        self.assertEqual(self.reconcile(server)[0], 403)                    # nothing pending any more
        self.transition(server, "ACCEPTED")                                  # read-back of the confirmed intent

    def test_unknown_effect_reconciled_not_applied_allows_a_new_attempt(self):
        class CrashesBeforeWriting(RootedFileWriteAdapter):
            def execute(self, **kwargs):
                raise TimeoutError("connection lost before the write")
        crashing = CrashesBeforeWriting(self.tool_root)
        server = self.start(adapter=crashing)
        self.run_to_running(server)
        self.assertNotEqual(self.dispatch(server)[0], 200)
        status, body = self.reconcile(server)
        self.assertEqual((status, body["result"]["finding"]), (200, "NOT_APPLIED"), body)
        crashing.execute = lambda **kwargs: RootedFileWriteAdapter.execute(crashing, **kwargs)
        self.assertEqual(self.dispatch(server, key="life-k-2")[0], 200)
        self.assertEqual((self.tool_root / PATH).read_text(), CONTENT)

    def test_pending_unknown_effect_survives_a_restart(self):
        class WritesThenCrashes(RootedFileWriteAdapter):
            def execute(self, **kwargs):
                super().execute(**kwargs)
                raise TimeoutError("lost")
        first = self.start(adapter=WritesThenCrashes(self.tool_root))
        self.run_to_running(first)
        self.assertNotEqual(self.dispatch(first)[0], 200)
        first.shutdown()
        restarted = self.start()                         # new process state, same durable ledgers
        self.assertEqual(self.dispatch(restarted, key="life-k-2")[0], 403)
        self.assertEqual(len(self.effect_receipts()), 1)
        self.assertEqual(self.reconcile(restarted)[1]["result"]["finding"], "APPLIED")
        self.assertEqual(self.dispatch(restarted, key="life-k-2")[0], 200)

    def test_reconciliation_read_requires_authority(self):
        class WritesThenCrashes(RootedFileWriteAdapter):
            def execute(self, **kwargs):
                super().execute(**kwargs)
                raise TimeoutError("lost")
        server = self.start(adapter=WritesThenCrashes(self.tool_root))
        self.run_to_running(server)
        self.dispatch(server)
        from runtime.session_auth import revoke_session
        revoke_session(revocation_path=self.session.revocation_path,
                       session_id=self.session.authenticated_context().session_id)
        self.assertEqual(self.reconcile(server)[0], 401)

    def test_adapter_refuses_a_path_that_differs_from_the_authorized_resource(self):
        server = self.start()
        self.run_to_running(server)
        status, body = self.dispatch(server, path="out/other.txt")
        self.assertEqual(status, 200, body)          # dispatch completed with a known FAILURE outcome
        self.assertEqual([r["outcome"] for r in self.effect_receipts()], ["FAILURE"])
        self.assertFalse((self.tool_root / "out").exists())

    def test_replayed_idempotency_key_never_reaches_the_adapter_again(self):
        server = self.start()
        self.run_to_running(server)
        self.assertEqual(self.dispatch(server)[0], 200)
        (self.tool_root / PATH).unlink()
        status, body = self.dispatch(server)          # same key
        self.assertEqual(status, 403, body)
        self.assertFalse((self.tool_root / PATH).exists())
        self.assertEqual(len(self.effect_receipts()), 1)

    def test_dispatch_before_running_and_outside_scope_is_refused(self):
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task(TASK)
        task["scope"]["include"] += [FILE_RESOURCE, FILE_SCOPE]
        self.ok(server, "POST", "/api/tasks", {"task": task})
        self.assertEqual(self.dispatch(server)[0], 403)     # DRAFT, not RUNNING
        self.assertFalse((self.tool_root / "out").exists())
        self.assertEqual(self.effect_receipts(), [])


if __name__ == "__main__":
    unittest.main()
