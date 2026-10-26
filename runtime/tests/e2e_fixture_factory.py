"""TEST-ONLY provisioning and factory for runtime.service end-to-end tests.

Everything that is an owner decision is a clearly labelled fixture here:
  D2 policy-source verifier, D4 approved-Memory-record rule, tool adapter and acceptance
  provider. They must never be registered in runtime/production_config.py.
Everything else is the production code path: runtime.production_config.compose_service,
LocalRootStore/LocalPolicyProvider/GitCandidateProvider/LocalEvidenceSink, NativePolicyEngine,
Trusted* providers over memory.AuthorityEvidenceReader, MemoryStore, HGHTTPServer, and the
D3 candidate runtime.session_auth.TokenSessionSource (real implementation, not registered).

Provisioning writes only beneath the directory it is given.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess

from maep.core import POLICY_VERSION
from maep.local_authority_store import LocalRootStore
from maep.local_runtime_providers import GitCandidateProvider, _digest
from maep.native_authority import TrustRootRecord
from memory import MemoryStore
from memory.tests import test_store as store_fixtures
from runtime.session_auth import TokenSessionSource, issue_session

FIXTURE_ENV = "HG_E2E_FIXTURE_DIR"
APPROVED_SOURCE = "test://approved-source"
READ_TASK = "T-E2E-READ"
UNAPPROVED_TASK = "T-E2E-UNAPPROVED"
NEW_TASK = "T-E2E-NEW"
UNLISTED_TASK = "T-E2E-UNLISTED"        # approved record, absent from policy and session (N10)
RUN_READ_TASK = "T-E2E-RUN-READ"        # RUNNING; its one applicability record binds the task read
RUN_EXEC_TASK = "T-E2E-RUN-EXEC"        # RUNNING; its one applicability record binds the dispatch
RUN_REQ_TASK = "T-E2E-RUN-REQ"          # RUNNING; its record classifies the dispatch REQUIRED (no gate)
DISPATCH_ACTION, DISPATCH_RESOURCE = "EXECUTE", "tool:fixture:echo"
NEW_EVIDENCE = "EV-NEW-1"
NEW_SUPPORT_EVIDENCE = "EV-NEW-SUP"
MEMORY_RULES = [{"rule_id": "memory-data-plane", "actions": ["READ", "WRITE"],
                 "resource_prefix": "memory:", "classification": "NOT_REQUIRED"}]


class FixturePolicySourceVerifier:
    """FIXTURE for D2 (owner decision): accepts only a policy file marked test-only."""
    def verify_policy_source(self, record, *, root, policy):
        return record.get("fixture_approval") == "test-only-not-production"


class FixtureMemoryRecordVerifier:
    """FIXTURE for D4 (owner decision): approves records from one test source."""
    def verify_approved_memory_record(self, record, *, record_type, root, policy):
        return record.get("_evidence_record", {}).get("source_ref") == APPROVED_SOURCE


class FixtureAdapter:
    """FIXTURE tool adapter; records calls, performs no effect."""
    def __init__(self):
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return {"outcome": "SUCCESS", "idempotent": False, "provider_ref": "fixture-effect"}


def _fixture_acceptance(task_id, target):
    raise RuntimeError("fixture acceptance provider: not exercised by these tests")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _git(checkout: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(checkout), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def provision(base: str | Path, *, port: int = 0, memory_rules: bool = False) -> dict:
    """Create an isolated HG state directory; returns config and the bearer token path."""
    base = Path(base)
    checkout = base / "checkout"
    checkout.mkdir(parents=True)
    _git(checkout, "init", "-q")
    _git(checkout, "remote", "add", "origin", "https://github.com/OAI-GIANG/HG.git")
    (checkout / "README.md").write_text("e2e fixture checkout\n", encoding="utf-8")
    _git(checkout, "add", "README.md")
    _git(checkout, "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid",
         "commit", "-q", "-m", "fixture")
    candidate = GitCandidateProvider(checkout).inspect(str(checkout))
    candidate_ref = candidate["candidate_ref"]

    config = {
        "schema": "hg-runtime-factory-config-v1", "host": "127.0.0.1", "port": port,
        "checkout": str(checkout), "authority_dir": str(base / "authority"),
        "policy_path": str(base / "policy.json"), "evidence_dir": str(base / "evidence"),
        "memory_db": str(base / "memory" / "hg.sqlite3"),
        "idempotency_db": str(base / "idempotency.sqlite3"), "receipts_dir": str(base / "receipts"),
    }
    LocalRootStore(config["authority_dir"]).store_active(TrustRootRecord.create(
        root_id="e2e-fixture-root", generation=1, created_at="2026-10-26T00:00:00Z",
        bootstrap_authorization_ref="fixture:owner", verification_method="fixture-only",
        verification_material_ref="fixture://material", policy_change_rule_ref="fixture://policy",
        evidence_ref="fixture://evidence"))

    # Memory provisioning mirrors an owner bootstrap: done out of band with the test-only
    # evaluator, because no production path can create the first task (finding N1).
    db = Path(config["memory_db"]).absolute()
    store = MemoryStore(db, principal_provider=lambda: "provisioner",
                        policy_evaluator=store_fixtures.policy_decision,
                        applicability_provider=store_fixtures.applicability_provider_for_test)
    store.initialize(task_id="T-PROVISION")

    def resource(kind, task_id):
        return f"memory:{kind}/{task_id} [store:{db}]"

    def add_task(task_id, source, *, app_action="READ", app_resource=None, running=False,
                 classification="NOT_REQUIRED"):
        task = store_fixtures.MemoryStoreTests.task(task_id)
        task["inputs"] = [{"ref_id": f"{task_id}-APP", "kind": "EVIDENCE", "description": "maep022:applicability"},
                          {"ref_id": f"{task_id}-SUP", "kind": "EVIDENCE", "description": "support"}]
        if running:
            task["scope"]["include"].append(DISPATCH_RESOURCE)
        store.create_task(task, candidate_ref=candidate_ref)
        for evidence_id, payload in (
                (f"{task_id}-SUP", {"candidate_ref": candidate_ref}),
                (f"{task_id}-APP", {"candidate_ref": candidate_ref, "action": app_action,
                                    "resource": app_resource or resource("task", task_id),
                                    "classification": classification,
                                    "facts_used": ["memory-data-plane"], "evidence_refs": [f"{task_id}-SUP"],
                                    "rule_version": "MAEP-022-v1", "applicability_id": f"APP-{task_id}"})):
            evidence = store_fixtures.MemoryStoreTests.evidence(evidence_id, candidate_ref)
            evidence.update(evidence_type="OTHER", source_ref=source,
                            result=json.dumps(payload, sort_keys=True, separators=(",", ":")))
            store.record_evidence(task_id, evidence)
        if running:
            # Provisioning-only lifecycle under the test evaluator (no production path exists, N1).
            for state, version in (("READY", 1), ("ASSESSED", 2), ("PLANNED", 3)):
                store.transition_task(task_id, state, expected_version=version)
            action_request = {"principal": "provisioner", "action": DISPATCH_ACTION,
                              "resource": DISPATCH_RESOURCE, "scope": [DISPATCH_RESOURCE],
                              "task_id": task_id, "policy_version": POLICY_VERSION,
                              "capability_affecting": False,
                              "capability_gate": {"applies": False, "reason": "fixture echo adapter"}}
            store.transition_task(task_id, "AUTHORIZED", expected_version=4, action_request=action_request)
            store.transition_task(task_id, "RUNNING", expected_version=5, action_request=action_request)

    add_task(READ_TASK, APPROVED_SOURCE)
    add_task(UNAPPROVED_TASK, "test://not-approved")
    add_task(UNLISTED_TASK, APPROVED_SOURCE)
    add_task(RUN_READ_TASK, APPROVED_SOURCE, running=True)
    add_task(RUN_EXEC_TASK, APPROVED_SOURCE, app_action=DISPATCH_ACTION, app_resource=DISPATCH_RESOURCE,
             running=True)
    add_task(RUN_REQ_TASK, APPROVED_SOURCE, app_action=DISPATCH_ACTION, app_resource=DISPATCH_RESOURCE,
             running=True, classification="REQUIRED")

    rules, resources, scopes = [], [], []
    for task_id in (READ_TASK, UNAPPROVED_TASK, RUN_READ_TASK, RUN_EXEC_TASK, RUN_REQ_TASK, NEW_TASK):
        rules.append({"action": "READ", "resource": resource("task", task_id),
                      "scope": [f"memory:task:{task_id}:read"], "effect": "ALLOW"})
        resources.append(resource("task", task_id))
        scopes.append(f"memory:task:{task_id}:read")
    rules.append({"action": DISPATCH_ACTION, "resource": DISPATCH_RESOURCE,
                  "scope": [DISPATCH_RESOURCE], "effect": "ALLOW"})
    resources.append(DISPATCH_RESOURCE)
    scopes.append(DISPATCH_RESOURCE)
    for evidence_id in (NEW_EVIDENCE, NEW_SUPPORT_EVIDENCE):
        rules.append({"action": "WRITE", "resource": resource("evidence", evidence_id),
                      "scope": [f"memory:task:{NEW_TASK}:evidence:write"], "effect": "ALLOW"})
        resources.append(resource("evidence", evidence_id))
    scopes.append(f"memory:task:{NEW_TASK}:evidence:write")
    rules.append({"action": "WRITE", "resource": resource("task", NEW_TASK),
                  "scope": [f"memory:task:{NEW_TASK}:write"], "effect": "ALLOW"})
    scopes.append(f"memory:task:{NEW_TASK}:write")    # resource already listed for its READ rule
    policy = {"status": "ACTIVE", "version": POLICY_VERSION, "root_generation": 1,
              "approval_evidence_refs": ["fixture:policy-approval"], "grant_ttl_seconds": 60, "rules": rules}
    if memory_rules:
        policy["applicability_rules"] = MEMORY_RULES
    policy_path = Path(config["policy_path"])
    fd = os.open(policy_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"policy": policy, "policy_digest": _digest(policy),
                   "fixture_approval": "test-only-not-production"}, handle)

    session = {"session_path": str(base / "session" / "session.json"),
               "revocation_path": str(base / "session" / "revocations.json")}
    issue_session(session_path=session["session_path"], token_path=base / "session" / "token",
                  revocation_path=session["revocation_path"], principal_id="STT", valid_days=1,
                  capabilities=["READ", "WRITE", DISPATCH_ACTION], resource_scopes=resources,
                  allowed_scopes=scopes)
    (base / "fixture.json").write_text(json.dumps({"config": config, "session": session}), encoding="utf-8")
    return {"config": config, "session": session, "token_path": str(base / "session" / "token"),
            "candidate_ref": candidate_ref, "resource": resource}


def bindings(session: TokenSessionSource, config: dict, *, policy_verifier=None, adapter=None,
             memory_verifier=None) -> dict:
    from memory import AuthorityEvidenceReader
    return {
        "approved-policy-source-verifier": policy_verifier or FixturePolicySourceVerifier(),
        "authenticated-session-resolver": session,
        "request-authenticator": session.authenticate_request,
        "authenticated-context-provider": session.authenticated_context,
        "approved-memory-record-verifier": memory_verifier or FixtureMemoryRecordVerifier(),
        "maep022-record-reader": AuthorityEvidenceReader(config["memory_db"]),
        "tool-adapter-registry": {"fixture": adapter or FixtureAdapter()},
        "acceptance-provider": _fixture_acceptance,
    }


def create_service():
    """HG_RUNTIME_FACTORY target for process-level E2E tests only."""
    from runtime.production_config import compose_service
    doc = json.loads((Path(os.environ[FIXTURE_ENV]) / "fixture.json").read_text(encoding="utf-8"))
    session = TokenSessionSource(**doc["session"])
    return compose_service(doc["config"], bindings(session, doc["config"]))
