"""C-21 Observability: a health report derived from a runtime's ledgers (no secrets, read-only).

Status: FAILING if a ledger cannot be read or is inconsistent; DEGRADED if actions are
pending reconciliation, memory has conflicts, tasks are blocked, or no model provider is
available (when a router is given); OK otherwise. Each check says why.
"""
from collections import Counter
from pathlib import Path

from maep.ledger import read_events
from maep.task_store import TaskStore
from hg.tools.gateway import pending_from_events
from hg.verification.evidence import EventLog


def health(workdir, *, router=None, trust_loader=None):
    workdir = Path(workdir)
    checks, report = [], {"workdir": str(workdir)}

    def check(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    try:
        store = TaskStore.restore(workdir / "tasks.jsonl")
        task_ids = sorted({e["task_id"] for e in read_events(workdir / "tasks.jsonl") if e["type"] == "TASK_CREATED"})
        states = Counter(store.snapshot(t)["task"]["state"] for t in task_ids)
        report["tasks"] = dict(sorted(states.items()))
        check("task ledger", "OK", f"{len(task_ids)} task(s) replayed consistently")
        if states.get("BLOCKED"):
            check("blocked tasks", "DEGRADED", f"{states['BLOCKED']} task(s) BLOCKED")
    except Exception as exc:
        check("task ledger", "FAILING", f"{type(exc).__name__}: {exc}")
    try:
        actions = EventLog(workdir / "actions.jsonl").events()
        pending = pending_from_events(actions)
        report["actions"] = dict(Counter(e["payload"].get("status") for e in actions if e["kind"] == "ACTION_COMPLETED"))
        report["refusals"] = dict(Counter(e["payload"].get("status") for e in actions if e["kind"] == "ACTION_REFUSED"))
        report["pending_actions"] = sorted(pending)
        check("action ledger", "OK", f"{len(actions)} event(s)")
        if pending:
            check("pending actions", "DEGRADED", f"{len(pending)} action(s) need reconciliation before more effects")
    except Exception as exc:
        check("action ledger", "FAILING", f"{type(exc).__name__}: {exc}")
    models = workdir / "models.jsonl"
    if models.exists():
        try:
            calls = [e["payload"] for e in EventLog(models).events("MODEL_CALL")]
            report["model_calls"] = {"total": len(calls), "errors": dict(Counter(c["error"] for c in calls if c["error"]))}
        except Exception as exc:
            check("model ledger", "FAILING", f"{type(exc).__name__}: {exc}")
    memory = workdir / "memory.jsonl"
    if memory.exists():
        try:
            from hg.memory.store import MemoryStore
            stats = MemoryStore(memory).stats()
            report["memory"] = stats
            check("memory", "DEGRADED" if stats["conflicts"] else "OK",
                  f"{stats['records']} record(s), {stats['conflicts']} conflict(s)")
        except Exception as exc:
            check("memory", "FAILING", f"{type(exc).__name__}: {exc}")
    if router is not None:
        available = router.available("planning")
        check("model providers", "OK" if available else "DEGRADED",
              f"available: {', '.join(available)}" if available else "no provider available"
              + (" in offline mode" if router.offline else ""))
    if trust_loader is not None:
        try:
            _doc, provenance = trust_loader()
            check("trust root", "OK", f"loaded at {provenance.get('commit', '')[:12]}")
        except Exception as exc:
            check("trust root", "DEGRADED", str(exc))
    worst = "FAILING" if any(c["status"] == "FAILING" for c in checks) else (
        "DEGRADED" if any(c["status"] == "DEGRADED" for c in checks) else "OK")
    report.update(status=worst, checks=checks)
    return report
