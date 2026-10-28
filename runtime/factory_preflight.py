"""Read-only preflight for the runtime.service production factory (ADR-012).

``create_service()`` stops at the first missing production input. This tool evaluates every
input the factory and its readiness check depend on and reports all of them at once, so the
owner sees the complete provisioning list in one run.

It only reads. It never creates, repairs, approves, issues or activates a trust root, policy,
approval, session, Memory database, ledger or directory, and it never reads or prints the
bearer token (the factory configuration does not name it). The only side effect is whatever
``git status`` itself refreshes in the checkout index while the candidate is inspected.

    python -m runtime.factory_preflight --config /abs/path/runtime-factory.json

``--config`` defaults to ``HG_RUNTIME_CONFIG``. Exit 0 when no check is BLOCKED, 78 otherwise.
A PASS here is not a production verification: composition re-checks everything at startup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_runtime_providers import GitCandidateProvider, LocalPolicyProvider
from maep.native_authority import TrustRootRecord
from runtime.production_config import CONFIG_ENV, load_config, missing_bindings

REPORT_SCHEMA = "hg-runtime-factory-preflight-v1"
EXIT_BLOCKED = 78


def _check(checks: list[dict[str, Any]], name: str, probe: Callable[[], Any]) -> bool:
    try:
        detail = probe()
    except Exception as exc:  # every anomaly, of any type, is reported as BLOCKED
        checks.append({"check": name, "status": "BLOCKED", "reason": str(exc) or type(exc).__name__})
        return False
    entry: dict[str, Any] = {"check": name, "status": "PASS"}
    if detail is not None:
        entry["detail"] = detail
    checks.append(entry)
    return True


def _regular_file(path: str, label: str) -> None:
    info = Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file")


def preflight(config_path: str | None) -> dict[str, Any]:
    """Evaluate every production input; return a JSON-serialisable report."""
    checks: list[dict[str, Any]] = []
    state: dict[str, Any] = {}

    def config():
        state["config"] = load_config(config_path)

    if not _check(checks, "config", config):
        return {"schema": REPORT_SCHEMA, "ready": False, "checks": checks}
    cfg = state["config"]

    def bindings():
        missing = missing_bindings()
        if missing:
            raise ValueError("unregistered production bindings: " + "; ".join(missing))

    def root():
        record = LocalRootStore(cfg["authority_dir"]).load_active()
        if not isinstance(record, TrustRootRecord) or not record.verify_integrity():
            raise ValueError("no verified active trust root is provisioned (owner bootstrap required)")
        state["root"] = record
        return {"root_id": record.root_id, "generation": record.generation,
                "record_digest": record.record_digest}

    _check(checks, "bindings", bindings)
    _check(checks, "trust-root", root)
    if "root" in state:
        # Informational: no runtime code dereferences this field (owner decision A-1).
        ref = state["root"].policy_change_rule_ref
        target = Path(os.path.expanduser(ref[len("file://"):])) if ref.startswith("file://") else None
        resolved = target is not None and not target.is_symlink() and target.is_file()
        checks.append({"check": "policy-change-rule-ref", "status": "NOTICE",
                       "detail": {"ref": ref, "file_exists_after_tilde_expansion": resolved,
                                  "note": "not dereferenced by the factory; resolution is an owner decision"}})

    def evidence():
        if LocalEvidenceSink(cfg["evidence_dir"]).verify_integrity() is not True:
            raise ValueError("authority evidence ledger integrity check failed")

    def approval():
        from runtime.owner_approvals import LocalPolicyApprovalVerifier
        state["approval"] = LocalPolicyApprovalVerifier(cfg["policy_approval_path"])

    def policy():
        if "root" not in state:
            raise ValueError("the policy cannot be verified without a verified trust root")
        if "approval" not in state:
            _regular_file(cfg["policy_path"], "policy file")
            raise ValueError("policy file is present but unverifiable until its owner approval record exists")
        active = LocalPolicyProvider(cfg["policy_path"], state["approval"]).load_active(state["root"])
        return {"version": active.get("version"), "policy_digest": active.get("policy_digest")}

    def session():
        from runtime.session_auth import TokenSessionSource
        source = TokenSessionSource(session_path=cfg["session_record"],
                                    revocation_path=cfg["session_revocations"])
        context = source.authenticated_context()   # raises when expired, not yet valid or revoked
        return {"session_id": context.session_id, "principal_id": context.principal_id}

    def memory():
        _regular_file(cfg["memory_db"], "Memory database (owner initialization required)")

    def write_roots():
        absent = sorted(name for name, root in cfg["file_write_roots"].items() if not Path(root).is_dir())
        if absent:
            raise ValueError("file_write_roots are not provisioned directories: " + ", ".join(absent))

    def state_dirs():
        if not Path(cfg["idempotency_db"]).parent.is_dir():
            raise ValueError("idempotency_db parent directory does not exist")

    def checkout():
        path = str(Path(cfg["checkout"]).absolute())
        candidate = GitCandidateProvider(path).inspect(path)
        if not isinstance(candidate, dict) or candidate.get("verified") is not True:
            raise ValueError("checkout is not a verified OAI-GIANG/HG candidate")
        if candidate.get("working_tree_dirty") is not False:
            raise ValueError("checkout working tree is dirty; readiness would not report a verified release")
        return {"candidate_ref": candidate.get("candidate_ref")}

    for name, probe in (("evidence-ledger", evidence), ("policy-approval", approval),
                        ("active-policy", policy), ("session", session), ("memory-db", memory),
                        ("file-write-roots", write_roots), ("state-dirs", state_dirs),
                        ("checkout-readiness", checkout)):
        _check(checks, name, probe)
    ready = not any(item["status"] == "BLOCKED" for item in checks)
    return {"schema": REPORT_SCHEMA, "ready": ready, "checks": checks}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime.factory_preflight",
                                     description="Read-only report of every runtime.service production input.")
    parser.add_argument("--config", default=os.environ.get(CONFIG_ENV),
                        help=f"absolute path to the factory configuration (default: ${CONFIG_ENV})")
    args = parser.parse_args(argv)
    report = preflight(args.config)
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if report["ready"] else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
