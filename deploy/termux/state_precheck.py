"""Verify an attested, non-empty copy of HG runtime state using release-local loaders.

Usage:
  python3 -I -B state_precheck.py <release_root> <state_copy_dir>

The copy must contain .hg-state-copy.json. The sidecar is an operational-integrity
attestation, not a cryptographic signature or proof of the original source identity.
This command rejects live-state paths and opens SQLite strictly read-only.
"""
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote


ATTESTATION = ".hg-state-copy.json"
REQUIRED = {"tasks.jsonl", "actions.jsonl", "memory.jsonl", "http-idempotency.sqlite3"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _service_config_state_dir():
    """state_dir of the service config (HG_SERVICE_CONFIG or the documented default path).

    The live state can live anywhere the config says, so the config is a protected-root
    source too. A config that exists but names no usable state_dir fails closed.
    """
    path = Path(os.environ.get("HG_SERVICE_CONFIG") or Path.home() / ".config" / "hg" / "runtime-service.json")
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
    state = doc.get("state_dir") if isinstance(doc, dict) else None
    if not isinstance(state, str) or not os.path.isabs(state):
        raise ValueError(f"service config {path} names no absolute state_dir")
    return Path(state)


def _protected_live_roots():
    roots = []
    configured = os.environ.get("HG_RUNTIME_STATE_DIR")
    if configured:
        roots.append(Path(configured))
    from_config = _service_config_state_dir()
    if from_config is not None:
        roots.append(from_config)
    roots.append(Path.home() / ".local" / "share" / "hg" / "runtime-service-state")
    return {p.resolve() for p in roots}


def _read_only(factory, *args, **kwargs):
    """Open a ledger view read-only. Releases before writer admission have no read_only
    parameter and no admission, so their plain loader is already read-only in effect."""
    try:
        return factory(*args, read_only=True, **kwargs)
    except TypeError as exc:
        if "read_only" not in str(exc):
            raise
        return factory(*args, **kwargs)


def _reject_live_path(state):
    for protected in _protected_live_roots():
        if state == protected or state in protected.parents or protected in state.parents:
            raise ValueError("state_copy_dir overlaps the protected live runtime-state root")


def _inventory_files(state):
    files = []
    for path in sorted(state.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"copy contains a symlink: {path.relative_to(state)}")
        if path.is_file() and path.name != ATTESTATION:
            rel = path.relative_to(state).as_posix()
            raw = path.read_bytes()
            files.append({"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return files


def _load_attestation(state):
    path = state / ATTESTATION
    if path.is_symlink() or not path.is_file():
        raise ValueError("copy attestation is missing or not a regular file")
    doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
    if not isinstance(doc, dict) or doc.get("schema") != "hg-state-copy-attestation-v1":
        raise ValueError("unsupported copy attestation schema")
    for field in ("copy_id", "source_ref", "created_at", "assurance"):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            raise ValueError(f"copy attestation field {field} is required")
    if doc["assurance"] != "OPERATIONAL_INTEGRITY_UNAUTHENTICATED":
        raise ValueError("copy attestation assurance must be explicitly operational/unauthenticated")
    inventory = doc.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("copy inventory must be a non-empty list")
    seen = set()
    for item in inventory:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid inventory entry")
        rel = item["path"]
        if (not isinstance(rel, str) or not rel or Path(rel).is_absolute()
                or Path(rel).as_posix() != rel or any(part in ("", ".", "..") for part in Path(rel).parts)
                or rel == ATTESTATION):
            raise ValueError("unsafe inventory path")
        if rel in seen:
            raise ValueError("duplicate inventory path")
        seen.add(rel)
        if isinstance(item["bytes"], bool) or not isinstance(item["bytes"], int) or item["bytes"] < 0:
            raise ValueError("inventory bytes must be a non-negative integer")
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("inventory SHA-256 is malformed")
    missing = REQUIRED - seen
    if missing:
        raise ValueError("copy inventory lacks required runtime domains: " + ", ".join(sorted(missing)))
    actual = _inventory_files(state)
    expected = {item["path"]: item for item in inventory}
    observed = {item["path"]: item for item in actual}
    if set(expected) != set(observed):
        raise ValueError("copy inventory does not cover exactly the regular files in the copy")
    for rel, item in expected.items():
        if item != observed[rel]:
            raise ValueError(f"copy inventory mismatch: {rel}")
    return doc, len(inventory)


def _sqlite_readonly(path):
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        result = db.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError("SQLite quick_check failed")
        rows = db.execute("SELECT state, COUNT(*) FROM requests GROUP BY state").fetchall()
        return {"states": {state: count for state, count in rows}, "quick_check": "ok"}
    finally:
        db.close()


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"result": "FAIL", "reason": "usage: state_precheck.py <release_root> <state_copy_dir>"}))
        return 2
    release, raw_state = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        if not release.is_absolute() or not release.is_dir() or release.is_symlink():
            raise ValueError("release_root must be an absolute real directory")
        if not raw_state.is_absolute() or not raw_state.is_dir() or raw_state.is_symlink():
            raise ValueError("state_copy_dir must be an existing absolute real directory")
        state = raw_state.resolve()
        _reject_live_path(state)
        attestation, inventory_count = _load_attestation(state)
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "reason": f"copy admission: {type(exc).__name__}: {exc}"}))
        return 1

    sys.path.insert(0, str(release))
    report = {"release": str(release), "state_copy": str(state),
              "copy_id": attestation["copy_id"], "source_ref": attestation["source_ref"],
              "assurance": attestation["assurance"], "inventory_entries": inventory_count, "checks": {}}
    try:
        from maep.task_store import TaskStore
        from hg.verification.evidence import EventLog
        from hg.memory.store import MemoryStore
        from hg.tools.gateway import pending_from_events
    except Exception as exc:
        print(json.dumps({"result": "FAIL", "reason": f"import: {type(exc).__name__}: {exc}"}))
        return 1

    def check(name, fn):
        try:
            report["checks"][name] = {"ok": True, "detail": fn()}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    # The copy carries the live .writer.lock marker, so writer stores would (rightly) refuse it;
    # every loader here is a read-only view that cannot append.
    def tasks():
        _read_only(TaskStore.restore, state / "tasks.jsonl")
        from maep.ledger import read_events
        events = read_events(state / "tasks.jsonl")
        return {"events": len(events), "tasks": len({e["task_id"] for e in events if e.get("type") == "TASK_CREATED"})}

    def actions():
        events = _read_only(EventLog, state / "actions.jsonl").events()
        return {"events": len(events), "pending": len(pending_from_events(events))}

    check("tasks", tasks)
    check("actions", actions)
    check("memory", lambda: _read_only(MemoryStore, state / "memory.jsonl").stats())
    check("idempotency", lambda: _sqlite_readonly(state / "http-idempotency.sqlite3"))
    ok = bool(report["checks"]) and all(c["ok"] for c in report["checks"].values())
    report["result"] = "PASS" if ok else "FAIL"
    report["limitation"] = "Operational copy integrity only; source authenticity is not cryptographically established."
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
