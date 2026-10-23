"""Runtime assembly (MIID layer 11): the one place HG's components are wired together.

Two ledgers live in the work directory: `tasks.jsonl` (task-state owner,
maep.task_store.TaskStore) and `actions.jsonl` (ActionGateway). If they already hold
events the runtime resumes from them (RT-05) instead of starting over.

Grants are passed in by the caller. Until RT-06 anchors them to the owner trust root,
every caller of build_runtime is trusted to supply them; tests and the self-check use
fixtures, which is stated wherever their results are reported.
"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from maep.ledger import read_events
from maep.policy import PolicyEvaluator
from maep.task_store import TaskStore
from hg.brain.orchestrator import BrainOrchestrator
from hg.tools.gateway import ActionGateway, LocalFileReadAdapter, LocalFileWriteAdapter
from hg.verification.evidence import AcceptanceGate, EventLog

DEFAULT_PRINCIPAL = "STT"


def utcnow():
    return datetime.now(timezone.utc)


def open_task_store(path, evaluator, clock):
    path = Path(path)
    if path.exists() and read_events(path):
        return TaskStore.restore(path, policy_evaluator=evaluator, clock=clock)
    return TaskStore(path, policy_evaluator=evaluator, clock=clock)


def build_runtime(workdir, grants, *, principal=DEFAULT_PRINCIPAL, mode="AUTHORIZED_EXECUTION",
                  verifiers=None, clock=None, extra_adapters=(), condition_provider=None):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    root = workdir / "root"
    root.mkdir(exist_ok=True)
    clock = clock or utcnow
    evaluator = PolicyEvaluator(list(grants), condition_provider or (lambda _condition, _request: False))
    store = open_task_store(workdir / "tasks.jsonl", evaluator, clock)
    actions = EventLog(workdir / "actions.jsonl", clock=clock)
    adapters = [LocalFileWriteAdapter(root), LocalFileReadAdapter(root), *extra_adapters]
    gateway = ActionGateway(store, evaluator, actions, adapters, principal=principal, mode=mode)
    gate = AcceptanceGate(clock=clock)
    orchestrator = BrainOrchestrator(store, gateway, gate, principal=principal, verifiers=verifiers)
    return SimpleNamespace(workdir=workdir, root=root, clock=clock, evaluator=evaluator, store=store,
                           actions=actions, gateway=gateway, gate=gate, orch=orchestrator)
