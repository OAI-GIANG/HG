"""Load a copy of the live state directory with a release's own code, read-only (switch gate).

usage: python3 -I -B state_precheck.py <release_root> <state_copy_dir>

Runs the same loaders the service uses at startup and on first request: TaskStore.restore,
the action ledger, MemoryStore replay and the idempotency SQLite store (opened through the
release's fail-closed opener, then only read). Exit 0 and {"result": "PASS"} only if all load.
Always point it at a COPY: opening SQLite can checkpoint a WAL into the database.
"""
import json
import sys
from pathlib import Path


def main():
    release, state = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(release))
    report = {"release": str(release), "state_copy": str(state), "checks": {}}
    try:
        from maep.task_store import TaskStore
        from hg.verification.evidence import EventLog
        from hg.memory.store import MemoryStore
        from hg.http_api import IdempotencyStore
        from hg.tools.gateway import pending_from_events
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "reason": f"import: {type(exc).__name__}: {exc}"}))
        return 1

    def check(name, fn):
        try:
            report["checks"][name] = {"ok": True, "detail": fn()}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    if (state / "tasks.jsonl").exists():
        def tasks():
            from maep.ledger import read_events
            TaskStore.restore(state / "tasks.jsonl")
            events = read_events(state / "tasks.jsonl")
            return {"events": len(events), "tasks": len({e["task_id"] for e in events if e.get("type") == "TASK_CREATED"})}
        check("tasks", tasks)
    if (state / "actions.jsonl").exists():
        check("actions", lambda: {"events": len(EventLog(state / "actions.jsonl").events()),
                                  "pending": len(pending_from_events(EventLog(state / "actions.jsonl").events()))})
    if (state / "memory.jsonl").exists():
        check("memory", lambda: MemoryStore(state / "memory.jsonl").stats())
    db = state / "http-idempotency.sqlite3"
    if db.exists():
        def idem():
            store = IdempotencyStore(db)
            try:
                rows = store._db.execute("SELECT state, COUNT(*) FROM requests GROUP BY state").fetchall()
                return {state_: n for state_, n in rows}
            finally:
                store.close()
        check("idempotency", idem)
    ok = all(c["ok"] for c in report["checks"].values())
    report["result"] = "PASS" if ok else "FAIL"
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
