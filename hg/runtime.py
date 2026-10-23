"""Runtime assembly (MIID layer 11): the one place HG's components are wired together.

Two ledgers live in the work directory: `tasks.jsonl` (task-state owner,
maep.task_store.TaskStore) and `actions.jsonl` (ActionGateway). If they already hold
events the runtime resumes from them (RT-05) instead of starting over.

Authority (RT-06): `grants` are per-task grants for PolicyEvaluator. With
`authority=CanonicalManifest.from_github()` every decision must ALSO be permitted by a live
grant in the canonical owner manifest on `main` (AnchoredPolicyEvaluator); the runtime is
then in "anchored" trust mode. Without it the runtime is in "fixture" trust mode: the
caller's grants are trusted as given, which is only appropriate for tests and the
self-check: it must be requested explicitly (`allow_fixture_grants=True`) and is reported
as such (`runtime.trust`). With neither, build_runtime refuses to start.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from maep.ledger import read_events
from maep.authority.anchored import AnchoredPolicyEvaluator
from maep.authority.canonical_source import CanonicalManifest
from maep.authority.issuer import IssuedGrantEvaluator, TaskGrantIssuer
from maep.core import MAEPError, enforce_execution_mode
from maep.policy import PolicyEvaluator
from maep.task_store import TaskStore
from hg.brain.orchestrator import BrainOrchestrator
from hg.tools.code import CodeDiffAdapter, CodeSearchAdapter, SymbolIndexAdapter, TestRunAdapter, UrlReadAdapter
from hg.tools.gateway import ActionGateway, LocalFileReadAdapter, LocalFileWriteAdapter
from hg.verification.evidence import AcceptanceGate, EventLog

DEFAULT_PRINCIPAL = "STT"
AUDIT_ONLY_PRINCIPAL = "HG_AUDIT"


def utcnow():
    return datetime.now(timezone.utc)


def open_task_store(path, evaluator, clock):
    path = Path(path)
    if path.exists() and read_events(path):
        return TaskStore.restore(path, policy_evaluator=evaluator, clock=clock)
    return TaskStore(path, policy_evaluator=evaluator, clock=clock)


def build_runtime(workdir, grants, *, principal=DEFAULT_PRINCIPAL, mode="AUTHORIZED_EXECUTION",
                  verifiers=None, clock=None, extra_adapters=(), condition_provider=None, authority=None,
                  allow_fixture_grants=False, issue_task_grants=False, memory=None, grant_ttl_s=3600):
    enforce_execution_mode(mode, "READ")
    if mode == "AUDIT_ONLY":
        if principal != AUDIT_ONLY_PRINCIPAL:
            raise MAEPError("AUDIT_ONLY requires principal='HG_AUDIT'")
        if allow_fixture_grants:
            raise MAEPError("AUDIT_ONLY forbids fixture grants")
        if authority is not None:
            raise MAEPError("AUDIT_ONLY loads canonical authority internally; caller-supplied authority is forbidden")
        authority = CanonicalManifest.from_github()
        if issue_task_grants and list(grants):
            raise MAEPError("AUDIT_ONLY task-grant issuance cannot also accept caller-supplied grants")
    if authority is not None and allow_fixture_grants:
        raise MAEPError("pass either authority or allow_fixture_grants, not both")
    if issue_task_grants and (authority is None or list(grants)):
        raise MAEPError("issue_task_grants needs authority and no caller-supplied grants")
    if authority is None and not allow_fixture_grants:
        raise MAEPError("unanchored runtime refused: pass authority=CanonicalManifest.from_github(), "
                        "or allow_fixture_grants=True for tests and self-checks (RT-06)")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    root = workdir / "root"
    root.mkdir(exist_ok=True)
    clock = clock or utcnow
    issuer = None
    if issue_task_grants:
        # Autonomous mode: per-task grants are issued only from the owner manifest on main.
        inner = IssuedGrantEvaluator(condition_provider=condition_provider)
        evaluator = AnchoredPolicyEvaluator(inner, authority)
        issuer = TaskGrantIssuer(authority, inner, principal=principal, ttl_s=grant_ttl_s, clock=clock)
        trust = "anchored+issued"
    else:
        evaluator = PolicyEvaluator(list(grants), condition_provider or (lambda _condition, _request: False))
        trust = "fixture"
        if authority is not None:
            evaluator = AnchoredPolicyEvaluator(evaluator, authority)   # one evaluator for store and gateway
            trust = "anchored"
    if memory is True:
        from hg.memory.store import MemoryStore
        memory = MemoryStore(workdir / "memory.jsonl", clock=clock)
    store = open_task_store(workdir / "tasks.jsonl", evaluator, clock)
    actions = EventLog(workdir / "actions.jsonl", clock=clock)
    if mode == "AUDIT_ONLY":
        # Do not instantiate write, commit, process-execution, or other effect adapters.
        adapters = [LocalFileReadAdapter(root), CodeSearchAdapter(root),
                    SymbolIndexAdapter(root), CodeDiffAdapter(root),
                    *extra_adapters]
    else:
        adapters = [LocalFileWriteAdapter(root), LocalFileReadAdapter(root), CodeSearchAdapter(root),
                    SymbolIndexAdapter(root), CodeDiffAdapter(root), TestRunAdapter(root), UrlReadAdapter(),
                    *extra_adapters]
    gateway = ActionGateway(store, evaluator, actions, adapters, principal=principal, mode=mode)
    gate = AcceptanceGate(clock=clock)
    orchestrator = BrainOrchestrator(store, gateway, gate, principal=principal, verifiers=verifiers,
                                     issuer=issuer, memory=memory)
    return SimpleNamespace(workdir=workdir, root=root, clock=clock, evaluator=evaluator, trust=trust, memory=memory,
                           store=store,
                           actions=actions, gateway=gateway, gate=gate, orch=orchestrator)
