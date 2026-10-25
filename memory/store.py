"""MAEP-bound durable Memory & Knowledge store for HG.

The store is a scoped persistence adapter, not an orchestrator or policy authority.
It uses Python's standard library only. Every read/write requires a trusted runtime
identity and policy-evaluator dependency; no caller-supplied ALLOW flag is trusted.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from urllib.parse import quote

from maep.core import (
    MAEPError,
    POLICY_VERSION,
    assess_candidate_change,
    authorize_action,
    enforce_execution_mode,
    evaluate_gate,
    transition,
    validate_blocker,
    validate_claim,
    validate_closure,
    validate_evidence,
    validate_task,
)

SCHEMA_VERSION = 1
CONTINUITY_VERSION = "MAEP-AFCP-1.0.0"
KNOWLEDGE_STATUSES = {"UNVERIFIED", "VERIFIED"}
UNRESUMABLE_TASK_TARGETS = {"AUTHORIZED", "RUNNING", "ACCEPTED", "CLOSED_VERIFIED"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _canonical_json(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise MAEPError("record is not valid canonical JSON") from exc


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event_digest(
    sequence, event_id, task_id, event_type, policy_version,
    candidate_ref, occurred_at, prev_digest, payload
):
    return _digest({
        "sequence": sequence,
        "event_id": event_id,
        "task_id": task_id,
        "event_type": event_type,
        "policy_version": policy_version,
        "candidate_ref": candidate_ref,
        "occurred_at": occurred_at,
        "prev_digest": prev_digest,
        "payload": payload,
    })


def _loads_object(raw, label):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MAEPError(f"{label} JSON is invalid; state preserved and use blocked") from exc
    if not isinstance(value, dict):
        raise MAEPError(f"{label} must be a JSON object")
    return value


def _unique_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


def _require_nonempty(value, label):
    if not _nonempty(value):
        raise MAEPError(f"{label} must be a non-empty string")


def _validate_task_index_args(index_scope_task_id, limit, offset):
    if not _nonempty(index_scope_task_id):
        raise MAEPError("index authorization task context is required")
    if (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500
            or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0):
        raise MAEPError("task index pagination is invalid")


def _validate_evidence_lookup_args(task_id, evidence_id):
    if not isinstance(task_id, str) or not task_id.strip():
        raise MAEPError("task_id must be a non-empty string")
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        raise MAEPError("evidence_id must be a non-empty string")


def _validate_event_limit(limit):
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise MAEPError("limit must be an integer from 1 to 1000")


def _reject_secret_fields(value, path="record"):
    """Reject obvious secret-value fields; this is not a content DLP scanner."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise MAEPError(f"{path} contains a non-string field name")
            normalized = key.lower().replace("-", "_")
            is_reference = normalized.endswith(("_ref", "_id", "_name"))
            sensitive_markers = (
                "password", "passwd", "secret", "private_key",
                "privatekey", "access_token", "refresh_token",
                "api_key", "credential_value",
            )
            if not is_reference and any(marker in normalized for marker in sensitive_markers):
                raise MAEPError(f"{path}.{key} looks like a secret value; store a reference, not the secret")
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def _validate_continuity_record(record, *, expected_task_id=None):
    """Validate required AFCP structure without an external JSON Schema dependency."""
    required = {
        "record_version", "task_id", "created_at", "updated_at", "linked_task_id",
        "objective", "scope", "current_state", "state_as_of", "candidate_ref",
        "policy_version", "task_version", "completed_steps", "pending_steps",
        "blockers", "decisions", "evidence_refs", "checkpoint", "next_action",
        "freshness", "integrity_and_recovery",
    }
    if not isinstance(record, dict) or not required.issubset(record):
        raise MAEPError("continuity record is incomplete")
    if record["record_version"] != CONTINUITY_VERSION:
        raise MAEPError("unsupported continuity protocol version")
    for field in ("task_id", "created_at", "updated_at", "objective", "state_as_of", "candidate_ref", "policy_version"):
        _require_nonempty(record.get(field), f"continuity.{field}")
    if expected_task_id is not None and record["task_id"] != expected_task_id:
        raise MAEPError("continuity task ID mismatch")
    if record["linked_task_id"] is not None and not _nonempty(record["linked_task_id"]):
        raise MAEPError("linked_task_id must be null or a non-empty string")
    if not isinstance(record["current_state"], str) or record["current_state"] not in {
        "DRAFT", "READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING",
        "VERIFYING", "ACCEPTED", "CLOSED_VERIFIED", "BLOCKED", "FAILED",
        "CANCELLED", "UNVERIFIED",
    }:
        raise MAEPError("continuity task state is invalid")
    if not isinstance(record["task_version"], int) or record["task_version"] < 1:
        raise MAEPError("continuity task_version must be a positive integer")
    scope = record["scope"]
    if (
        not isinstance(scope, dict) or not isinstance(scope.get("include"), list)
        or not scope["include"] or not all(_nonempty(item) for item in scope["include"])
        or not isinstance(scope.get("exclude"), list)
    ):
        raise MAEPError("continuity scope is incomplete")
    for field in ("completed_steps", "pending_steps", "blockers", "decisions", "evidence_refs"):
        if not isinstance(record[field], list):
            raise MAEPError(f"continuity.{field} must be a list")
    evidence_refs = record["evidence_refs"]
    if not all(_nonempty(ref) for ref in evidence_refs):
        raise MAEPError("continuity evidence references must be non-empty strings")
    for step in record["completed_steps"]:
        if not isinstance(step, dict) or not all(
            _nonempty(step.get(key)) for key in ("step_id", "outcome", "timestamp")
        ):
            raise MAEPError("continuity completed step is malformed")
        if not isinstance(step.get("evidence_refs"), list):
            raise MAEPError("continuity completed step evidence_refs must be a list")
        if step.get("verification_status") not in {"VERIFIED", "UNVERIFIED"}:
            raise MAEPError("completed step must explicitly label verification status")
        if not step["evidence_refs"] and step.get("verification_status") != "UNVERIFIED":
            raise MAEPError("completed step without evidence must remain UNVERIFIED")
        if any(not _nonempty(ref) for ref in step["evidence_refs"]):
            raise MAEPError("completed step evidence references must be non-empty")
        if any(ref not in evidence_refs for ref in step["evidence_refs"]):
            raise MAEPError("completed step evidence refs are absent from continuity evidence_refs")
    for step in record["pending_steps"]:
        if (
            not isinstance(step, dict) or not _nonempty(step.get("step_id"))
            or not isinstance(step.get("prerequisites"), list)
            or not isinstance(step.get("acceptance_conditions"), list)
            or not step["acceptance_conditions"]
        ):
            raise MAEPError("continuity pending step is malformed")
    for blocker in record["blockers"]:
        validate_blocker(blocker)
    for decision in record["decisions"]:
        if not isinstance(decision, dict) or not all(
            _nonempty(decision.get(key))
            for key in ("decision_id", "decision", "authority_source", "rationale", "timestamp")
        ):
            raise MAEPError("continuity decision record is incomplete")
        if not isinstance(decision.get("scope"), (dict, list)):
            raise MAEPError("continuity decision scope is missing")
    checkpoint = record["checkpoint"]
    checkpoint_fields = {
        "checkpoint_id", "schema_version", "task_id", "candidate_ref", "policy_version",
        "captured_at", "event_sequence", "content_digest",
    }
    if not isinstance(checkpoint, dict) or not checkpoint_fields.issubset(checkpoint):
        raise MAEPError("continuity checkpoint metadata is incomplete")
    for field in ("checkpoint_id", "task_id", "candidate_ref", "policy_version", "captured_at"):
        _require_nonempty(checkpoint.get(field), f"continuity.checkpoint.{field}")
    if checkpoint["schema_version"] != CONTINUITY_VERSION:
        raise MAEPError("checkpoint protocol version mismatch")
    if checkpoint["task_id"] != record["task_id"]:
        raise MAEPError("checkpoint task identity mismatch")
    if checkpoint["candidate_ref"] != record["candidate_ref"]:
        raise MAEPError("checkpoint candidate mismatch")
    if checkpoint["policy_version"] != record["policy_version"]:
        raise MAEPError("checkpoint policy version mismatch")
    if not isinstance(checkpoint["event_sequence"], int) or checkpoint["event_sequence"] < 0:
        raise MAEPError("checkpoint event sequence is invalid")
    digest = checkpoint["content_digest"]
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MAEPError("checkpoint content digest is invalid")
    next_action = record["next_action"]
    if not isinstance(next_action, dict) or not all(
        _nonempty(next_action.get(field))
        for field in ("description", "expected_result", "stop_condition")
    ):
        raise MAEPError("continuity next_action is incomplete")
    if not isinstance(next_action.get("preconditions"), list):
        raise MAEPError("continuity next_action preconditions must be a list")
    auth = next_action.get("required_authorization")
    if not (_nonempty(auth) or (isinstance(auth, dict) and bool(auth)) or (isinstance(auth, list) and bool(auth))):
        raise MAEPError("continuity next_action required_authorization is missing")
    freshness = record["freshness"]
    if not isinstance(freshness, dict) or not _nonempty(freshness.get("last_live_state_inspection_at")):
        raise MAEPError("continuity freshness metadata is incomplete")
    resources = freshness.get("inspected_resources")
    if not isinstance(resources, list) or not isinstance(freshness.get("stale_unknown_reasons"), list):
        raise MAEPError("continuity freshness collections are malformed")
    resource_ids = set()
    for item in resources:
        if not isinstance(item, dict) or not _nonempty(item.get("resource_id")) or not _nonempty(item.get("version")):
            raise MAEPError("continuity resource observation is malformed")
        if item["resource_id"] in resource_ids:
            raise MAEPError("continuity resource observation is duplicated")
        resource_ids.add(item["resource_id"])
    integrity = record["integrity_and_recovery"]
    if not isinstance(integrity, dict) or not isinstance(
        integrity.get("last_successfully_loaded_event_sequence"), int
    ):
        raise MAEPError("continuity integrity metadata is incomplete")
    if integrity.get("parse_validation_result") != "PASS":
        raise MAEPError("continuity record validation result is not PASS")
    if not isinstance(integrity.get("detected_gaps_or_corruption"), list):
        raise MAEPError("continuity corruption/gap collection is malformed")
    if integrity["last_successfully_loaded_event_sequence"] != checkpoint["event_sequence"]:
        raise MAEPError("continuity checkpoint/event sequence metadata disagrees")
    _reject_secret_fields(record, "continuity")
    return True


class MemoryStore:
    """MAEP-governed local durable store.

    Trusted dependencies are supplied by the HG runtime:
      principal_provider() -> authenticated principal ID
      policy_evaluator(request) -> {
          "grant": MAEP authorization object,
          "trusted_policy_allow": True/False,
          "satisfied_conditions": [...]
      }
      live_state_provider(task_id) -> observed live task/candidate/policy/resources.

    Without the principal and policy evaluator, all reads and writes fail closed.
    Without the live-state provider, checkpoint creation and resume approval block.
    The constructor performs no filesystem/database writes.
    """

    def __init__(
        self,
        db_path,
        *,
        principal_provider=None,
        policy_evaluator=None,
        live_state_provider=None,
        acceptance_provider=None,
        applicability_provider=None,
        candidate_ref_provider=None,
        effect_recheck_provider=None,
        execution_mode="AUTHORIZED_EXECUTION",
        timeout_seconds=5.0,
    ):
        if execution_mode not in {"READ_ONLY", "AUTHORIZED_EXECUTION"}:
            raise MAEPError("unknown execution mode")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise MAEPError("timeout_seconds must be positive")
        self.path = Path(db_path).expanduser().absolute()
        self.principal_provider = principal_provider
        self.policy_evaluator = policy_evaluator
        self.live_state_provider = live_state_provider
        self.acceptance_provider = acceptance_provider
        # This callback must be injected by the actual execution boundary, not by
        # the policy evaluator or request creator. If absent, authorization fails closed.
        self.applicability_provider = applicability_provider
        self.candidate_ref_provider = candidate_ref_provider
        self.effect_recheck_provider = effect_recheck_provider
        self.execution_mode = execution_mode
        self.timeout_seconds = float(timeout_seconds)

    def _authorize(self, action, resource, scope, task_id):
        """Obtain and validate authority from the trusted runtime seam."""
        enforce_execution_mode(self.execution_mode, action)
        if callable(self.candidate_ref_provider) and not callable(self.effect_recheck_provider):
            raise MAEPError("BLOCKED: candidate-bound Memory authorization requires pre-effect recheck")
        if not callable(self.principal_provider) or not callable(self.policy_evaluator):
            raise MAEPError("BLOCKED: authenticated principal/policy evaluator unavailable")
        try:
            principal = self.principal_provider()
        except Exception as exc:
            raise MAEPError("BLOCKED: authenticated principal provider failed") from exc
        _require_nonempty(principal, "authenticated principal")
        # Bind every logical object to the configured durable store location (MAEP-004).
        bound_resource = f"{resource} [store:{self.path}]"
        candidate_ref = None
        if callable(self.candidate_ref_provider):
            try:
                candidate_ref = self.candidate_ref_provider(task_id)
            except Exception as exc:
                raise MAEPError("BLOCKED: candidate identity provider failed") from exc
            _require_nonempty(candidate_ref, "candidate identity")
        request = {
            "principal": principal,
            "action": action,
            "resource": bound_resource,
            "storage_ref": str(self.path),
            "scope": list(scope),
            "task_id": task_id,
            "policy_version": POLICY_VERSION,
            "candidate_ref": candidate_ref,
        }
        try:
            decision = self.policy_evaluator(dict(request))
        except Exception as exc:
            raise MAEPError("BLOCKED: trusted policy evaluation failed") from exc
        if not isinstance(decision, dict):
            raise MAEPError("BLOCKED: policy evaluator returned no decision object")
        grant = decision.get("grant")
        request["satisfied_conditions"] = decision.get("satisfied_conditions", [])
        # This method authorizes Memory data-plane access, not capability evolution.
        # MAEP-022 is evaluated at the capability-change authority boundary when relevant.
        authorize_action(
            grant,
            request,
            trusted_policy_allow=decision.get("trusted_policy_allow"),
        )
        if callable(self.effect_recheck_provider):
            try:
                self.effect_recheck_provider(dict(request))
            except Exception as exc:
                raise MAEPError("BLOCKED: Memory pre-effect authority recheck failed") from exc
        return {
            "authorization_id": grant["authorization_id"],
            "principal": principal,
            "action": action,
            "resource": resource,
            "scope": list(scope),
        }

    def _authorize_external_action(self, action_request, task_id):
        """Validate action-specific authority without granting or executing that action."""
        if not isinstance(action_request, dict):
            raise MAEPError("action-specific authorization request is required")
        required = {
            "principal", "action", "resource", "scope", "task_id", "policy_version",
            "capability_affecting", "capability_gate",
        }
        if not required.issubset(action_request):
            raise MAEPError("action-specific authorization request is incomplete")
        principal = self.principal_provider() if callable(self.principal_provider) else None
        if action_request.get("principal") != principal:
            raise MAEPError("action principal differs from authenticated runtime identity")
        if action_request.get("task_id") != task_id or action_request.get("policy_version") != POLICY_VERSION:
            raise MAEPError("action request task/policy version mismatch")
        if not _nonempty(action_request.get("resource")) or not isinstance(action_request.get("scope"), list) or not action_request["scope"]:
            raise MAEPError("action request requires resource and explicit scope")
        if not isinstance(action_request.get("capability_affecting"), bool):
            raise MAEPError("action request must explicitly declare MAEP-022 applicability")
        if not isinstance(action_request.get("capability_gate"), dict):
            raise MAEPError("action request must include a MAEP-022 gate declaration")
        enforce_execution_mode(self.execution_mode, action_request["action"])
        if not callable(self.policy_evaluator):
            raise MAEPError("trusted policy evaluator unavailable for action-specific authorization")
        request = {
            "principal": principal,
            "action": action_request["action"],
            "resource": action_request["resource"],
            "scope": list(action_request["scope"]),
            "task_id": task_id,
            "policy_version": POLICY_VERSION,
            "capability_affecting": action_request["capability_affecting"],
            "capability_gate": action_request["capability_gate"],
        }
        candidate_ref = action_request.get("candidate_ref")
        if callable(self.candidate_ref_provider):
            try:
                observed_candidate_ref = self.candidate_ref_provider(task_id)
            except Exception as exc:
                raise MAEPError("BLOCKED: candidate identity provider failed") from exc
            _require_nonempty(observed_candidate_ref, "candidate identity")
            if candidate_ref is not None and candidate_ref != observed_candidate_ref:
                raise MAEPError("BLOCKED: action candidate differs from current candidate")
            candidate_ref = observed_candidate_ref
        if action_request["capability_affecting"]:
            _require_nonempty(candidate_ref, "capability-affecting action candidate_ref")
        if candidate_ref is not None:
            request["candidate_ref"] = candidate_ref
        try:
            decision = self.policy_evaluator(dict(request))
        except Exception as exc:
            raise MAEPError("action-specific policy evaluation failed") from exc
        if not isinstance(decision, dict):
            raise MAEPError("action-specific policy evaluator returned no decision")
        request["satisfied_conditions"] = decision.get("satisfied_conditions", [])
        if not callable(self.applicability_provider):
            raise MAEPError("BLOCKED: trusted MAEP-022 applicability provider unavailable")
        try:
            applicability = self.applicability_provider(dict(request))
        except Exception as exc:
            raise MAEPError("BLOCKED: trusted MAEP-022 applicability evaluation failed") from exc
        # The caller's capability_affecting/capability_gate fields are declarations,
        # not authority. Compare them to the candidate-bound trusted classification.
        if (not isinstance(applicability, dict)
                or applicability.get("verified") is not True
                or applicability.get("candidate_ref") != request.get("candidate_ref")
                or applicability.get("action") != request.get("action")
                or applicability.get("resource") != request.get("resource")
                or not isinstance(applicability.get("capability_affecting"), bool)):
            raise MAEPError("BLOCKED: trusted MAEP-022 applicability is unverified or mismatched")
        if applicability["capability_affecting"] != action_request["capability_affecting"]:
            raise MAEPError("BLOCKED: caller MAEP-022 declaration differs from trusted applicability")
        gate_declaration_applies = action_request["capability_gate"].get("applies")
        if gate_declaration_applies is not applicability["capability_affecting"]:
            raise MAEPError("BLOCKED: caller MAEP-022 gate declaration differs from trusted applicability")
        if applicability["capability_affecting"]:
            gate_decision = applicability.get("gate_decision")
            if (not isinstance(gate_decision, dict)
                    or gate_decision.get("status") != "PASS"
                    or gate_decision.get("verified") is not True
                    or gate_decision.get("candidate_ref") != request.get("candidate_ref")
                    or gate_decision.get("policy_version") != request.get("policy_version")
                    or not _nonempty(gate_decision.get("gate_id"))
                    or not isinstance(gate_decision.get("evidence_refs"), list)
                    or not gate_decision.get("evidence_refs")
                    or not all(_nonempty(ref) for ref in gate_decision["evidence_refs"])):
                raise MAEPError("BLOCKED: applicable MAEP-022 gate lacks verified candidate-bound PASS evidence")
        authorize_action(
            decision.get("grant"),
            request,
            trusted_policy_allow=decision.get("trusted_policy_allow"),
        )
        if callable(self.effect_recheck_provider):
            try:
                self.effect_recheck_provider(dict(request))
            except Exception as exc:
                raise MAEPError("BLOCKED: action pre-effect authority recheck failed") from exc
        return decision["grant"]["authorization_id"]

    def _connect(self, *, readonly=False):
        if self.path.exists():
            mode = self.path.stat().st_mode & 0o777
            if mode & 0o077:
                raise MAEPError("Memory database permissions are broader than 0600; access blocked without an authorized remediation")
        if readonly:
            if not self.path.is_file():
                raise MAEPError("Memory store does not exist")
            uri = "file:" + quote(str(self.path), safe="/:") + "?mode=ro"
            raw = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds, isolation_level=None)
        else:
            if not self.path.is_file():
                raise MAEPError("Memory store is not initialized; call initialize under MAEP authority")
            raw = sqlite3.connect(str(self.path), timeout=self.timeout_seconds, isolation_level=None)
        raw.row_factory = sqlite3.Row
        try:
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
            if readonly:
                raw.execute("PRAGMA query_only=ON")
                raw.execute("BEGIN")
            else:
                raw.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error as exc:
            raw.close()
            raise MAEPError("SQLite connection could not apply required safety settings") from exc
        return raw

    def _ensure_ready(self, connection):
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise MAEPError(
                    f"unsupported Memory schema version {version}; expected {SCHEMA_VERSION}; no auto-migration"
                )
            metadata = connection.execute(
                "SELECT value FROM memory_metadata WHERE key='schema_version'"
            ).fetchone()
            if metadata is None or metadata["value"] != str(SCHEMA_VERSION):
                raise MAEPError("Memory schema metadata is missing or inconsistent")
            policy_metadata = connection.execute(
                "SELECT value FROM memory_metadata WHERE key='policy_version'"
            ).fetchone()
            if policy_metadata is None or policy_metadata["value"] != POLICY_VERSION:
                raise MAEPError(
                    "Memory policy-version metadata is stale; explicit MAEP-reviewed migration/reconciliation is required"
                )
            required = {
                "memory_metadata", "tasks", "maep_events", "evidence",
                "knowledge_records", "checkpoints"
            }
            found = {
                row["name"] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not required.issubset(found):
                raise MAEPError("Memory schema is incomplete; fail closed without automatic repair")
            self._validate_event_chain(connection)
        except sqlite3.Error as exc:
            raise MAEPError("Memory database is malformed or unavailable; fail closed") from exc

    def _validate_event_chain(self, connection):
        """Detect missing, reordered, or modified rows in the local append-only event stream."""
        rows = connection.execute(
            """SELECT sequence, event_id, task_id, event_type, policy_version,
                      candidate_ref, occurred_at, prev_digest, event_digest, payload_json
               FROM maep_events ORDER BY sequence"""
        ).fetchall()
        expected_sequence = 1
        previous_digest = "HG-MEMORY-EVENT-GENESIS-V1"
        for row in rows:
            if row["sequence"] != expected_sequence:
                raise MAEPError("Memory event sequence has a gap or reordering; writes/reads blocked")
            if row["prev_digest"] != previous_digest:
                raise MAEPError(f"Memory event chain predecessor mismatch at sequence {expected_sequence}")
            payload = _loads_object(row["payload_json"], "event payload")
            expected_digest = _event_digest(
                row["sequence"], row["event_id"], row["task_id"], row["event_type"],
                row["policy_version"], row["candidate_ref"], row["occurred_at"],
                row["prev_digest"], payload,
            )
            if expected_digest != row["event_digest"]:
                raise MAEPError(f"Memory event digest mismatch at sequence {expected_sequence}")
            previous_digest = row["event_digest"]
            expected_sequence += 1
        return {"event_count": len(rows), "last_digest": previous_digest}

    @contextmanager
    def _transaction(self):
        connection = self._connect(readonly=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_ready(connection)
            yield connection
            connection.commit()
        except MAEPError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise MAEPError("Memory transaction failed and was rolled back") from exc
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, *, task_id):
        """Create a new database only; never repair/reset an existing unknown database."""
        if self.path.exists():
            self._authorize(
                "READ", "memory:database", ["memory:schema:validate"], task_id
            )
            if self.path.stat().st_size == 0:
                raise MAEPError("existing empty database file is ambiguous; preserve and investigate")
            connection = self._connect(readonly=True)
            try:
                self._ensure_ready(connection)
                return {"status": "READY", "created": False, "schema_version": SCHEMA_VERSION}
            finally:
                connection.close()

        initialization_auth = self._authorize(
            "WRITE", "memory:database", ["memory:schema:initialize"], task_id
        )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        initialization_auth = self._authorize(
            "WRITE", "memory:database", ["memory:schema:initialize"], task_id
        )
        try:
            file_descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(file_descriptor)
        except FileExistsError as exc:
            raise MAEPError("Memory database appeared during initialization; preserve and reconcile") from exc
        os.chmod(self.path, 0o600)
        connection = sqlite3.connect(
            str(self.path), timeout=self.timeout_seconds, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            schema_auth = self._authorize(
                "WRITE", "memory:database/schema", ["memory:schema:create"], task_id
            )
            ddl = [
                """CREATE TABLE memory_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )""",
                """CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    candidate_ref TEXT NOT NULL,
                    row_version INTEGER NOT NULL CHECK(row_version >= 1),
                    task_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
                """CREATE TABLE maep_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    candidate_ref TEXT,
                    occurred_at TEXT NOT NULL,
                    prev_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )""",
                """CREATE TABLE evidence (
                    evidence_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    candidate_ref TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""",
                """CREATE TABLE knowledge_records (
                    record_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    candidate_ref TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    verification_status TEXT NOT NULL
                        CHECK(verification_status IN ('UNVERIFIED','VERIFIED')),
                    supersedes_record_id TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, claim_id, version)
                )""",
                """CREATE TABLE checkpoints (
                    checkpoint_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    task_version INTEGER NOT NULL,
                    candidate_ref TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL,
                    content_digest TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""",
                "CREATE INDEX evidence_by_task_candidate ON evidence(task_id, candidate_ref)",
                "CREATE INDEX knowledge_by_task_claim ON knowledge_records(task_id, claim_id, version)",
                "CREATE INDEX knowledge_by_task_candidate ON knowledge_records(task_id, candidate_ref, policy_version)",
                "CREATE INDEX checkpoint_by_task ON checkpoints(task_id, checkpoint_sequence)",
                "CREATE INDEX event_by_task_sequence ON maep_events(task_id, sequence)",
                """CREATE TRIGGER maep_events_no_update BEFORE UPDATE ON maep_events
                    BEGIN SELECT RAISE(ABORT, 'MAEP events are append-only'); END""",
                """CREATE TRIGGER maep_events_no_delete BEFORE DELETE ON maep_events
                    BEGIN SELECT RAISE(ABORT, 'MAEP events are append-only'); END""",
                """CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
                    BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END""",
                """CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence
                    BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END""",
                """CREATE TRIGGER knowledge_no_update BEFORE UPDATE ON knowledge_records
                    BEGIN SELECT RAISE(ABORT, 'knowledge records are versioned, not updated'); END""",
                """CREATE TRIGGER knowledge_no_delete BEFORE DELETE ON knowledge_records
                    BEGIN SELECT RAISE(ABORT, 'knowledge history is append-only'); END""",
                """CREATE TRIGGER checkpoints_no_update BEFORE UPDATE ON checkpoints
                    BEGIN SELECT RAISE(ABORT, 'checkpoints are immutable'); END""",
                """CREATE TRIGGER checkpoints_no_delete BEFORE DELETE ON checkpoints
                    BEGIN SELECT RAISE(ABORT, 'checkpoints are immutable'); END""",
            ]
            for statement in ddl:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO memory_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                "INSERT INTO memory_metadata(key, value) VALUES('policy_version', ?)",
                (POLICY_VERSION,),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._append_event(
                connection,
                task_id=task_id,
                event_type="memory.initialized",
                candidate_ref=None,
                payload={
                    "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                    "file_creation_authorization_id": initialization_auth["authorization_id"],
                    "schema_creation_authorization_id": schema_auth["authorization_id"],
                },
            )
            connection.commit()
            os.chmod(self.path, 0o600)
            return {"status": "READY", "created": True, "schema_version": SCHEMA_VERSION}
        except Exception as exc:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(exc, MAEPError):
                raise
            raise MAEPError("Memory initialization failed; partial artifact preserved, no reset attempted") from exc
        finally:
            connection.close()

    def _append_event(self, connection, *, task_id, event_type, candidate_ref, payload):
        last = connection.execute(
            "SELECT sequence, event_digest FROM maep_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = (last["sequence"] + 1) if last else 1
        prev_digest = last["event_digest"] if last else "HG-MEMORY-EVENT-GENESIS-V1"
        event = {
            "sequence": sequence,
            "event_id": _unique_id("MEM-EVT"),
            "task_id": task_id,
            "event_type": event_type,
            "policy_version": POLICY_VERSION,
            "candidate_ref": candidate_ref,
            "occurred_at": _now(),
            "prev_digest": prev_digest,
            "payload": payload,
        }
        event_digest = _event_digest(
            sequence, event["event_id"], task_id, event_type, POLICY_VERSION,
            candidate_ref, event["occurred_at"], prev_digest, payload,
        )
        connection.execute(
            """INSERT INTO maep_events(
                sequence, event_id, task_id, event_type, policy_version,
                candidate_ref, occurred_at, prev_digest, event_digest, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sequence, event["event_id"], task_id, event_type, POLICY_VERSION,
                candidate_ref, event["occurred_at"], prev_digest, event_digest,
                _canonical_json(payload),
            ),
        )
        event["event_digest"] = event_digest
        return event

    def _task_row(self, connection, task_id):
        _require_nonempty(task_id, "task_id")
        row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise MAEPError("task not found")
        task = _loads_object(row["task_json"], "task")
        validate_task(task)
        if task.get("task_id") != task_id or task.get("state") != row["state"]:
            raise MAEPError("task record and indexed state disagree; reconciliation required")
        if task.get("policy_version") != row["policy_version"]:
            raise MAEPError("task payload and indexed policy version disagree; reconciliation required")
        return row, task

    def create_task(self, task, *, candidate_ref):
        _reject_secret_fields(task, "task")
        validate_task(task)
        _require_nonempty(candidate_ref, "candidate_ref")
        if task.get("policy_version") != POLICY_VERSION:
            raise MAEPError("task policy version is stale; reassess under current MAEP first")
        if task.get("state") != "DRAFT":
            raise MAEPError("new tasks must start in DRAFT; no pre-authorized task creation")
        task_id = task["task_id"]
        create_auth = self._authorize(
            "WRITE", f"memory:task/{task_id}", [f"memory:task:{task_id}:write"], task_id
        )
        now = _now()
        body = dict(task)
        serialized = _canonical_json(body)
        with self._transaction() as connection:
            create_auth = self._authorize(
                "WRITE", f"memory:task/{task_id}", [f"memory:task:{task_id}:write"], task_id
            )
            connection.execute(
                """INSERT INTO tasks(
                    task_id, state, policy_version, candidate_ref, row_version,
                    task_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (task_id, "DRAFT", POLICY_VERSION, candidate_ref, serialized, now, now),
            )
            self._append_event(
                connection, task_id=task_id, event_type="task.created",
                candidate_ref=candidate_ref,
                payload={
                    "row_version": 1, "state": "DRAFT", "task_digest": _digest(body),
                    "authorization_id": create_auth["authorization_id"],
                },
            )
        return {
            "task": body,
            "candidate_ref": candidate_ref,
            "row_version": 1,
            "created_at": now,
            "updated_at": now,
            "policy_status": "CURRENT",
        }

    def list_tasks(self, *, index_scope_task_id, limit=100, offset=0):
        """List canonical task snapshots through an explicitly authorized Memory index API.

        Authorization is bound to a caller-supplied existing task solely as the
        authorization context, never as the list of indexed task IDs. The evaluator
        must explicitly allow memory:tasks:index:read. The method reads no tables
        outside this MemoryStore and fails closed on schema/event/index mismatch.
        """
        _validate_task_index_args(index_scope_task_id, limit, offset)
        self._authorize(
            "READ", "memory:tasks/index",
            ["memory:tasks:index:read"], index_scope_task_id
        )
        return self._read_task_index(index_scope_task_id, limit=limit, offset=offset)

    def _read_task_index(self, index_scope_task_id, *, limit, offset):
        """Read-only index body shared by list_tasks and AuthorityEvidenceReader."""
        _validate_task_index_args(index_scope_task_id, limit, offset)
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            # Bind authorization context to a real canonical task before global listing.
            self._task_row(connection, index_scope_task_id)
            rows = connection.execute(
                "SELECT task_id, state, policy_version, candidate_ref, row_version, "
                "task_json, created_at, updated_at FROM tasks ORDER BY task_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            snapshots = []
            for row in rows:
                task = _loads_object(row["task_json"], "task")
                validate_task(task)
                if (task.get("task_id") != row["task_id"]
                        or task.get("state") != row["state"]
                        or task.get("policy_version") != row["policy_version"]):
                    raise MAEPError("canonical task index row/payload binding mismatch")
                if row["policy_version"] != POLICY_VERSION:
                    raise MAEPError("canonical task index contains stale policy records")
                snapshots.append({
                    "task": task,
                    "candidate_ref": row["candidate_ref"],
                    "row_version": row["row_version"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "policy_status": "CURRENT",
                })
            # The global event chain is validated by _ensure_ready; verify each selected
            # task also has its canonical creation event before making it index-visible.
            for snapshot in snapshots:
                tid = snapshot["task"]["task_id"]
                creation_events = connection.execute(
                    "SELECT event_type, candidate_ref, payload_json FROM maep_events "
                    "WHERE task_id=? AND event_type='task.created' ORDER BY sequence",
                    (tid,),
                ).fetchall()
                if len(creation_events) != 1:
                    raise MAEPError("canonical task index creation-event binding is missing or ambiguous")
                payload = _loads_object(creation_events[0]["payload_json"], "task creation event")
                if (creation_events[0]["candidate_ref"] != snapshot["candidate_ref"]
                        or payload.get("row_version") != 1
                        or not isinstance(payload.get("task_digest"), str)):
                    raise MAEPError("canonical task index creation-event binding mismatch")
                # Bind current state/version to the latest lifecycle event, not to the
                # original task.created event after a task has evolved.
                latest = connection.execute(
                    "SELECT event_type, candidate_ref, payload_json FROM maep_events "
                    "WHERE task_id=? AND event_type IN ('task.created','task.transitioned') "
                    "ORDER BY sequence DESC LIMIT 1",
                    (tid,),
                ).fetchone()
                if latest is None or latest["candidate_ref"] != snapshot["candidate_ref"]:
                    raise MAEPError("canonical task index latest lifecycle event missing or misbound")
                payload_latest = _loads_object(latest["payload_json"], "task lifecycle event")
                if latest["event_type"] == "task.created":
                    latest_state, latest_version = payload_latest.get("state"), payload_latest.get("row_version")
                else:
                    latest_state, latest_version = payload_latest.get("to_state"), payload_latest.get("row_version")
                if (latest_state != snapshot["task"]["state"]
                        or latest_version != snapshot["row_version"]):
                    raise MAEPError("canonical task index latest-state event binding mismatch")
            return {
                "tasks": snapshots,
                "limit": limit,
                "offset": offset,
                "returned": len(snapshots),
                "has_more": len(snapshots) == limit,
                "policy_version": POLICY_VERSION,
                "integrity_status": "PASS",
            }
        finally:
            connection.close()

    def get_task(self, task_id):
        self._authorize(
            "READ", f"memory:task/{task_id}", [f"memory:task:{task_id}:read"], task_id
        )
        return self._read_task(task_id)

    def _read_task(self, task_id):
        """Read-only task snapshot shared by get_task and AuthorityEvidenceReader."""
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            row, task = self._task_row(connection, task_id)
            return {
                "task": task,
                "candidate_ref": row["candidate_ref"],
                "row_version": row["row_version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "policy_status": "CURRENT" if row["policy_version"] == POLICY_VERSION else "STALE",
            }
        finally:
            connection.close()

    def transition_task(
        self, task_id, target, *, expected_version, resolution_evidence_ref=None,
        action_request=None, trigger="orchestrator"
    ):
        """Persist a MAEP-guarded transition without executing the described action.

        AUTHORIZED/RUNNING require a fresh action-specific grant from the trusted policy
        evaluator. ACCEPTED/CLOSED_VERIFIED require a trusted acceptance provider plus
        candidate-bound evidence. The actual Tools adapter must re-check authority again
        immediately before any external side effect.
        """
        _require_nonempty(target, "target state")
        action_authorization_id = None
        if target in {"AUTHORIZED", "RUNNING"}:
            action_authorization_id = self._authorize_external_action(action_request, task_id)
        acceptance_context = None
        if target in {"ACCEPTED", "CLOSED_VERIFIED"}:
            if not callable(self.acceptance_provider):
                raise MAEPError(
                    f"{target} blocked: trusted MAEP acceptance provider is unavailable"
                )
            try:
                acceptance_context = self.acceptance_provider(task_id, target)
            except Exception as exc:
                raise MAEPError("trusted MAEP acceptance evaluation failed; transition blocked") from exc
            if not isinstance(acceptance_context, dict):
                raise MAEPError("acceptance provider returned no decision object")

        transition_auth = self._authorize(
            "WRITE", f"memory:task/{task_id}", [f"memory:task:{task_id}:transition"], task_id
        )
        with self._transaction() as connection:
            row, task = self._task_row(connection, task_id)
            if row["policy_version"] != POLICY_VERSION:
                raise MAEPError("task policy version is stale; transition blocked")
            if expected_version != row["row_version"]:
                raise MAEPError("task version conflict; reload and reconcile before transition")
            current = row["state"]
            resolution_ok = False
            if current == "BLOCKED" and target == "ASSESSED":
                if not _nonempty(resolution_evidence_ref):
                    raise MAEPError("BLOCKED -> ASSESSED requires linked resolution evidence")
                evidence_row = connection.execute(
                    "SELECT task_id, candidate_ref, policy_version FROM evidence WHERE evidence_id=?",
                    (resolution_evidence_ref,),
                ).fetchone()
                if (
                    evidence_row is None or evidence_row["task_id"] != task_id
                    or evidence_row["candidate_ref"] != row["candidate_ref"]
                    or evidence_row["policy_version"] != POLICY_VERSION
                ):
                    raise MAEPError("blocker resolution evidence is missing, stale or out of scope")
                resolution_ok = True

            guards = {}
            gate_ids = []
            acceptance_payload = None
            if target == "VERIFYING":
                result_row = connection.execute(
                    """SELECT evidence_id FROM evidence
                       WHERE task_id=? AND candidate_ref=? AND policy_version=?
                       ORDER BY created_at DESC LIMIT 1""",
                    (task_id, row["candidate_ref"], POLICY_VERSION),
                ).fetchone()
                guards["result_recorded"] = result_row is not None
                guards["candidate_ref"] = row["candidate_ref"]
            if target == "READY":
                guards["task_valid"] = validate_task(task)
            if target in {"AUTHORIZED", "RUNNING"}:
                guards["authorization_valid"] = bool(action_authorization_id)
            if target in {"ACCEPTED", "CLOSED_VERIFIED"}:
                if (
                    acceptance_context.get("candidate_ref") != row["candidate_ref"]
                    or acceptance_context.get("policy_version") != POLICY_VERSION
                ):
                    raise MAEPError("acceptance context candidate/policy mismatch")
                gates = acceptance_context.get("mandatory_gates")
                if not isinstance(gates, list):
                    raise MAEPError("acceptance provider must return mandatory_gates")
                if any(not isinstance(gate, dict) for gate in gates):
                    raise MAEPError("acceptance provider returned a malformed gate")
                for gate in gates:
                    if gate.get("task_id") != task_id or gate.get("candidate_ref") != row["candidate_ref"]:
                        raise MAEPError("acceptance gate task/candidate mismatch")
                mandatory_gates = [gate for gate in gates if gate.get("required") is True]
                if not mandatory_gates:
                    raise MAEPError("acceptance blocked: no mandatory gates were supplied")
                mandatory_criteria = {
                    criterion["criterion_id"]
                    for criterion in task.get("acceptance_criteria", [])
                    if isinstance(criterion, dict) and criterion.get("mandatory") is True
                }
                gate_criteria = {
                    criterion_id
                    for gate in mandatory_gates
                    for criterion_id in gate.get("criteria_refs", [])
                }
                if not mandatory_criteria or not mandatory_criteria.issubset(gate_criteria):
                    raise MAEPError("acceptance gates do not cover every mandatory task criterion")
                evidence_rows = connection.execute(
                    """SELECT evidence_id, evidence_json FROM evidence
                       WHERE task_id=? AND candidate_ref=? AND policy_version=?""",
                    (task_id, row["candidate_ref"], POLICY_VERSION),
                ).fetchall()
                evidence_by_id = {
                    item["evidence_id"]: _loads_object(item["evidence_json"], "evidence")
                    for item in evidence_rows
                }
                for evidence in evidence_by_id.values():
                    validate_evidence(evidence, candidate_ref=row["candidate_ref"])
                gates_pass = all(
                    evaluate_gate(gate, evidence_by_id, row["candidate_ref"])
                    for gate in mandatory_gates
                )
                gate_ids = [gate.get("gate_id", "UNIDENTIFIED") for gate in mandatory_gates]
                if not gates_pass:
                    raise MAEPError("acceptance blocked: one or more mandatory gates failed or lack evidence")
                guards["mandatory_gates_pass"] = True
                if target == "CLOSED_VERIFIED":
                    closure = acceptance_context.get("closure")
                    if not isinstance(closure, dict):
                        raise MAEPError("CLOSED_VERIFIED requires a closure record")
                    if closure.get("task_id") != task_id or closure.get("final_state") != "CLOSED_VERIFIED":
                        raise MAEPError("closure task identity or terminal state mismatch")
                    validate_closure(
                        closure,
                        mandatory_gates=mandatory_gates,
                        evidence_by_id=evidence_by_id,
                        candidate_ref=row["candidate_ref"],
                        policy_version=POLICY_VERSION,
                    )
                    guards.update({
                        "criteria_pass": True,
                        "evidence_resolved": True,
                        "no_mandatory_blocker": True,
                    })
                    acceptance_payload = {"mandatory_gates": mandatory_gates, "closure": closure}
                else:
                    acceptance_payload = {"mandatory_gates": mandatory_gates}

            result = transition(
                current, target, guards=guards, blocker_resolved=resolution_ok
            )
            task["state"] = result
            now = _now()
            new_version = row["row_version"] + 1
            transition_auth = self._authorize(
                "WRITE", f"memory:task/{task_id}", [f"memory:task:{task_id}:transition"], task_id
            )
            if target in {"AUTHORIZED", "RUNNING"}:
                action_authorization_id = self._authorize_external_action(action_request, task_id)
            connection.execute(
                """UPDATE tasks SET state=?, row_version=?, task_json=?, updated_at=?
                   WHERE task_id=? AND row_version=?""",
                (result, new_version, _canonical_json(task), now, task_id, row["row_version"]),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise MAEPError("concurrent task update detected; state change rejected")
            self._append_event(
                connection, task_id=task_id, event_type="task.transitioned",
                candidate_ref=row["candidate_ref"],
                payload={
                    "from_state": current, "to_state": result, "row_version": new_version,
                    "trigger": trigger, "resolution_evidence_ref": resolution_evidence_ref,
                    "action_authorization_id": action_authorization_id,
                    "transition_authorization_id": transition_auth["authorization_id"],
                    "mandatory_gate_ids": gate_ids,
                    "acceptance": acceptance_payload,
                },
            )
        return {
            "task": task,
            "candidate_ref": row["candidate_ref"],
            "row_version": new_version,
            "created_at": row["created_at"],
            "updated_at": now,
            "policy_status": "CURRENT",
        }

    def record_evidence(self, task_id, evidence):
        _reject_secret_fields(evidence, "evidence")
        validate_evidence(evidence)
        evidence_auth = self._authorize(
            "WRITE", f"memory:evidence/{evidence.get('evidence_id')}",
            [f"memory:task:{task_id}:evidence:write"], task_id
        )
        with self._transaction() as connection:
            row, _ = self._task_row(connection, task_id)
            if row["policy_version"] != POLICY_VERSION:
                raise MAEPError("evidence write blocked by stale policy version")
            if evidence["candidate_ref"] != row["candidate_ref"]:
                raise MAEPError("evidence candidate does not match current task candidate")
            evidence_copy = dict(evidence)
            evidence_auth = self._authorize(
                "WRITE", f"memory:evidence/{evidence.get('evidence_id')}",
                [f"memory:task:{task_id}:evidence:write"], task_id
            )
            now = _now()
            connection.execute(
                """INSERT INTO evidence(evidence_id, task_id, candidate_ref, policy_version, evidence_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    evidence["evidence_id"], task_id, row["candidate_ref"], POLICY_VERSION,
                    _canonical_json(evidence_copy), now,
                ),
            )
            self._append_event(
                connection, task_id=task_id, event_type="evidence.recorded",
                candidate_ref=row["candidate_ref"],
                payload={
                    "evidence_id": evidence["evidence_id"], "evidence_digest": _digest(evidence_copy),
                    "authorization_id": evidence_auth["authorization_id"],
                },
            )
        return {"evidence_id": evidence["evidence_id"], "status": "RECORDED", "candidate_ref": evidence["candidate_ref"]}

    def get_evidence(self, task_id, evidence_id):
        """Read one immutable evidence record through the authorized Memory API.

        The returned binding includes the database-owned task, candidate and policy
        metadata. A record's own JSON fields are not accepted as proof of these bindings.
        """
        _validate_evidence_lookup_args(task_id, evidence_id)
        self._authorize(
            "READ", f"memory:evidence/{evidence_id}",
            [f"memory:task:{task_id}:evidence:read"], task_id
        )
        return self._read_evidence(task_id, evidence_id)

    def _read_evidence(self, task_id, evidence_id):
        """Read-only evidence body shared by get_evidence and AuthorityEvidenceReader."""
        _validate_evidence_lookup_args(task_id, evidence_id)
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            task_row, _ = self._task_row(connection, task_id)
            row = connection.execute(
                "SELECT evidence_id, task_id, candidate_ref, policy_version, evidence_json, created_at "
                "FROM evidence WHERE evidence_id=? AND task_id=?",
                (evidence_id, task_id),
            ).fetchone()
            if row is None:
                return None
            if (row["candidate_ref"] != task_row["candidate_ref"]
                    or row["policy_version"] != task_row["policy_version"]):
                raise MAEPError("evidence database binding differs from canonical task")
            evidence = _loads_object(row["evidence_json"], "evidence")
            validate_evidence(evidence, candidate_ref=row["candidate_ref"])
            if evidence.get("evidence_id") != row["evidence_id"]:
                raise MAEPError("evidence identity differs from database key")
            return {
                "evidence_id": row["evidence_id"], "task_id": row["task_id"],
                "candidate_ref": row["candidate_ref"], "policy_version": row["policy_version"],
                "created_at": row["created_at"], "evidence": evidence,
            }
        finally:
            connection.close()

    def put_knowledge(self, task_id, claim, *, candidate_ref, source_ref, collector, method,
                      provenance_limitations, supersedes_record_id=None):
        """Append a versioned claim; never silently promote a claim to VERIFIED."""
        _reject_secret_fields(claim, "knowledge.claim")
        validate_claim(claim)
        for field, value in (
            ("candidate_ref", candidate_ref), ("source_ref", source_ref),
            ("collector", collector), ("method", method),
        ):
            _require_nonempty(value, field)
        _reject_secret_fields({
            "source_ref": source_ref, "collector": collector, "method": method,
            "provenance_limitations": provenance_limitations,
        }, "knowledge.provenance")
        if not isinstance(provenance_limitations, list):
            raise MAEPError("provenance_limitations must be a list")
        if claim.get("claim_type") == "FACT" and not claim.get("evidence_refs"):
            raise MAEPError("FACT knowledge requires evidence references")
        knowledge_auth = self._authorize(
            "WRITE", f"memory:knowledge/{claim.get('claim_id')}",
            [f"memory:task:{task_id}:knowledge:write"], task_id
        )
        with self._transaction() as connection:
            task_row, _ = self._task_row(connection, task_id)
            if task_row["policy_version"] != POLICY_VERSION:
                raise MAEPError("knowledge write blocked by stale policy version")
            if candidate_ref != task_row["candidate_ref"]:
                raise MAEPError("knowledge candidate must match current task candidate")
            for evidence_id in claim["evidence_refs"]:
                evidence_row = connection.execute(
                    "SELECT task_id, candidate_ref, policy_version FROM evidence WHERE evidence_id=?",
                    (evidence_id,),
                ).fetchone()
                if evidence_row is None or evidence_row["task_id"] != task_id:
                    raise MAEPError(f"knowledge references unavailable evidence: {evidence_id}")
                if evidence_row["candidate_ref"] != candidate_ref:
                    raise MAEPError(f"knowledge evidence candidate mismatch: {evidence_id}")
                if evidence_row["policy_version"] != POLICY_VERSION:
                    raise MAEPError(f"knowledge evidence policy is stale: {evidence_id}")
            latest = connection.execute(
                """SELECT record_id, version FROM knowledge_records
                   WHERE task_id=? AND claim_id=? ORDER BY version DESC LIMIT 1""",
                (task_id, claim["claim_id"]),
            ).fetchone()
            if latest is None:
                if supersedes_record_id is not None:
                    raise MAEPError("first knowledge version cannot supersede a nonexistent record")
                version = 1
            else:
                if supersedes_record_id != latest["record_id"]:
                    raise MAEPError("knowledge update must explicitly supersede the latest record ID")
                version = latest["version"] + 1
            knowledge_auth = self._authorize(
                "WRITE", f"memory:knowledge/{claim.get('claim_id')}",
                [f"memory:task:{task_id}:knowledge:write"], task_id
            )
            record_id = _unique_id("KNOW")
            created_at = _now()
            record = {
                "record_id": record_id,
                "claim": dict(claim),
                "task_id": task_id,
                "candidate_ref": candidate_ref,
                "policy_version": POLICY_VERSION,
                "version": version,
                "verification_status": "UNVERIFIED",
                "provenance": {
                    "source_ref": source_ref,
                    "collector": collector,
                    "method": method,
                    "collected_at": created_at,
                    "limitations": list(provenance_limitations),
                },
                "supersedes_record_id": supersedes_record_id,
                "created_at": created_at,
            }
            knowledge_auth = self._authorize(
                "WRITE", f"memory:knowledge/{claim.get('claim_id')}",
                [f"memory:task:{task_id}:knowledge:write"], task_id
            )
            record["authorization_id"] = knowledge_auth["authorization_id"]
            connection.execute(
                """INSERT INTO knowledge_records(
                    record_id, claim_id, version, task_id, candidate_ref, policy_version,
                    verification_status, supersedes_record_id, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'UNVERIFIED', ?, ?, ?)""",
                (
                    record_id, claim["claim_id"], version, task_id, candidate_ref,
                    POLICY_VERSION, supersedes_record_id, _canonical_json(record), created_at,
                ),
            )
            self._append_event(
                connection, task_id=task_id, event_type="knowledge.recorded",
                candidate_ref=candidate_ref,
                payload={
                    "record_id": record_id, "claim_id": claim["claim_id"], "version": version,
                    "verification_status": "UNVERIFIED", "record_digest": _digest(record),
                    "authorization_id": knowledge_auth["authorization_id"],
                },
            )
        return record

    def verify_knowledge(self, task_id, claim_id, *, candidate_ref, evidence_refs, verification_id, limitations):
        """Append an authorized verification version backed by stored candidate-bound evidence."""
        for field, value in (
            ("claim_id", claim_id), ("candidate_ref", candidate_ref), ("verification_id", verification_id)
        ):
            _require_nonempty(value, field)
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise MAEPError("verification requires evidence references")
        if not isinstance(limitations, list):
            raise MAEPError("verification limitations must be a list")
        auth = self._authorize(
            "WRITE", f"memory:knowledge/verify/{claim_id}",
            [f"memory:task:{task_id}:knowledge:verify"], task_id
        )
        with self._transaction() as connection:
            task_row, _ = self._task_row(connection, task_id)
            if task_row["policy_version"] != POLICY_VERSION:
                raise MAEPError("verification blocked by stale task policy version")
            if candidate_ref != task_row["candidate_ref"]:
                raise MAEPError("verification candidate does not match current task")
            latest = connection.execute(
                """SELECT * FROM knowledge_records WHERE task_id=? AND claim_id=?
                   ORDER BY version DESC LIMIT 1""",
                (task_id, claim_id),
            ).fetchone()
            if latest is None:
                raise MAEPError("knowledge claim not found")
            if latest["candidate_ref"] != candidate_ref or latest["policy_version"] != POLICY_VERSION:
                raise MAEPError("stale knowledge cannot be marked VERIFIED")
            for evidence_id in evidence_refs:
                evidence_row = connection.execute(
                    "SELECT task_id, candidate_ref, policy_version FROM evidence WHERE evidence_id=?",
                    (evidence_id,),
                ).fetchone()
                if (
                    evidence_row is None or evidence_row["task_id"] != task_id
                    or evidence_row["candidate_ref"] != candidate_ref
                    or evidence_row["policy_version"] != POLICY_VERSION
                ):
                    raise MAEPError(f"verification evidence is missing, stale, or out of scope: {evidence_id}")
            old_record = _loads_object(latest["record_json"], "knowledge record")
            validate_claim(old_record.get("claim"))
            auth = self._authorize(
                "WRITE", f"memory:knowledge/verify/{claim_id}",
                [f"memory:task:{task_id}:knowledge:verify"], task_id
            )
            new_version = latest["version"] + 1
            record_id = _unique_id("KNOW")
            created_at = _now()
            new_record = dict(old_record)
            new_record.update({
                "record_id": record_id,
                "version": new_version,
                "verification_status": "VERIFIED",
                "supersedes_record_id": latest["record_id"],
                "created_at": created_at,
                "verification": {
                    "verification_id": verification_id,
                    "verifier_principal": auth["principal"],
                    "authorization_id": auth["authorization_id"],
                    "verified_at": created_at,
                    "evidence_refs": list(evidence_refs),
                    "limitations": list(limitations),
                },
            })
            auth = self._authorize(
                "WRITE", f"memory:knowledge/verify/{claim_id}",
                [f"memory:task:{task_id}:knowledge:verify"], task_id
            )
            new_record["verification"]["authorization_id"] = auth["authorization_id"]
            connection.execute(
                """INSERT INTO knowledge_records(
                    record_id, claim_id, version, task_id, candidate_ref, policy_version,
                    verification_status, supersedes_record_id, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'VERIFIED', ?, ?, ?)""",
                (
                    record_id, claim_id, new_version, task_id, candidate_ref, POLICY_VERSION,
                    latest["record_id"], _canonical_json(new_record), created_at,
                ),
            )
            self._append_event(
                connection, task_id=task_id, event_type="knowledge.verified",
                candidate_ref=candidate_ref,
                payload={
                    "record_id": record_id, "claim_id": claim_id, "version": new_version,
                    "verification_id": verification_id, "evidence_refs": list(evidence_refs),
                    "authorization_id": auth["authorization_id"],
                },
            )
        return new_record

    def get_knowledge(self, task_id, claim_id, *, include_stale=False):
        """Read the latest version of one claim through the scoped Memory API.

        Authorization is task-scoped. Cross-task retrieval is intentionally not
        inferred or exposed by this API. Database-owned task/candidate/policy and
        latest-version bindings are returned separately from record_json.
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise MAEPError("task_id must be a non-empty string")
        if not isinstance(claim_id, str) or not claim_id.strip():
            raise MAEPError("claim_id must be a non-empty string")
        if not isinstance(include_stale, bool):
            raise MAEPError("include_stale must be boolean")
        self._authorize(
            "READ", f"memory:knowledge/{claim_id}",
            [f"memory:task:{task_id}:knowledge:read"], task_id
        )
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            task_row, _ = self._task_row(connection, task_id)
            row = connection.execute(
                """SELECT * FROM knowledge_records
                   WHERE task_id=? AND claim_id=? ORDER BY version DESC LIMIT 1""",
                (task_id, claim_id),
            ).fetchone()
            if row is None:
                return None
            record = _loads_object(row["record_json"], "knowledge record")
            if (record.get("record_id") != row["record_id"]
                    or record.get("claim", {}).get("claim_id") != row["claim_id"]
                    or record.get("version") != row["version"]
                    or record.get("task_id") != row["task_id"]
                    or record.get("candidate_ref") != row["candidate_ref"]
                    or record.get("policy_version") != row["policy_version"]
                    or record.get("verification_status") != row["verification_status"]):
                raise MAEPError("knowledge record content differs from canonical database bindings")
            validate_claim(record.get("claim"))
            status = "CURRENT"
            if (row["policy_version"] != POLICY_VERSION
                    or row["policy_version"] != task_row["policy_version"]
                    or row["candidate_ref"] != task_row["candidate_ref"]):
                status = "STALE"
            if status == "STALE" and not include_stale:
                return None
            record["record_status"] = status
            record["verification_status"] = row["verification_status"]
            return record
        except sqlite3.Error as exc:
            raise MAEPError("knowledge retrieval failed; no result may be treated as verified") from exc
        finally:
            connection.close()

    def search_knowledge(self, task_id, query, *, limit=20, include_stale=False):
        _require_nonempty(query, "query")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise MAEPError("limit must be an integer from 1 to 100")
        self._authorize(
            "READ", f"memory:knowledge/task/{task_id}",
            [f"memory:task:{task_id}:knowledge:read"], task_id
        )
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            task_row, _ = self._task_row(connection, task_id)
            rows = connection.execute(
                """SELECT k.* FROM knowledge_records k
                   JOIN (SELECT claim_id, MAX(version) AS version
                         FROM knowledge_records WHERE task_id=? GROUP BY claim_id) latest
                     ON latest.claim_id=k.claim_id AND latest.version=k.version
                   WHERE k.task_id=? ORDER BY k.created_at DESC""",
                (task_id, task_id),
            ).fetchall()
            results = []
            for row in rows:
                record = _loads_object(row["record_json"], "knowledge record")
                statement = record.get("claim", {}).get("statement", "")
                if not isinstance(statement, str) or query.casefold() not in statement.casefold():
                    continue
                status = "CURRENT"
                if row["policy_version"] != POLICY_VERSION or row["candidate_ref"] != task_row["candidate_ref"]:
                    status = "STALE"
                if status == "STALE" and not include_stale:
                    continue
                record["record_status"] = status
                record["verification_status"] = row["verification_status"]
                results.append(record)
                if len(results) >= limit:
                    break
            return results
        except sqlite3.Error as exc:
            raise MAEPError("knowledge retrieval failed; no result may be treated as verified") from exc
        finally:
            connection.close()

    def update_candidate(self, task_id, *, expected_version, old_candidate_ref, new_candidate_ref):
        _require_nonempty(old_candidate_ref, "old_candidate_ref")
        _require_nonempty(new_candidate_ref, "new_candidate_ref")
        if old_candidate_ref == new_candidate_ref:
            raise MAEPError("candidate is unchanged; no mutation is required")
        candidate_auth = self._authorize(
            "WRITE", f"memory:task/{task_id}/candidate",
            [f"memory:task:{task_id}:candidate:change"], task_id
        )
        with self._transaction() as connection:
            row, task = self._task_row(connection, task_id)
            if row["policy_version"] != POLICY_VERSION:
                raise MAEPError("candidate change blocked by stale policy version")
            if row["row_version"] != expected_version:
                raise MAEPError("task version conflict; candidate change blocked")
            if row["candidate_ref"] != old_candidate_ref:
                raise MAEPError("old candidate reference does not match canonical task state")
            evidence_ids = [
                item["evidence_id"] for item in connection.execute(
                    "SELECT evidence_id FROM evidence WHERE task_id=? AND candidate_ref=?",
                    (task_id, old_candidate_ref),
                ).fetchall()
            ]
            impact = assess_candidate_change(old_candidate_ref, new_candidate_ref, evidence_ids)
            candidate_auth = self._authorize(
                "WRITE", f"memory:task/{task_id}/candidate",
                [f"memory:task:{task_id}:candidate:change"], task_id
            )
            now = _now()
            new_version = row["row_version"] + 1
            connection.execute(
                """UPDATE tasks SET candidate_ref=?, row_version=?, updated_at=?
                   WHERE task_id=? AND row_version=?""",
                (new_candidate_ref, new_version, now, task_id, expected_version),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise MAEPError("concurrent candidate change detected")
            self._append_event(
                connection, task_id=task_id, event_type="task.candidate_changed",
                candidate_ref=new_candidate_ref,
                payload={
                    "old_candidate_ref": old_candidate_ref, "new_candidate_ref": new_candidate_ref,
                    "impact_assessment_required": impact["impact_assessment_required"],
                    "invalidated_evidence_refs": impact["invalidate_evidence_refs"],
                    "new_row_version": new_version,
                    "authorization_id": candidate_auth["authorization_id"],
                },
            )
        return {"task_id": task_id, "candidate_ref": new_candidate_ref, "row_version": new_version, **impact}

    def _live_state(self, task_id):
        if not callable(self.live_state_provider):
            raise MAEPError("live-state observer unavailable; resume cannot be approved")
        try:
            observed = self.live_state_provider(task_id)
        except Exception as exc:
            raise MAEPError("live-state observation failed; resume blocked") from exc
        if not isinstance(observed, dict):
            raise MAEPError("live-state observer returned no object")
        for field in ("task_id", "candidate_ref", "policy_version", "observed_at", "resources"):
            if field not in observed:
                raise MAEPError(f"live-state observation missing {field}")
        if not all(_nonempty(observed[field]) for field in ("task_id", "candidate_ref", "policy_version", "observed_at")):
            raise MAEPError("live-state identity/version fields must be non-empty")
        if not isinstance(observed["resources"], list):
            raise MAEPError("live-state resources must be a list")
        resources = []
        seen = set()
        for item in observed["resources"]:
            if not isinstance(item, dict) or not _nonempty(item.get("resource_id")) or not _nonempty(item.get("version")):
                raise MAEPError("each live resource needs resource_id and version")
            if item["resource_id"] in seen:
                raise MAEPError("duplicate live resource observation")
            seen.add(item["resource_id"])
            resources.append({"resource_id": item["resource_id"], "version": item["version"]})
        return {
            "task_id": observed["task_id"],
            "candidate_ref": observed["candidate_ref"],
            "policy_version": observed["policy_version"],
            "observed_at": observed["observed_at"],
            "resources": sorted(resources, key=lambda item: item["resource_id"]),
        }

    def save_checkpoint(
        self, task_id, *, expected_version, completed_steps, pending_steps, blockers,
        decisions, evidence_refs, next_action, linked_task_id=None
    ):
        _reject_secret_fields({
            "completed_steps": completed_steps, "pending_steps": pending_steps,
            "blockers": blockers, "decisions": decisions, "evidence_refs": evidence_refs,
            "next_action": next_action, "linked_task_id": linked_task_id,
        }, "checkpoint")
        if not isinstance(completed_steps, list) or not isinstance(pending_steps, list):
            raise MAEPError("completed_steps and pending_steps must be lists")
        if not isinstance(blockers, list) or not isinstance(decisions, list) or not isinstance(evidence_refs, list):
            raise MAEPError("blockers, decisions and evidence_refs must be lists")
        if not isinstance(next_action, dict):
            raise MAEPError("next_action must be an object")
        for field in ("description", "expected_result", "stop_condition"):
            _require_nonempty(next_action.get(field), f"next_action.{field}")
        if not isinstance(next_action.get("preconditions"), list):
            raise MAEPError("next_action.preconditions must be a list")
        auth_requirement = next_action.get("required_authorization")
        if not (
            _nonempty(auth_requirement)
            or (isinstance(auth_requirement, dict) and bool(auth_requirement))
            or (isinstance(auth_requirement, list) and bool(auth_requirement))
        ):
            raise MAEPError("next_action.required_authorization must be explicit")
        for step in completed_steps:
            if not isinstance(step, dict) or not all(_nonempty(step.get(k)) for k in ("step_id", "outcome", "timestamp")):
                raise MAEPError("completed step missing ID, outcome or timestamp")
            refs = step.get("evidence_refs")
            if not isinstance(refs, list):
                raise MAEPError("completed step evidence_refs must be a list")
            if step.get("verification_status") not in {"VERIFIED", "UNVERIFIED"}:
                raise MAEPError("completed step must explicitly label verification status")
            if not refs and step.get("verification_status") != "UNVERIFIED":
                raise MAEPError("completed step without evidence must be labeled UNVERIFIED")
            if refs and step.get("verification_status") == "VERIFIED" and not all(_nonempty(ref) for ref in refs):
                raise MAEPError("verified completed-step evidence references must be non-empty")
        for step in pending_steps:
            if not isinstance(step, dict) or not _nonempty(step.get("step_id")):
                raise MAEPError("pending step requires step_id")
            if not isinstance(step.get("prerequisites"), list) or not isinstance(step.get("acceptance_conditions"), list) or not step["acceptance_conditions"]:
                raise MAEPError("pending step requires prerequisite list and acceptance conditions")
        for blocker in blockers:
            validate_blocker(blocker)
        for decision in decisions:
            required = ("decision_id", "decision", "authority_source", "rationale", "timestamp")
            if not isinstance(decision, dict) or not all(_nonempty(decision.get(k)) for k in required):
                raise MAEPError("decision record incomplete")
            if not isinstance(decision.get("scope"), (dict, list)):
                raise MAEPError("decision scope must be explicit")
        observed = self._live_state(task_id)
        checkpoint_auth = self._authorize(
            "WRITE", f"memory:checkpoint/{task_id}",
            [f"memory:task:{task_id}:checkpoint:write"], task_id
        )
        checkpoint_id = _unique_id("CHK")
        created_at = _now()
        with self._transaction() as connection:
            row, task = self._task_row(connection, task_id)
            if row["row_version"] != expected_version:
                raise MAEPError("task version changed during checkpoint capture; retry only after reconciliation")
            if row["policy_version"] != POLICY_VERSION:
                raise MAEPError("checkpoint blocked by stale policy")
            if observed["task_id"] != task_id:
                raise MAEPError("live task identity conflicts with requested checkpoint")
            if observed["candidate_ref"] != row["candidate_ref"]:
                raise MAEPError("live candidate conflicts with canonical task candidate")
            if observed["policy_version"] != POLICY_VERSION:
                raise MAEPError("live policy version is stale")
            all_evidence_refs = list(dict.fromkeys(
                list(evidence_refs)
                + [ref for step in completed_steps for ref in step.get("evidence_refs", [])]
            ))
            for evidence_id in all_evidence_refs:
                _require_nonempty(evidence_id, "checkpoint evidence reference")
                evidence_row = connection.execute(
                    "SELECT task_id, candidate_ref, policy_version FROM evidence WHERE evidence_id=?",
                    (evidence_id,),
                ).fetchone()
                if (
                    evidence_row is None or evidence_row["task_id"] != task_id
                    or evidence_row["candidate_ref"] != row["candidate_ref"]
                    or evidence_row["policy_version"] != POLICY_VERSION
                ):
                    raise MAEPError(f"checkpoint evidence unresolved, stale or out of scope: {evidence_id}")
            current_event_seq = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM maep_events"
            ).fetchone()[0]
            record = {
                "record_version": CONTINUITY_VERSION,
                "task_id": task_id,
                "created_at": created_at,
                "updated_at": created_at,
                "linked_task_id": linked_task_id,
                "objective": task["objective"],
                "scope": task["scope"],
                "current_state": row["state"],
                "state_as_of": row["updated_at"],
                "candidate_ref": row["candidate_ref"],
                "policy_version": POLICY_VERSION,
                "task_version": row["row_version"],
                "completed_steps": completed_steps,
                "pending_steps": pending_steps,
                "blockers": blockers,
                "decisions": decisions,
                "evidence_refs": all_evidence_refs,
                "checkpoint": {
                    "checkpoint_id": checkpoint_id,
                    "schema_version": CONTINUITY_VERSION,
                    "task_id": task_id,
                    "candidate_ref": row["candidate_ref"],
                    "policy_version": POLICY_VERSION,
                    "captured_at": created_at,
                    "event_sequence": current_event_seq,
                    "content_digest": "",
                },
                "next_action": dict(next_action),
                "freshness": {
                    "last_live_state_inspection_at": observed["observed_at"],
                    "inspected_resources": observed["resources"],
                    "stale_unknown_reasons": [],
                },
                "integrity_and_recovery": {
                    "last_successfully_loaded_event_sequence": current_event_seq,
                    "parse_validation_result": "PASS",
                    "detected_gaps_or_corruption": [],
                },
            }
            record["checkpoint"]["content_digest"] = _digest(record)
            _validate_continuity_record(record, expected_task_id=task_id)
            checkpoint_auth = self._authorize(
                "WRITE", f"memory:checkpoint/{task_id}",
                [f"memory:task:{task_id}:checkpoint:write"], task_id
            )
            digest = record["checkpoint"]["content_digest"]
            connection.execute(
                """INSERT INTO checkpoints(
                    checkpoint_id, task_id, task_version, candidate_ref, policy_version,
                    event_sequence, content_digest, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint_id, task_id, row["row_version"], row["candidate_ref"],
                    POLICY_VERSION, current_event_seq, digest, _canonical_json(record), created_at,
                ),
            )
            self._append_event(
                connection, task_id=task_id, event_type="checkpoint.saved",
                candidate_ref=row["candidate_ref"],
                payload={
                    "checkpoint_id": checkpoint_id, "task_version": row["row_version"],
                    "content_digest": digest, "authorization_id": checkpoint_auth["authorization_id"],
                },
            )
        return record

    def latest_checkpoint(self, task_id):
        self._authorize(
            "READ", f"memory:checkpoint/{task_id}",
            [f"memory:task:{task_id}:checkpoint:read"], task_id
        )
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            self._task_row(connection, task_id)
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE task_id=? ORDER BY checkpoint_sequence DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            record = _loads_object(row["record_json"], "checkpoint")
            _validate_continuity_record(record, expected_task_id=task_id)
            metadata = record.get("checkpoint")
            if not isinstance(metadata, dict) or metadata.get("content_digest") != row["content_digest"]:
                raise MAEPError("checkpoint digest metadata mismatch; resume blocked")
            unsigned = json.loads(_canonical_json(record))
            unsigned["checkpoint"]["content_digest"] = ""
            if _digest(unsigned) != row["content_digest"]:
                raise MAEPError("checkpoint digest validation failed; resume blocked")
            return record
        finally:
            connection.close()

    def assess_resume(self, task_id):
        """Assess resumption; this never executes the next action.

        CURRENT only means the stored checkpoint matches the observed state. The
        orchestrator must still obtain fresh action-specific authorization before effects.
        """
        self._authorize(
            "READ", f"memory:checkpoint/{task_id}",
            [f"memory:task:{task_id}:checkpoint:read"], task_id
        )
        result = {
            "task_id": task_id,
            "status": "UNKNOWN",
            "can_resume": False,
            "differences": [],
            "observed_at": _now(),
            "audit_recorded": False,
        }
        try:
            connection = self._connect(readonly=True)
            try:
                self._ensure_ready(connection)
                task_row, task = self._task_row(connection, task_id)
                checkpoint_row = connection.execute(
                    "SELECT * FROM checkpoints WHERE task_id=? ORDER BY checkpoint_sequence DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
                if task_row["state"] in {"FAILED", "CANCELLED", "CLOSED_VERIFIED"}:
                    result.update(
                        status="BLOCKED",
                        differences=["terminal task cannot resume; continue through a linked task/amendment"],
                    )
                elif checkpoint_row is None:
                    result.update(status="PARTIAL", differences=["no durable checkpoint exists"])
                else:
                    record = _loads_object(checkpoint_row["record_json"], "checkpoint")
                    _validate_continuity_record(record, expected_task_id=task_id)
                    metadata = record.get("checkpoint")
                    unsigned = json.loads(_canonical_json(record))
                    if not isinstance(metadata, dict):
                        result.update(status="BLOCKED", differences=["checkpoint metadata is malformed"])
                    else:
                        stored_digest = metadata.get("content_digest")
                        unsigned["checkpoint"]["content_digest"] = ""
                        digest_ok = (
                            stored_digest == checkpoint_row["content_digest"]
                            and _digest(unsigned) == stored_digest
                        )
                        if not digest_ok:
                            result.update(status="BLOCKED", differences=["checkpoint digest failed"])
                        else:
                            differences = []
                            conflicts = []
                            unknowns = []
                            hard_blocks = []
                            if record.get("task_id") != task_id or metadata.get("task_id") != task_id:
                                conflicts.append("checkpoint task identity differs")
                            if record.get("candidate_ref") != task_row["candidate_ref"] or metadata.get("candidate_ref") != task_row["candidate_ref"]:
                                differences.append("checkpoint candidate differs from canonical task candidate")
                            if record.get("policy_version") != POLICY_VERSION or task_row["policy_version"] != POLICY_VERSION:
                                differences.append("checkpoint/task policy is stale")
                            if record.get("task_version") != task_row["row_version"] or record.get("current_state") != task_row["state"]:
                                differences.append("task state changed after checkpoint")
                            if result["status"] not in {"PARTIAL", "BLOCKED"}:
                                try:
                                    observed = self._live_state(task_id)
                                    if observed["task_id"] != task_id:
                                        conflicts.append("live task identity differs")
                                    if observed["candidate_ref"] != task_row["candidate_ref"]:
                                        conflicts.append("live candidate conflicts with canonical task candidate")
                                    if observed["policy_version"] != POLICY_VERSION:
                                        differences.append("live policy version is stale")
                                    recorded_resources = {
                                        item["resource_id"]: item["version"]
                                        for item in record["freshness"]["inspected_resources"]
                                    }
                                    live_resources = {
                                        item["resource_id"]: item["version"] for item in observed["resources"]
                                    }
                                    if set(recorded_resources) != set(live_resources):
                                        unknowns.append("live resource inventory differs from checkpoint")
                                    for resource_id in set(recorded_resources) & set(live_resources):
                                        if recorded_resources[resource_id] != live_resources[resource_id]:
                                            differences.append(f"resource version changed: {resource_id}")
                                    event_seq = int(record["checkpoint"]["event_sequence"])
                                    count = connection.execute(
                                        "SELECT COUNT(*) FROM maep_events WHERE sequence<=?", (event_seq,)
                                    ).fetchone()[0]
                                    if count != event_seq:
                                        conflicts.append("event sequence has a gap or missing history")
                                    later = connection.execute(
                                        """SELECT event_type, payload_json FROM maep_events
                                           WHERE task_id=? AND sequence>? ORDER BY sequence""",
                                        (task_id, event_seq),
                                    ).fetchall()
                                    for event in later:
                                        payload = _loads_object(event["payload_json"], "event payload")
                                        if event["event_type"] in {"checkpoint.saved", "resume.assessed"}:
                                            if event["event_type"] == "checkpoint.saved" and payload.get("checkpoint_id") != record["checkpoint"]["checkpoint_id"]:
                                                differences.append("a newer checkpoint event exists")
                                            continue
                                        differences.append(f"task event occurred after checkpoint: {event['event_type']}")
                                    for evidence_id in record.get("evidence_refs", []):
                                        evidence_row = connection.execute(
                                            "SELECT task_id,candidate_ref,policy_version FROM evidence WHERE evidence_id=?",
                                            (evidence_id,),
                                        ).fetchone()
                                        if (
                                            evidence_row is None or evidence_row["task_id"] != task_id
                                            or evidence_row["candidate_ref"] != task_row["candidate_ref"]
                                            or evidence_row["policy_version"] != POLICY_VERSION
                                        ):
                                            conflicts.append(f"checkpoint evidence is unresolved or mismatched: {evidence_id}")
                                except MAEPError as exc:
                                    unknowns.append(str(exc))
                                unresolved = [
                                    blocker for blocker in record.get("blockers", [])
                                    if not isinstance(blocker, dict) or blocker.get("status") != "RESOLVED"
                                ]
                                if unresolved:
                                    hard_blocks.append("checkpoint has unresolved blockers")
                                if conflicts:
                                    result.update(status="CONFLICTING", differences=conflicts + hard_blocks + differences + unknowns)
                                elif hard_blocks:
                                    result.update(status="BLOCKED", differences=hard_blocks + differences + unknowns)
                                elif differences:
                                    result.update(status="STALE", differences=differences + unknowns)
                                elif unknowns:
                                    result.update(status="UNKNOWN", differences=unknowns)
                                else:
                                    result.update(status="CURRENT", can_resume=True, differences=[])
                                result["checkpoint_id"] = record["checkpoint"]["checkpoint_id"]
            finally:
                connection.close()
        except MAEPError as exc:
            result.update(status="BLOCKED", can_resume=False, differences=[str(exc)])

        # MAEP requires the decision itself to be durable before further action.
        try:
            resume_auth = self._authorize(
                "WRITE", f"memory:resume/{task_id}",
                [f"memory:task:{task_id}:resume:record"], task_id
            )
            with self._transaction() as connection:
                _, _ = self._task_row(connection, task_id)
                resume_auth = self._authorize(
                    "WRITE", f"memory:resume/{task_id}",
                    [f"memory:task:{task_id}:resume:record"], task_id
                )
                self._append_event(
                    connection, task_id=task_id, event_type="resume.assessed",
                    candidate_ref=None,
                    payload={
                        "status": result["status"], "can_resume": result["can_resume"],
                        "differences": result["differences"], "checkpoint_id": result.get("checkpoint_id"),
                        "observed_at": result["observed_at"],
                        "authorization_id": resume_auth["authorization_id"],
                    },
                )
            result["audit_recorded"] = True
        except MAEPError as exc:
            result.update(
                status="BLOCKED", can_resume=False, audit_recorded=False,
                differences=list(result["differences"]) + [f"resume decision could not be persisted: {exc}"],
            )
        return result

    def get_events(self, task_id, *, limit=100):
        _validate_event_limit(limit)
        self._authorize(
            "READ", f"memory:events/{task_id}",
            [f"memory:task:{task_id}:events:read"], task_id
        )
        return self._read_events(task_id, limit=limit)

    def _read_events(self, task_id, *, limit):
        """Read-only event body shared by get_events and AuthorityEvidenceReader."""
        _validate_event_limit(limit)
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            self._task_row(connection, task_id)
            rows = connection.execute(
                "SELECT * FROM maep_events WHERE task_id=? ORDER BY sequence DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
            results = []
            for row in reversed(rows):
                results.append({
                    "sequence": row["sequence"], "event_id": row["event_id"],
                    "task_id": row["task_id"], "event_type": row["event_type"],
                    "policy_version": row["policy_version"], "candidate_ref": row["candidate_ref"],
                    "occurred_at": row["occurred_at"], "prev_digest": row["prev_digest"],
                    "event_digest": row["event_digest"],
                    "payload": _loads_object(row["payload_json"], "event payload"),
                })
            return results
        finally:
            connection.close()

    def check_integrity(self, *, task_id):
        self._authorize(
            "READ", "memory:database/integrity",
            ["memory:integrity:read"], task_id
        )
        return self._inspect_integrity()

    def _inspect_integrity(self):
        """Read-only integrity inspection shared by check_integrity and AuthorityEvidenceReader."""
        connection = self._connect(readonly=True)
        try:
            self._ensure_ready(connection)
            result = connection.execute("PRAGMA integrity_check").fetchall()
            messages = [row[0] for row in result]
            if messages != ["ok"]:
                return {"status": "FAIL", "scope": "SQLite structural integrity", "details": messages}
            checkpoints = connection.execute(
                "SELECT checkpoint_id, content_digest, record_json FROM checkpoints"
            ).fetchall()
            for row in checkpoints:
                record = _loads_object(row["record_json"], "checkpoint")
                meta = record.get("checkpoint")
                if not isinstance(meta, dict) or meta.get("content_digest") != row["content_digest"]:
                    return {"status": "FAIL", "scope": "checkpoint digest consistency", "checkpoint_id": row["checkpoint_id"]}
                record["checkpoint"]["content_digest"] = ""
                if _digest(record) != row["content_digest"]:
                    return {"status": "FAIL", "scope": "checkpoint digest integrity", "checkpoint_id": row["checkpoint_id"]}
            return {
                "status": "PASS",
                "scope": "SQLite structural integrity, SHA-256 event-chain continuity, and checkpoint digest consistency only",
                "event_count": connection.execute("SELECT COUNT(*) FROM maep_events").fetchone()[0],
                "evidence_count": connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
                "knowledge_record_count": connection.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0],
                "checkpoint_count": len(checkpoints),
                "limitations": [
                    "Does not prove authorship, semantic truth, backup provenance or resistance to privileged file/database edits."
                ],
            }
        except MAEPError as exc:
            return {
                "status": "FAIL",
                "scope": "Memory schema/event-chain/checkpoint integrity",
                "details": [str(exc)],
                "automatic_repair": "NOT_PERFORMED",
            }
        except sqlite3.Error as exc:
            raise MAEPError("integrity inspection failed; no automatic repair attempted") from exc
        finally:
            connection.close()

    def backup_to(self, destination, *, task_id):
        """Create a verified SQLite online backup. Existing destinations are never overwritten."""
        target = Path(destination).expanduser().absolute()
        if target == self.path:
            raise MAEPError("backup destination must differ from source")
        if target.exists():
            raise MAEPError("backup destination exists; overwrite is prohibited")
        self._authorize(
            "READ", "memory:database/backup-source",
            [f"memory:task:{task_id}:backup:read"], task_id
        )
        self._authorize(
            "WRITE", f"memory:backup/{target}",
            [f"memory:task:{task_id}:backup:write"], task_id
        )
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._authorize(
            "WRITE", f"memory:backup/{target}",
            [f"memory:task:{task_id}:backup:write"], task_id
        )
        try:
            destination_fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(destination_fd)
        except FileExistsError as exc:
            raise MAEPError("backup destination appeared during creation; refusing overwrite") from exc
        os.chmod(target, 0o600)
        source = self._connect(readonly=True)
        destination_connection = None
        try:
            self._ensure_ready(source)
            destination_connection = sqlite3.connect(
                str(target), timeout=self.timeout_seconds, isolation_level=None
            )
            destination_connection.execute("PRAGMA foreign_keys=ON")
            destination_connection.execute("PRAGMA synchronous=FULL")
            self._authorize(
                "READ", "memory:database/backup-source",
                [f"memory:task:{task_id}:backup:read"], task_id
            )
            self._authorize(
                "WRITE", f"memory:backup/{target}",
                [f"memory:task:{task_id}:backup:write"], task_id
            )
            source.backup(destination_connection)
            self._ensure_ready(destination_connection)
            check = destination_connection.execute("PRAGMA integrity_check").fetchall()
            if [row[0] for row in check] != ["ok"]:
                raise MAEPError("backup integrity validation failed; artifact preserved for diagnosis")
            if destination_connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise MAEPError("backup schema version mismatch; artifact preserved")
            destination_connection.close()
            destination_connection = None
            os.chmod(target, 0o600)
            return {"status": "PASS", "destination": str(target), "integrity_check": "ok"}
        except sqlite3.Error as exc:
            raise MAEPError("backup failed; partial destination preserved and not auto-deleted") from exc
        finally:
            if destination_connection is not None:
                destination_connection.close()
            source.close()

    def restore_to(self, destination, *, task_id, source_path=None):
        """Restore a selected database backup to a new isolated target without overwriting."""
        target = Path(destination).expanduser().absolute()
        source_path = self.path if source_path is None else Path(source_path).expanduser().absolute()
        if target == source_path:
            raise MAEPError("restore target must differ from the selected source")
        if target.exists():
            raise MAEPError("restore target exists; overwrite/production restore is prohibited")
        self._authorize(
            "READ", f"memory:database/restore-source/{source_path}",
            [f"memory:task:{task_id}:restore:read"], task_id
        )
        self._authorize(
            "WRITE", f"memory:restore-target/{target}",
            [f"memory:task:{task_id}:restore:create"], task_id
        )
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            destination_fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(destination_fd)
        except FileExistsError as exc:
            raise MAEPError("restore target appeared during creation; refusing overwrite") from exc
        os.chmod(target, 0o600)
        self._authorize(
            "READ", f"memory:database/restore-source/{source_path}",
            [f"memory:task:{task_id}:restore:read"], task_id
        )
        self._authorize(
            "WRITE", f"memory:restore-target/{target}",
            [f"memory:task:{task_id}:restore:create"], task_id
        )
        source_store = MemoryStore(
            source_path,
            principal_provider=self.principal_provider,
            policy_evaluator=self.policy_evaluator,
            live_state_provider=self.live_state_provider,
            acceptance_provider=self.acceptance_provider,
            applicability_provider=self.applicability_provider,
            execution_mode=self.execution_mode,
            timeout_seconds=self.timeout_seconds,
        )
        source = source_store._connect(readonly=True)
        destination_connection = None
        try:
            source_store._ensure_ready(source)
            destination_connection = sqlite3.connect(
                str(target), timeout=self.timeout_seconds, isolation_level=None
            )
            destination_connection.execute("PRAGMA foreign_keys=ON")
            destination_connection.execute("PRAGMA synchronous=FULL")
            self._authorize(
                "READ", f"memory:database/restore-source/{source_path}",
                [f"memory:task:{task_id}:restore:read"], task_id
            )
            self._authorize(
                "WRITE", f"memory:restore-target/{target}",
                [f"memory:task:{task_id}:restore:create"], task_id
            )
            source.backup(destination_connection)
            source_store._ensure_ready(destination_connection)
            check = destination_connection.execute("PRAGMA integrity_check").fetchall()
            if [row[0] for row in check] != ["ok"]:
                raise MAEPError("restored target integrity check failed; artifact preserved")
            destination_connection.close()
            destination_connection = None
            os.chmod(target, 0o600)
            return {"status": "PASS", "destination": str(target), "integrity_check": "ok"}
        except MAEPError:
            raise
        except sqlite3.Error as exc:
            raise MAEPError("restore to isolated target failed; artifact preserved") from exc
        finally:
            if destination_connection is not None:
                destination_connection.close()
            source.close()


class AuthorityEvidenceReader:
    """Read-only Memory record source for the Native Authority decision path only.

    NativePolicyEngine resolves its MAEP-022 applicability/gate/evidence records from
    Memory while it is deciding. Reading them through MemoryStore's public API asks
    the same engine for permission, which re-enters authorize() without end. This
    reader breaks that cycle: the authority (the decision point) reads the records
    it decides on, without asking itself.

    It is deliberately narrow:
      * read-only: SQLite ``mode=ro`` plus ``PRAGMA query_only=ON`` (via the shared
        MemoryStore read helpers); it has no write methods;
      * same data and integrity checks as the authorized API: each method calls the
        identical MemoryStore read body (schema, policy metadata, full event-chain
        digest validation, row/payload binding), so no logic is duplicated;
      * not a data-plane API: compose it only into the authority's record resolver
        (MemoryMAEPRecordResolver / CanonicalMemoryTaskSelectors). HTTP, Brain and
        adapters keep using MemoryStore, whose access still requires authority;
      * not proof of authority: records it returns must still pass the approved-source
        provenance verifier (D4) before NativePolicyEngine relies on them.
    """

    def __init__(self, db_path, *, timeout_seconds=5.0):
        # Private store with no principal/policy providers in READ_ONLY mode: any
        # attempt to reach a public (authorizing) method on it fails closed.
        self._store = MemoryStore(db_path, execution_mode="READ_ONLY",
                                  timeout_seconds=timeout_seconds)

    @property
    def path(self):
        return self._store.path

    def get_task(self, task_id):
        return self._store._read_task(task_id)

    def get_evidence(self, task_id, evidence_id):
        return self._store._read_evidence(task_id, evidence_id)

    def get_events(self, task_id, *, limit=100):
        return self._store._read_events(task_id, limit=limit)

    def check_integrity(self, *, task_id):
        _require_nonempty(task_id, "task_id")
        return self._store._inspect_integrity()

    def list_tasks(self, *, index_scope_task_id, limit=100, offset=0):
        return self._store._read_task_index(index_scope_task_id, limit=limit, offset=offset)
