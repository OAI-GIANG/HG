"""Owner tool: verified Memory restore and explicit store rebind (finding N10).

Memory authority binds every resource to the database location
(``memory:<kind>/<id> [store:<absolute path>]``, MAEP-004). A backup restored to
another path therefore carries no permission: policy rules, session resource scopes
and the store's own applicability records all name the old location. That is
intended -- restoring data must never re-grant authority by itself -- and this tool
does not change it. It provides the explicit owner steps that make a restore usable
again without weakening exact matching:

``restore``
    Copy a backup into a NEW file (never overwrite), verify SQLite integrity, schema
    version and the full Memory event chain on both sides, and require the restored
    chain head and record counts to equal the backup's. Writes a restore manifest.
``propose-policy``
    Rewrite the exact rule resources bound to the old store into the restored store
    in a NEW policy document whose status is ``PROPOSED`` and which carries no
    approval. Nothing is authorized under it until the owner approves it through the
    D2 policy source and makes it ACTIVE.
``session-scopes``
    Print the rebound resource scopes for a NEW session the owner issues with
    ``python -m runtime.session_auth issue`` (D3). The old session keeps its old,
    no-longer-matching scopes.

Restoring to the original location after the database was lost needs no rebind: the
policy and session never stopped naming that location.

The tool does not talk to a running service, the policy provider or the session
source, has no network access and prints no token or secret. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any
from urllib.parse import quote

from maep.local_runtime_providers import _digest, _read_private_json, _write_new_json
from maep.native_authority import AuthorityError
from memory import AuthorityEvidenceReader

MANIFEST_SCHEMA = "hg-memory-restore-manifest-v1"
PROPOSAL_SCHEMA = "hg-memory-rebind-proposal-v1"
GENESIS = "HG-MEMORY-EVENT-GENESIS-V1"
_SNAPSHOT_KEYS = ("event_count", "evidence_count", "knowledge_record_count", "checkpoint_count",
                  "head_sequence", "chain_head")


class RebindError(AuthorityError):
    """Restore or rebind refused; nothing was overwritten."""


def _abs(path: Any, label: str) -> Path:
    if not isinstance(path, (str, Path)) or not str(path):
        raise RebindError(f"{label} is required")
    return Path(path).expanduser().absolute()


def _suffix(store: Path) -> str:
    return f" [store:{store}]"


def snapshot(db_path: str | Path) -> dict[str, Any]:
    """Integrity-checked summary of a Memory database (read-only)."""
    path = _abs(db_path, "database path")
    try:
        report = AuthorityEvidenceReader(path).check_integrity(task_id="memory-restore-verify")
    except Exception as exc:
        raise RebindError(f"Memory database unreadable or invalid: {path}") from exc
    if not isinstance(report, dict) or report.get("status") != "PASS":
        details = report.get("details") if isinstance(report, dict) else None
        raise RebindError(f"Memory integrity check failed for {path}: {details}")
    uri = "file:" + quote(str(path), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(
            "SELECT sequence, event_digest FROM maep_events ORDER BY sequence DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    result = {key: report[key] for key in _SNAPSHOT_KEYS[:4]}
    result.update(head_sequence=row[0] if row else 0, chain_head=row[1] if row else GENESIS)
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def restore(backup_path: str | Path, target_path: str | Path) -> dict[str, Any]:
    """Restore a verified backup to a new file. Never overwrites; never grants authority."""
    backup, target = _abs(backup_path, "backup"), _abs(target_path, "target")
    manifest_path = Path(str(target) + ".restore-manifest.json")
    if target == backup:
        raise RebindError("restore target must differ from the backup")
    # A leftover hot journal/WAL beside the target would be replayed by SQLite into the
    # restored database on first open, so its presence blocks the restore.
    sidecars = [Path(str(target) + suffix) for suffix in ("-journal", "-wal", "-shm")]
    for path in (target, manifest_path, *sidecars):
        if path.exists() or path.is_symlink():
            raise RebindError(f"refusing to overwrite or reuse existing path: {path}")
    source = snapshot(backup)                     # corrupted or tampered backups stop here
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, partial_name = tempfile.mkstemp(prefix=f".{target.name}.restore-", suffix=".partial",
                                        dir=str(target.parent))
    os.close(fd)
    partial = Path(partial_name)
    os.chmod(partial, 0o600)
    src = sqlite3.connect("file:" + quote(str(backup), safe="/:") + "?mode=ro", uri=True,
                          isolation_level=None)
    dst = sqlite3.connect(str(partial), isolation_level=None)
    try:
        src.backup(dst)
        if [row[0] for row in dst.execute("PRAGMA integrity_check").fetchall()] != ["ok"]:
            raise RebindError(f"restored copy failed SQLite integrity; preserved at {partial}")
    except sqlite3.Error as exc:
        raise RebindError(f"restore copy failed; partial preserved at {partial}") from exc
    finally:
        dst.close()
        src.close()
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
    restored = snapshot(partial)
    if restored != source:
        raise RebindError(f"restored copy does not match the backup; preserved at {partial}")
    # Publish without replacing anything: reserve the final name exclusively first.
    try:
        reserve = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RebindError(f"restore target appeared during restore; copy preserved at {partial}") from exc
    os.close(reserve)
    os.replace(partial, target)
    _fsync_dir(target.parent)
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PASS",
        "backup": str(backup), "backup_sha256": _file_sha256(backup),
        "target": str(target), "target_sha256": _file_sha256(target),
        "source_snapshot": source, "restored_snapshot": snapshot(target),
        "authority": "NONE: resources stay bound to the restored path; rebind needs owner approval",
    }
    if manifest["restored_snapshot"] != source:
        raise RebindError("restored database changed during publication")
    _write_new_json(manifest_path, manifest)
    return dict(manifest, manifest_path=str(manifest_path))


def _load_manifest(manifest_path: str | Path, new_store: Path) -> dict[str, Any]:
    manifest = _read_private_json(_abs(manifest_path, "restore manifest"))
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PASS":
        raise RebindError("restore manifest is not a passing restore record")
    if manifest.get("target") != str(new_store):
        raise RebindError("restore manifest does not describe the new store")
    if snapshot(new_store) != manifest.get("restored_snapshot"):
        raise RebindError("restored store changed since the restore was verified")
    return manifest


def _rebind_resource(value: Any, old: Path, new: Path) -> tuple[Any, bool]:
    if not isinstance(value, str) or " [store:" not in value:
        return value, False
    if value.endswith(_suffix(old)) and value.count(" [store:") == 1:
        return value[: -len(_suffix(old))] + _suffix(new), True
    raise RebindError(f"resource bound to another store; refusing ambiguous rebind: {value}")


def propose_policy(*, policy_path: str | Path, old_store: str | Path, new_store: str | Path,
                   manifest_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    """Write a PROPOSED, unapproved policy with resources rebound to the restored store."""
    old, new = _abs(old_store, "old store"), _abs(new_store, "new store")
    source_path, out = _abs(policy_path, "policy"), _abs(out_path, "output")
    if old == new:
        raise RebindError("old and new store must differ")
    if out == source_path:
        raise RebindError("output must be a new file")
    manifest = _load_manifest(manifest_path, new)
    raw = _read_private_json(source_path)
    policy = raw.get("policy")
    if not isinstance(policy, dict) or raw.get("policy_digest") != _digest(policy):
        raise RebindError("source policy document digest does not match its policy")
    rules = policy.get("rules")
    if not isinstance(rules, list):
        raise RebindError("source policy has no rules")
    rebound_rules, changed = [], 0
    for rule in rules:
        if not isinstance(rule, dict):
            raise RebindError("source policy rule is malformed")
        resource, moved = _rebind_resource(rule.get("resource"), old, new)
        changed += moved
        rebound_rules.append(dict(rule, resource=resource))
    if not changed:
        raise RebindError("no policy rule is bound to the old store; nothing to rebind")
    # Not active and carrying no approval: the source policy's approval refs approved the
    # old binding, not this one. LocalPolicyProvider refuses both conditions.
    proposed = dict(policy, rules=rebound_rules, status="PROPOSED", approval_evidence_refs=[])
    document = {
        "policy": proposed, "policy_digest": _digest(proposed),
        "rebind_proposal": {
            "schema": PROPOSAL_SCHEMA, "source_policy_digest": raw["policy_digest"],
            "old_store": str(old), "new_store": str(new), "rules_rebound": changed,
            "restore_manifest_target_sha256": manifest["target_sha256"],
            "activation": "owner must approve through the D2 policy source and set status ACTIVE",
        },
    }
    _write_new_json(out, document)
    return {"status": "PROPOSED", "out": str(out), "rules_rebound": changed,
            "policy_digest": document["policy_digest"]}


def session_scopes(*, session_path: str | Path, old_store: str | Path, new_store: str | Path) -> dict[str, Any]:
    """Rebound grant lists for a NEW owner-issued session (the token digest is not output)."""
    old, new = _abs(old_store, "old store"), _abs(new_store, "new store")
    if old == new:
        raise RebindError("old and new store must differ")
    record = _read_private_json(_abs(session_path, "session"))
    scopes = record.get("resource_scopes")
    if not isinstance(scopes, list) or not scopes:
        raise RebindError("session record has no resource scopes")
    rebound, changed = [], 0
    for scope in scopes:
        value, moved = _rebind_resource(scope, old, new)
        rebound.append(value)
        changed += moved
    if not changed:
        raise RebindError("no session resource scope is bound to the old store")
    return {"principal_id": record.get("principal_id"), "capabilities": record.get("capabilities"),
            "resource_scopes": rebound, "allowed_scopes": record.get("allowed_scopes"),
            "resource_scopes_rebound": changed,
            "issue": "owner issues a new session: python -m runtime.session_auth issue ..."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime.memory_rebind", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--backup", required=True)
    r.add_argument("--target", required=True)
    p = sub.add_parser("propose-policy")
    for name in ("--policy", "--old-store", "--new-store", "--manifest", "--out"):
        p.add_argument(name, required=True)
    s = sub.add_parser("session-scopes")
    for name in ("--session", "--old-store", "--new-store"):
        s.add_argument(name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "restore":
            result = restore(args.backup, args.target)
        elif args.command == "propose-policy":
            result = propose_policy(policy_path=args.policy, old_store=args.old_store,
                                    new_store=args.new_store, manifest_path=args.manifest, out_path=args.out)
        else:
            result = session_scopes(session_path=args.session, old_store=args.old_store,
                                    new_store=args.new_store)
    except AuthorityError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
