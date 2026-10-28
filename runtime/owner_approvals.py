"""D2-a and D4-a verifiers for runtime.service (implemented; registration is separate).

D2-a  LocalPolicyApprovalVerifier -- `approved-policy-source-verifier`
      The owner issues one approval record (JSON, mode 600, owned by the runtime user,
      no symlink) for one exact policy document. It binds the repository, the policy
      digest and version, and the trust-root generation and digest; its approval_ref
      must be listed in the policy's own approval_evidence_refs. The record is re-read
      on every policy load, so moving it away blocks all authority immediately.
      Owner tooling: `python -m runtime.owner_approvals approve-policy ...`.

D4-a  AuthorizedWriteRecordVerifier -- `approved-memory-record-verifier`
      A MAEP-022 Memory record (applicability or gate) is approved only if the Memory
      write that created it was authorized by this authority: the authorization_id
      on its `evidence.recorded` event must be the digest of exactly one ALLOW
      `authorization.decision` in the authority's own evidence ledger, for WRITE on
      that evidence id bound to this Memory store, for the same task, candidate and
      policy version, under the current root generation, and the write must fall in
      the grant's validity window. Records provisioned out of band are not approved.

Both verifiers only ever return True or False / raise; neither creates records,
requests approvals, uses signatures or invokes review workflows (MAEP-029/030).
Limitation (same as D3): any process running as the same Android/Unix user can write
these local files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_runtime_providers import _digest, _read_private_json, _write_new_json
from maep.native_authority import AuthorityError, TrustRootRecord
from maep.policy_templates import POLICY_SCHEMA_V2, PolicyTemplateError, validate_policy_source_v2

REPOSITORY = "OAI-GIANG/HG"
APPROVAL_SCHEMA = "hg-runtime-policy-approval-v1"
APPROVAL_KEYS = frozenset({"schema", "repository", "policy_digest", "policy_version", "root_generation",
                           "root_digest", "approval_ref", "approved_at"})
MAX_APPROVAL_BYTES = 16384
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def _absolute(path: Any, label: str) -> Path:
    if not isinstance(path, (str, Path)) or not str(path) or not Path(path).is_absolute():
        raise AuthorityError(f"{label} must be an absolute path")
    return Path(path)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthorityError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise AuthorityError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


# -- D2-a -------------------------------------------------------------------------------
class LocalPolicyApprovalVerifier:
    """Owner approval record for one exact runtime.service policy (fails closed)."""

    def __init__(self, approval_path: str | Path):
        self.approval_path = _absolute(approval_path, "policy approval path")
        self._load()          # a missing or malformed approval blocks startup

    def __repr__(self):
        return f"LocalPolicyApprovalVerifier(approval_path={str(self.approval_path)!r})"

    def _load(self) -> dict[str, Any]:
        try:
            info = self.approval_path.lstat()
        except OSError as exc:
            raise AuthorityError("policy approval record unavailable") from exc
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AuthorityError("policy approval record must be owned by the runtime user")
        if info.st_size > MAX_APPROVAL_BYTES:
            raise AuthorityError("policy approval record too large")
        record = _read_private_json(self.approval_path)   # regular, non-symlink, 0600-like, strict JSON
        if set(record) != APPROVAL_KEYS or record.get("schema") != APPROVAL_SCHEMA:
            raise AuthorityError("policy approval record does not match its schema")
        if (record["repository"] != REPOSITORY
                or not isinstance(record["policy_digest"], str) or not _DIGEST.fullmatch(record["policy_digest"])
                or not isinstance(record["root_digest"], str) or not _DIGEST.fullmatch(record["root_digest"])
                or not isinstance(record["policy_version"], str) or not record["policy_version"].strip()
                or not isinstance(record["root_generation"], int) or isinstance(record["root_generation"], bool)
                or not isinstance(record["approval_ref"], str) or not _REF.fullmatch(record["approval_ref"])):
            raise AuthorityError("policy approval record fields are invalid")
        _parse_time(record["approved_at"])
        return record

    def verify_policy_source(self, record: dict[str, Any], *, root: TrustRootRecord,
                             policy: dict[str, Any]) -> bool:
        approval = self._load()
        if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
            return False
        if not isinstance(record, dict) or not isinstance(policy, dict):
            return False
        refs = policy.get("approval_evidence_refs")
        return (record.get("policy_digest") == approval["policy_digest"] == _digest(policy)
                and policy.get("version") == approval["policy_version"]
                and policy.get("root_generation") == approval["root_generation"] == root.generation
                and root.record_digest == approval["root_digest"]
                and isinstance(refs, list) and approval["approval_ref"] in refs)


def approve_policy(*, policy_path: str | Path, authority_dir: str | Path, approval_path: str | Path,
                   approval_ref: str) -> dict[str, Any]:
    """Owner action: write the approval record for one exact, already final policy file."""
    raw = _read_private_json(_absolute(policy_path, "policy path"))
    policy = raw.get("policy")
    if not isinstance(policy, dict) or raw.get("policy_digest") != _digest(policy):
        raise AuthorityError("policy document digest does not match its policy")
    if policy.get("status") != "ACTIVE":
        raise AuthorityError("only a policy with status ACTIVE can be approved")
    if not isinstance(approval_ref, str) or not _REF.fullmatch(approval_ref):
        raise AuthorityError("approval reference is invalid")
    if approval_ref not in (policy.get("approval_evidence_refs") or []):
        raise AuthorityError("the policy must list the approval reference in approval_evidence_refs")
    root = LocalRootStore(_absolute(authority_dir, "authority dir")).load_active()
    if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
        raise AuthorityError("active trust root unavailable")
    if policy.get("schema_version") == POLICY_SCHEMA_V2:
        try:
            validate_policy_source_v2(policy, expected_root_generation=root.generation)
        except PolicyTemplateError as exc:
            raise AuthorityError("policy v2 schema validation failed") from exc
    elif policy.get("schema_version") not in (None, "hg.policy.v1"):
        raise AuthorityError("unsupported local policy schema version")
    if policy.get("root_generation") != root.generation:
        raise AuthorityError("policy does not bind the active root generation")
    record = {
        "schema": APPROVAL_SCHEMA, "repository": REPOSITORY, "policy_digest": raw["policy_digest"],
        "policy_version": policy.get("version"), "root_generation": root.generation,
        "root_digest": root.record_digest, "approval_ref": approval_ref,
        "approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_new_json(_absolute(approval_path, "approval path"), record)
    return {"result": "APPROVED", "policy_digest": record["policy_digest"],
            "approval_ref": approval_ref, "approval_path": str(approval_path)}


# -- D4-a -------------------------------------------------------------------------------
class AuthorizedWriteRecordVerifier:
    """Approve a Memory record only if this authority allowed the write that created it."""

    def __init__(self, *, evidence_sink: LocalEvidenceSink, memory_store_path: str | Path):
        if not callable(getattr(evidence_sink, "find_decision", None)):
            raise AuthorityError("authorized-write verifier requires an authority evidence ledger")
        self.evidence_sink = evidence_sink
        self.memory_store_path = str(Path(_absolute(memory_store_path, "memory store path")).absolute())

    def __repr__(self):
        return f"AuthorizedWriteRecordVerifier(memory_store_path={self.memory_store_path!r})"

    def verify_approved_memory_record(self, record: dict[str, Any], *, record_type: str,
                                      root: TrustRootRecord, policy: dict[str, Any]) -> bool:
        binding = record.get("_memory_binding") if isinstance(record, dict) else None
        if not isinstance(binding, dict) or not isinstance(root, TrustRootRecord):
            return False
        authorization_id = binding.get("authorization_id")
        evidence_id, task_id = binding.get("evidence_id"), binding.get("task_id")
        if (not isinstance(authorization_id, str) or not _DIGEST.fullmatch(authorization_id)
                or not isinstance(evidence_id, str) or not evidence_id
                or not isinstance(task_id, str) or not task_id):
            return False
        decision = self.evidence_sink.find_decision(authorization_id)   # integrity errors raise
        if decision is None:
            return False
        expected_resource = f"memory:evidence/{evidence_id} [store:{self.memory_store_path}]"
        if (decision.get("decision") != "ALLOW" or decision.get("action") != "WRITE"
                or decision.get("resource") != expected_resource
                or decision.get("task_ref") != task_id
                or decision.get("candidate_ref") != binding.get("candidate_ref")
                or decision.get("policy_version") != binding.get("policy_version")
                or decision.get("root_generation") != root.generation):
            return False
        try:
            issued, expires = _parse_time(decision.get("issued_at")), _parse_time(decision.get("expires_at"))
            written = _parse_time(binding.get("created_at"))
        except (AuthorityError, ValueError):
            return False
        return issued <= written <= expires


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime.owner_approvals",
                                     description="Owner tooling for the D2-a policy approval record.")
    sub = parser.add_subparsers(dest="command", required=True)
    approve = sub.add_parser("approve-policy")
    for name in ("--policy", "--authority-dir", "--approval-file", "--approval-ref"):
        approve.add_argument(name, required=True)
    args = parser.parse_args(argv)
    try:
        result = approve_policy(policy_path=args.policy, authority_dir=args.authority_dir,
                                approval_path=args.approval_file, approval_ref=args.approval_ref)
    except AuthorityError as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 78
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
