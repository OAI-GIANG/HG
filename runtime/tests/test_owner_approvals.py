"""D2-a (owner policy approval record) and D4-a (authority-authorized Memory records).

Unit tests cover every refusal; the E2E tests run compose_service + real HTTP with the
REAL D2-a and D4-a verifiers in place of the test fixtures (D3 is the real
TokenSessionSource; only the tool adapter and acceptance provider stay fixtures).
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_runtime_providers import _digest, _write_new_json
from maep.memory_evidence_providers import MemoryLedgerProvenanceVerifier, _digest as _memory_digest
from maep.native_authority import AuthorityError, TrustRootRecord
from memory import AuthorityEvidenceReader
from runtime import owner_approvals
from runtime.errors import RuntimeStartupError
from runtime.owner_approvals import AuthorizedWriteRecordVerifier, LocalPolicyApprovalVerifier, approve_policy
from runtime.production_config import compose_service
from runtime.session_auth import TokenSessionSource

fixture = __import__("e2e_fixture_factory")
composition = __import__("test_production_composition_e2e")
APPROVAL_REF = "fixture:policy-approval"      # listed in the provisioned policy's approval_evidence_refs


def make_root(generation=1):
    return TrustRootRecord.create(
        root_id="unit-root", generation=generation, created_at="2026-10-26T00:00:00Z",
        bootstrap_authorization_ref="fixture:owner", verification_method="fixture-only",
        verification_material_ref="fixture://material", policy_change_rule_ref="fixture://policy",
        evidence_ref="fixture://evidence")


class PolicyApprovalUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-d2a-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.base / "state")
        self.config = self.state["config"]
        self.root = LocalRootStore(self.config["authority_dir"]).load_active()
        self.raw = json.loads(Path(self.config["policy_path"]).read_text())
        self.policy = self.raw["policy"]
        self.approval = self.base / "approval" / "policy-approval.json"
        approve_policy(policy_path=self.config["policy_path"], authority_dir=self.config["authority_dir"],
                       approval_path=self.approval, approval_ref=APPROVAL_REF)

    def verify(self, *, record=None, policy=None, root=None):
        return LocalPolicyApprovalVerifier(self.approval).verify_policy_source(
            record or self.raw, root=root or self.root, policy=policy or self.policy)

    def rewrite(self, **changes):
        body = dict(json.loads(self.approval.read_text()), **changes)
        self.approval.unlink()
        _write_new_json(self.approval, body)

    def test_exact_policy_is_approved_with_literal_true(self):
        self.assertIs(self.verify(), True)
        self.assertEqual(os.stat(self.approval).st_mode & 0o777, 0o600)

    def test_changed_policy_version_root_or_refs_are_refused(self):
        changed = dict(self.policy, grant_ttl_seconds=61)
        self.assertIs(self.verify(record=dict(self.raw, policy=changed, policy_digest=_digest(changed)),
                                  policy=changed), False)
        other_version = dict(self.policy, version="MAEP-9.9.9")
        self.assertIs(self.verify(record=dict(self.raw, policy_digest=_digest(other_version)),
                                  policy=other_version), False)
        self.assertIs(self.verify(root=make_root(generation=2)), False)
        self.assertIs(self.verify(root=make_root(generation=1)), False)     # same generation, other digest
        no_ref = dict(self.policy, approval_evidence_refs=["other:ref"])
        self.rewrite(policy_digest=_digest(no_ref))
        self.assertIs(self.verify(record=dict(self.raw, policy_digest=_digest(no_ref)), policy=no_ref), False)

    def test_malformed_unsafe_or_missing_records_block(self):
        for changes in ({"repository": "OAI-GIANG/HG2"}, {"schema": "v0"}, {"policy_digest": "sha256:xyz"},
                        {"root_generation": True}, {"approval_ref": "bad ref"}, {"extra": 1}):
            with self.subTest(changes=changes):
                original = self.approval.read_text()
                self.rewrite(**changes)
                with self.assertRaises(AuthorityError):
                    self.verify()
                self.approval.unlink()
                self.approval.write_text(original)
                os.chmod(self.approval, 0o600)
        os.chmod(self.approval, 0o644)
        with self.assertRaises(AuthorityError):
            self.verify()
        os.chmod(self.approval, 0o600)
        link = self.base / "link.json"
        link.symlink_to(self.approval)
        with self.assertRaises(AuthorityError):
            LocalPolicyApprovalVerifier(link)
        duplicate = self.base / "dup.json"
        duplicate.write_text('{"schema": "a", "schema": "b"}')
        os.chmod(duplicate, 0o600)
        with self.assertRaises(AuthorityError):
            LocalPolicyApprovalVerifier(duplicate)
        with self.assertRaises(AuthorityError):
            LocalPolicyApprovalVerifier(self.base / "missing.json")
        with self.assertRaises(AuthorityError):
            LocalPolicyApprovalVerifier("relative.json")

    def test_approve_refuses_inactive_unlisted_tampered_or_existing(self):
        kwargs = dict(policy_path=self.config["policy_path"], authority_dir=self.config["authority_dir"])
        with self.assertRaisesRegex(AuthorityError, "overwrite"):
            approve_policy(**kwargs, approval_path=self.approval, approval_ref=APPROVAL_REF)
        with self.assertRaisesRegex(AuthorityError, "must list"):
            approve_policy(**kwargs, approval_path=self.base / "a2.json", approval_ref="owner:unlisted")
        proposed = dict(self.policy, status="PROPOSED")
        path = self.base / "proposed.json"
        _write_new_json(path, {"policy": proposed, "policy_digest": _digest(proposed)})
        with self.assertRaisesRegex(AuthorityError, "ACTIVE"):
            approve_policy(**dict(kwargs, policy_path=str(path)), approval_path=self.base / "a3.json",
                           approval_ref=APPROVAL_REF)
        tampered = self.base / "tampered.json"
        _write_new_json(tampered, {"policy": dict(self.policy, grant_ttl_seconds=5),
                                   "policy_digest": self.raw["policy_digest"]})
        with self.assertRaisesRegex(AuthorityError, "digest"):
            approve_policy(**dict(kwargs, policy_path=str(tampered)), approval_path=self.base / "a4.json",
                           approval_ref=APPROVAL_REF)

    def test_cli(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args = ["approve-policy", "--policy", self.config["policy_path"], "--authority-dir",
                    self.config["authority_dir"], "--approval-ref", APPROVAL_REF, "--approval-file"]
            self.assertEqual(owner_approvals.main(args + [str(self.base / "cli.json")]), 0)
            self.assertEqual(owner_approvals.main(args + [str(self.base / "cli.json")]), 78)
        self.assertEqual(json.loads(out.getvalue())["result"], "APPROVED")
        self.assertEqual(json.loads(err.getvalue())["result"], "BLOCKED")


class AuthorizedWriteUnitTests(unittest.TestCase):
    STORE = "/state/memory/hg.sqlite3"
    TS = {"issued_at": "2026-10-26T01:00:00Z", "expires_at": "2026-10-26T01:01:00Z"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-d4a-")
        self.addCleanup(self.tmp.cleanup)
        self.sink = LocalEvidenceSink(Path(self.tmp.name) / "evidence")
        self.root = make_root()
        self.verifier = AuthorizedWriteRecordVerifier(evidence_sink=self.sink, memory_store_path=self.STORE)

    def decision(self, event_type="authorization.decision", **changes):
        payload = {"decision": "ALLOW", "action": "WRITE",
                   "resource": f"memory:evidence/EV-1 [store:{self.STORE}]", "task_ref": "T-1",
                   "candidate_ref": "cand-1", "policy_version": "MAEP-1.2.0",
                   "root_generation": self.root.generation, **self.TS}
        payload.update(changes)
        payload["decision_digest"] = _digest(payload)
        self.sink.append({"event_type": event_type, "occurred_at": self.TS["issued_at"],
                          "payload": payload, "payload_digest": _digest(payload)})
        return payload["decision_digest"]

    def record(self, authorization_id, **changes):
        evidence = {"evidence_id": "EV-1", "result": "x"}
        binding = {"authorization_id": authorization_id, "evidence_id": "EV-1", "task_id": "T-1",
                   "candidate_ref": "cand-1", "policy_version": "MAEP-1.2.0",
                   "created_at": "2026-10-26T01:00:30Z", "memory_integrity": "PASS",
                   "evidence_digest": _memory_digest(evidence)}
        binding.update(changes)
        return {"evidence_id": "EV-1", "candidate_ref": "cand-1", "_evidence_record": evidence,
                "_memory_binding": binding}

    def check(self, record):
        return self.verifier.verify_approved_memory_record(
            record, record_type="MAEP022_APPLICABILITY", root=self.root, policy={})

    def test_write_authorized_by_this_authority_is_approved(self):
        self.assertIs(self.check(self.record(self.decision())), True)

    def test_every_mismatch_is_refused(self):
        exact = self.decision()
        cases = {
            "missing decision": self.record("sha256:" + "0" * 64),
            "malformed id": self.record("not-a-digest"),
            "no binding": {},
            "deny event": self.record(self.decision("authorization.deny", decision="DENY")),
            "read not write": self.record(self.decision(action="READ")),
            "other evidence": self.record(self.decision(resource=f"memory:evidence/EV-2 [store:{self.STORE}]")),
            "other store": self.record(self.decision(resource="memory:evidence/EV-1 [store:/other.sqlite3]")),
            "other task": self.record(self.decision(task_ref="T-2")),
            "other candidate": self.record(self.decision(candidate_ref="cand-2")),
            "other policy version": self.record(self.decision(policy_version="MAEP-1.1.0")),
            "other root generation": self.record(self.decision(root_generation=2)),
            "written after expiry": self.record(exact, created_at="2026-10-26T01:05:00Z"),
            "written before issue": self.record(exact, created_at="2026-10-26T00:59:00Z"),
        }
        for name, record in cases.items():
            with self.subTest(name):
                self.assertIs(self.check(record), False)

    def test_tampered_ledger_blocks_and_provenance_fails_closed(self):
        digest = self.decision()
        provenance = MemoryLedgerProvenanceVerifier(self.verifier)
        policy = {"status": "ACTIVE", "root_generation": 1, "version": "MAEP-1.2.0"}
        self.assertIs(provenance.validate_record_provenance(
            self.record(digest), record_type="MAEP022_APPLICABILITY", root=self.root, policy=policy), True)
        lines = self.sink.ledger_path.read_text().splitlines(keepends=True)
        self.sink.ledger_path.write_text(lines[0].replace('"WRITE"', '"READ"'))
        with self.assertRaises(AuthorityError):
            self.check(self.record(digest))
        self.assertIs(provenance.validate_record_provenance(
            self.record(digest), record_type="MAEP022_APPLICABILITY", root=self.root, policy=policy), False)

    def test_duplicate_decision_digest_is_ambiguous(self):
        digest = self.decision()
        event = json.loads(self.sink.ledger_path.read_text().splitlines()[0])
        self.sink.append({k: event[k] for k in ("event_type", "occurred_at", "payload", "payload_digest")})
        with self.assertRaisesRegex(AuthorityError, "not unique"):
            self.check(self.record(digest))

    def test_constructor_requires_ledger_and_absolute_store(self):
        with self.assertRaises(AuthorityError):
            AuthorizedWriteRecordVerifier(evidence_sink=object(), memory_store_path=self.STORE)
        with self.assertRaises(AuthorityError):
            AuthorizedWriteRecordVerifier(evidence_sink=self.sink, memory_store_path="relative.sqlite3")


class OwnerApprovalsE2ETests(composition.CompositionE2ETests):
    """compose_service + HTTP with the real D2-a, D3 and D4-a sources."""
    for _name in [n for n in dir(composition.CompositionE2ETests) if n.startswith("test_")]:
        locals()[_name] = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-e2e-d2d4-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = fixture.provision(self.tmp.name, memory_rules=True)
        self.config = self.state["config"]
        self.token = Path(self.state["token_path"]).read_text().strip()
        self.session = TokenSessionSource(**self.state["session"])
        self.approval = self.base / "authority" / "policy-approval.json"
        approve_policy(policy_path=self.config["policy_path"], authority_dir=self.config["authority_dir"],
                       approval_path=self.approval, approval_ref=APPROVAL_REF)

    def start(self, **overrides):
        overrides.setdefault("policy_verifier", LocalPolicyApprovalVerifier(self.approval))
        overrides.setdefault("memory_verifier", AuthorizedWriteRecordVerifier(
            evidence_sink=LocalEvidenceSink(self.config["evidence_dir"]),
            memory_store_path=self.config["memory_db"]))
        return super().start(**overrides)

    def last_decision(self):
        sink = LocalEvidenceSink(self.config["evidence_dir"])
        return [e["payload"] for e in sink._read_events() if e["event_type"] == "authorization.decision"][-1]

    def test_record_written_under_authority_is_approved_end_to_end(self):
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        task["inputs"] = [
            {"ref_id": fixture.NEW_EVIDENCE, "kind": "EVIDENCE", "description": "maep022:applicability"},
            {"ref_id": fixture.NEW_SUPPORT_EVIDENCE, "kind": "EVIDENCE", "description": "support"}]
        self.assertEqual(self.call(server, "POST", "/api/tasks", body={"task": task})[0], 200)
        resource = self.state["resource"]("task", fixture.NEW_TASK)
        for evidence_id, result in (
                (fixture.NEW_SUPPORT_EVIDENCE, "observed over HTTP"),
                (fixture.NEW_EVIDENCE, json.dumps(
                    {"candidate_ref": self.state["candidate_ref"], "action": "READ", "resource": resource,
                     "classification": "NOT_REQUIRED", "facts_used": ["memory-data-plane"],
                     "evidence_refs": [fixture.NEW_SUPPORT_EVIDENCE], "rule_version": "MAEP-022-v1",
                     "applicability_id": "APP-OVER-HTTP"}, sort_keys=True, separators=(",", ":")))):
            evidence = fixture.store_fixtures.MemoryStoreTests.evidence(evidence_id, self.state["candidate_ref"])
            evidence.update(evidence_type="OTHER", source_ref="hg://runtime/over-http", result=result)
            status, body = self.call(server, "POST", "/api/evidence",
                                     body={"task_id": fixture.NEW_TASK, "evidence": evidence})
            self.assertEqual(status, 200, body)
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.NEW_TASK}")
        self.assertEqual(status, 200, body)
        # decided by the task's own record (approved by D4-a), not by the policy rule
        self.assertEqual(self.last_decision()["applicability_ref"], "APP-OVER-HTTP")

    def test_out_of_band_records_are_not_approved(self):
        server = self.start()
        status, body = self.call(server, "GET", f"/api/tasks/{fixture.READ_TASK}")
        self.assertEqual(status, 403, body)
        self.assertEqual(self.decisions(), [("authorization.blocked", ["AUTHORITY_VALIDATION_FAILED"])])

    def test_policy_change_without_new_approval_blocks_immediately(self):
        server = self.start()
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        self.assertEqual(self.call(server, "POST", "/api/tasks", body={"task": task})[0], 200)
        raw = json.loads(Path(self.config["policy_path"]).read_text())
        changed = dict(raw["policy"], grant_ttl_seconds=30)
        Path(self.config["policy_path"]).unlink()
        _write_new_json(Path(self.config["policy_path"]), {"policy": changed, "policy_digest": _digest(changed)})
        self.assertEqual(self.call(server, "GET", f"/api/tasks/{fixture.NEW_TASK}")[0], 403)
        self.assertEqual(self.decisions()[-1][0], "authorization.blocked")

    def test_missing_approval_blocks_startup_and_removal_blocks_requests(self):
        server = self.start()
        verifier = LocalPolicyApprovalVerifier(self.approval)
        moved = self.base / "approval-moved.json"
        os.replace(self.approval, moved)
        task = fixture.store_fixtures.MemoryStoreTests.task(fixture.NEW_TASK)
        self.assertEqual(self.call(server, "POST", "/api/tasks", body={"task": task})[0], 403)
        self.assertNotIn(fixture.NEW_TASK, AuthorityEvidenceReader(self.config["memory_db"]).list_canonical_task_ids())
        with self.assertRaises(AuthorityError):
            LocalPolicyApprovalVerifier(self.approval)         # the binding cannot even be built
        with self.assertRaisesRegex(RuntimeStartupError, "production composition blocked"):
            compose_service(self.config, fixture.bindings(self.session, self.config, policy_verifier=verifier))


if __name__ == "__main__":
    unittest.main()
