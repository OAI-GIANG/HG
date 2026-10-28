"""Native authority primitives for HG.

This module deliberately provides no implicit production bootstrap or permissive
provider defaults. Providers are trust-boundary dependencies and must be composed
by an explicitly reviewed runtime root. Standard-library only.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Protocol

from maep.core import MAEPError, validate_capability_evolution_decision
from maep.policy_templates import (
    POLICY_SCHEMA_V2, PolicyTemplateError, policy_rule_matches_v2,
    resource_grant_matches, scope_grants_cover, validate_effective_policy_v2,
)

# True while NativePolicyEngine.authorize() is evaluating in the current execution
# context (thread / asyncio task). A decision cannot depend on another decision of
# the authority itself: providers must read verified records, never ask authorize()
# again. Module-level by design (ContextVars must not be created per instance).
_AUTHORIZATION_ACTIVE: ContextVar[bool] = ContextVar("hg_native_authorization_active", default=False)


class AuthorityError(RuntimeError):
    """A required authority condition is missing, invalid, stale, or untrusted."""


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    BLOCKED = "BLOCKED"


class BootstrapState(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
    ACTIVE = "ACTIVE"
    ROTATION_PENDING = "ROTATION_PENDING"
    QUARANTINED = "QUARANTINED"
    BLOCKED = "BLOCKED"


class Applicability(str, Enum):
    REQUIRED = "REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    """Canonical JSON for digests; duplicate keys must be rejected at load time."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_digest(value: Any) -> str:
    try:
        return _digest(value)
    except Exception:
        label = type(value).__module__ + "." + type(value).__qualname__
        return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_time(value: Any) -> datetime:
    if not _nonempty(value):
        raise AuthorityError("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise AuthorityError("invalid timestamp") from None
    if parsed.tzinfo is None:
        raise AuthorityError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityError("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class TrustRootRecord:
    schema_version: str
    root_id: str
    generation: int
    status: str
    created_at: str
    bootstrap_authorization_ref: str
    verification_method: str
    verification_material_ref: str
    previous_root_digest: str | None
    policy_change_rule_ref: str
    record_digest: str
    evidence_ref: str

    @classmethod
    def create(cls, *, root_id: str, generation: int, created_at: str,
               bootstrap_authorization_ref: str, verification_method: str,
               verification_material_ref: str, policy_change_rule_ref: str,
               evidence_ref: str, previous_root_digest: str | None = None):
        fields = {
            "schema_version": "hg.trust-root.v1",
            "root_id": root_id,
            "generation": generation,
            "status": BootstrapState.ACTIVE.value,
            "created_at": created_at,
            "bootstrap_authorization_ref": bootstrap_authorization_ref,
            "verification_method": verification_method,
            "verification_material_ref": verification_material_ref,
            "previous_root_digest": previous_root_digest,
            "policy_change_rule_ref": policy_change_rule_ref,
            "evidence_ref": evidence_ref,
        }
        if not _nonempty(root_id) or not isinstance(generation, int) or generation < 1:
            raise AuthorityError("invalid trust-root identity/generation")
        for key in ("created_at", "bootstrap_authorization_ref", "verification_method",
                    "verification_material_ref", "policy_change_rule_ref", "evidence_ref"):
            if not _nonempty(fields[key]):
                raise AuthorityError("missing trust-root field: " + key)
        _parse_time(created_at)
        fields["record_digest"] = _digest(fields)
        return cls(**fields)

    def verify_integrity(self) -> bool:
        fields = asdict(self)
        claimed = fields.pop("record_digest")
        if self.schema_version != "hg.trust-root.v1" or self.status != BootstrapState.ACTIVE.value:
            return False
        if not isinstance(self.generation, int) or self.generation < 1 or not _nonempty(self.root_id):
            return False
        if self.generation == 1 and self.previous_root_digest is not None:
            return False
        if self.generation > 1 and not _nonempty(self.previous_root_digest):
            return False
        for name in ("bootstrap_authorization_ref", "verification_method",
                     "verification_material_ref", "policy_change_rule_ref", "evidence_ref"):
            if not _nonempty(getattr(self, name)):
                return False
        try:
            _parse_time(self.created_at)
        except AuthorityError:
            return False
        return claimed == _digest(fields)


class OwnerApprovalVerifier(Protocol):
    """Validate explicit owner-controlled bootstrap approval from an approved source.

    This is an authorization check, not an independent-review workflow. Implementations
    must not introduce signature features; unverifiable approval must block bootstrap.
    """
    def validate_owner_approval(self, canonical_payload: bytes, approval: Any) -> bool: ...


class RootStore(Protocol):
    def load_active(self) -> TrustRootRecord | None: ...
    def store_active(self, record: TrustRootRecord) -> None: ...


class PrincipalProvider(Protocol):
    def resolve(self, authenticated_context: Any) -> dict[str, Any] | None: ...


class CandidateProvider(Protocol):
    def inspect(self, target: Any) -> dict[str, Any] | None: ...


class PolicyProvider(Protocol):
    def load_active(self, root: TrustRootRecord) -> dict[str, Any] | None: ...


class ApplicabilityProvider(Protocol):
    def classify(self, request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None: ...


class GateProvider(Protocol):
    def evaluate(self, request: dict[str, Any], candidate: dict[str, Any],
                 policy: dict[str, Any]) -> dict[str, Any] | None: ...


class EvidenceSink(Protocol):
    def append(self, event: dict[str, Any]) -> str: ...


class TrustRootManager:
    """Bootstrap is explicit; construction and imports never create a root."""

    def __init__(self, store: RootStore, verifier: OwnerApprovalVerifier, evidence_sink):
        if store is None or verifier is None or evidence_sink is None:
            raise AuthorityError("bootstrap store, owner-approval verifier and durable evidence sink are required")
        if not callable(getattr(evidence_sink, "append", None)):
            raise AuthorityError("bootstrap evidence sink contract is incomplete")
        self._store = store
        self._verifier = verifier
        self._evidence_sink = evidence_sink

    def bootstrap(self, payload: dict[str, Any], approval: Any) -> TrustRootRecord:
        if self._store.load_active() is not None:
            raise AuthorityError("active root already exists; use governed rotation")
        if not isinstance(payload, dict):
            raise AuthorityError("bootstrap payload must be an object")
        allowed = {"root_id", "generation", "created_at", "bootstrap_authorization_ref",
                   "verification_method", "verification_material_ref", "policy_change_rule_ref",
                   "previous_root_digest"}
        if set(payload) != allowed:
            raise AuthorityError("bootstrap payload fields are incomplete or unknown")
        if not _nonempty(payload.get("root_id")) or payload.get("generation") != 1:
            raise AuthorityError("first root must have a root_id and generation 1")
        if payload.get("previous_root_digest") is not None:
            raise AuthorityError("first root cannot reference a previous root")
        canonical = _canonical_bytes(payload)
        try:
            approved = self._verifier.validate_owner_approval(canonical, approval)
        except Exception as exc:
            raise AuthorityError("bootstrap approval verification failed") from exc
        if approved is not True:
            raise AuthorityError("bootstrap owner approval not verified")
        event = {
            "event_type": "trust_root.bootstrap.approved",
            "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
            "payload_digest": _digest(payload),
        }
        try:
            evidence_ref = self._evidence_sink.append(event)
        except Exception as exc:
            raise AuthorityError("bootstrap evidence was not durably recorded") from exc
        if not _nonempty(evidence_ref):
            raise AuthorityError("bootstrap evidence was not durably recorded")
        record = TrustRootRecord.create(**payload, evidence_ref=evidence_ref)
        self._store.store_active(record)
        read_back = self._store.load_active()
        if not isinstance(read_back, TrustRootRecord) or not read_back.verify_integrity():
            raise AuthorityError("trust-root read-back/integrity verification failed")
        if read_back.record_digest != record.record_digest:
            raise AuthorityError("trust-root read-back mismatch")
        return read_back


@dataclass(frozen=True)
class AuthorizationResult:
    decision: Decision
    reason_codes: tuple[str, ...]
    principal_ref: str | None = None
    action: str | None = None
    resource: str | None = None
    task_ref: str | None = None
    candidate_ref: str | None = None
    root_generation: int | None = None
    root_digest: str | None = None
    policy_version: str | None = None
    policy_digest: str | None = None
    applicability_ref: str | None = None
    applicability_classification: str | None = None
    gate_ref: str | None = None
    gate_verified: bool = False
    gate_evidence_refs: tuple[str, ...] = ()
    issued_at: str | None = None
    expires_at: str | None = None
    request_digest: str | None = None
    decision_digest: str | None = None

    def as_record(self) -> dict[str, Any]:
        result = asdict(self)
        result["decision"] = self.decision.value
        result["reason_codes"] = list(self.reason_codes)
        return result


class NativePolicyEngine:
    """Fail-closed evaluator. It consumes verified provider records, not caller booleans."""

    def __init__(self, *, root_store: RootStore, principal_provider: PrincipalProvider,
                 candidate_provider: CandidateProvider, policy_provider: PolicyProvider,
                 applicability_provider: ApplicabilityProvider, gate_provider: GateProvider,
                 evidence_sink: EvidenceSink):
        dependencies = (root_store, principal_provider, candidate_provider, policy_provider,
                        applicability_provider, gate_provider, evidence_sink)
        if any(item is None for item in dependencies):
            raise AuthorityError("all production authority providers are mandatory")
        self.root_store = root_store
        self.principal_provider = principal_provider
        self.candidate_provider = candidate_provider
        self.policy_provider = policy_provider
        self.applicability_provider = applicability_provider
        self.gate_provider = gate_provider
        self.evidence_sink = evidence_sink

    def authorize(self, request: dict[str, Any], *, authenticated_context: Any,
                  candidate_target: Any, now: datetime | None = None) -> AuthorizationResult:
        if _AUTHORIZATION_ACTIVE.get():
            # A provider reached authorize() while a decision is being evaluated (for
            # example by reading Memory through its authorizing API). Refuse before any
            # provider runs; the enclosing evaluation then fails closed on its own.
            return self._blocked("AUTHORITY_REENTRANT_EVALUATION",
                                 request=request if isinstance(request, dict) else {})
        token = _AUTHORIZATION_ACTIVE.set(True)
        try:
            return self._evaluate(request, authenticated_context=authenticated_context,
                                  candidate_target=candidate_target, now=now)
        finally:
            _AUTHORIZATION_ACTIVE.reset(token)

    def _evaluate(self, request: dict[str, Any], *, authenticated_context: Any,
                  candidate_target: Any, now: datetime | None) -> AuthorizationResult:
        now = now or datetime.now(timezone.utc)
        now = now.astimezone(timezone.utc)
        if not isinstance(request, dict):
            return self._blocked("INVALID_REQUEST", request={})
        try:
            root = self.root_store.load_active()
            if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
                return self._blocked("MISSING_OR_INVALID_TRUST_ROOT", request=request)
            principal = self.principal_provider.resolve(authenticated_context)
            if (not isinstance(principal, dict) or principal.get("status") != "ACTIVE"
                    or principal.get("verified") is not True
                    or not _nonempty(principal.get("identity_evidence_ref"))):
                return self._blocked("IDENTITY_UNVERIFIED", request=request, root=root)
            if not _nonempty(principal.get("principal_id")):
                return self._blocked("PRINCIPAL_ID_INVALID", request=request, root=root)
            if principal.get("revoked") is True:
                return self._blocked("PRINCIPAL_REVOKED", request=request, root=root, principal=principal)
            if principal.get("expires_at") is not None and _parse_time(principal.get("expires_at")) <= now:
                return self._blocked("PRINCIPAL_EXPIRED", request=request, root=root, principal=principal)
            candidate = self.candidate_provider.inspect(candidate_target)
            if (not isinstance(candidate, dict) or candidate.get("verified") is not True
                    or candidate.get("repository") != "OAI-GIANG/HG"
                    or not _valid_digest(candidate.get("source_manifest_digest"))):
                return self._blocked("CANDIDATE_UNVERIFIED", request=request, root=root, principal=principal)
            candidate_ref = candidate.get("candidate_ref")
            if not _nonempty(candidate_ref):
                return self._blocked("CANDIDATE_ID_MISSING", request=request, root=root, principal=principal)
            if request.get("candidate_ref") is not None and request.get("candidate_ref") != candidate_ref:
                return self._blocked("REQUEST_CANDIDATE_MISMATCH", request=request, root=root, principal=principal, candidate=candidate)
            policy = self.policy_provider.load_active(root)
            if not isinstance(policy, dict) or policy.get("status") != "ACTIVE":
                return self._blocked("POLICY_UNVERIFIED", request=request, root=root, principal=principal, candidate=candidate)
            policy_schema = policy.get("schema_version")
            if policy_schema not in (None, "hg.policy.v1", POLICY_SCHEMA_V2):
                return self._blocked("POLICY_SCHEMA_UNSUPPORTED", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            policy_v2 = policy_schema == POLICY_SCHEMA_V2
            if policy_v2:
                try:
                    validate_effective_policy_v2(policy, expected_root_generation=root.generation)
                except PolicyTemplateError:
                    return self._blocked("POLICY_SCHEMA_INVALID", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            policy_version = policy.get("version")
            if not _nonempty(policy_version):
                return self._blocked("POLICY_VERSION_MISSING", request=request, root=root, principal=principal, candidate=candidate)
            if policy.get("root_generation") != root.generation:
                return self._blocked("POLICY_ROOT_GENERATION_MISMATCH", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            if (policy.get("provenance_verified") is not True
                    or not _valid_digest(policy.get("policy_digest"))
                    or not isinstance(policy.get("approval_evidence_refs"), list)
                    or not policy.get("approval_evidence_refs")):
                return self._blocked("POLICY_PROVENANCE_UNVERIFIED", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            applicability = self.applicability_provider.classify(request, candidate)
            if (not isinstance(applicability, dict) or applicability.get("verified") is not True
                    or not _nonempty(applicability.get("rule_version"))
                    or not isinstance(applicability.get("facts_used"), list)
                    or not applicability.get("facts_used")
                    or not isinstance(applicability.get("evidence_refs"), list)
                    or not applicability.get("evidence_refs")):
                return self._blocked("APPLICABILITY_UNVERIFIED", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            if applicability.get("candidate_ref") != candidate_ref:
                return self._blocked("APPLICABILITY_CANDIDATE_MISMATCH", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            if applicability.get("action") != request.get("action") or applicability.get("resource") != request.get("resource"):
                return self._blocked("APPLICABILITY_REQUEST_MISMATCH", request=request, root=root, principal=principal, candidate=candidate, policy=policy)
            classification = applicability.get("classification")
            if classification not in {Applicability.REQUIRED.value, Applicability.NOT_REQUIRED.value}:
                # Unknown applicability is blocked before invoking the MAEP-022 gate.
                # The gate is conditional policy, not a fallback for missing classification.
                return self._blocked("APPLICABILITY_UNKNOWN", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability)
            gate = None
            if classification == Applicability.REQUIRED.value:
                gate = self.gate_provider.evaluate(request, candidate, policy)
                if (not isinstance(gate, dict) or gate.get("status") != "PASS"
                        or gate.get("verified") is not True or gate.get("evidence_verified") is not True
                        or not _nonempty(gate.get("gate_id"))
                        or not isinstance(gate.get("evidence_refs"), list) or not gate.get("evidence_refs")):
                    return self._blocked("MAEP022_GATE_NOT_PASSED", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
                if gate.get("candidate_ref") != candidate_ref or gate.get("policy_version") != policy_version:
                    return self._blocked("MAEP022_GATE_STALE_OR_MISMATCHED", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
                # MAEP-022 has one canonical validator in maep.core. Native Authority
                # must validate the actual decision record and resolved evidence, not
                # accept a provider's PASS boolean as a substitute for the policy.
                gate_record = gate.get("record")
                gate_evidence = gate.get("evidence_by_id")
                if not isinstance(gate_record, dict) or not isinstance(gate_evidence, dict):
                    return self._blocked("MAEP022_CANONICAL_RECORD_MISSING", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
                try:
                    validate_capability_evolution_decision(
                        gate_record, evidence_by_id=gate_evidence,
                        candidate_ref=candidate_ref, policy_version=policy_version,
                    )
                except MAEPError:
                    return self._blocked("MAEP022_CANONICAL_VALIDATION_FAILED", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
            action, resource, task_ref = request.get("action"), request.get("resource"), request.get("task_ref")
            if not all(_nonempty(v) for v in (action, resource, task_ref)):
                return self._blocked("REQUEST_SCOPE_INCOMPLETE", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
            capabilities = principal.get("capabilities")
            resource_scopes = principal.get("resource_scopes")
            requested_scopes = request.get("scope")
            principal_scopes = principal.get("allowed_scopes")
            request_scopes_valid = (isinstance(requested_scopes, list) and bool(requested_scopes)
                                    and all(_nonempty(item) for item in requested_scopes))
            if policy_v2:
                resource_scope_allowed = resource_grant_matches(
                    resource_scopes, resource, task_ref, templates_allowed=True)
                principal_scope_allowed = scope_grants_cover(
                    requested_scopes, principal_scopes, task_ref, templates_allowed=True)
            else:
                resource_scope_allowed = isinstance(resource_scopes, list) and resource in resource_scopes
                principal_scope_allowed = (isinstance(principal_scopes, list) and request_scopes_valid
                                           and set(requested_scopes).issubset(set(principal_scopes)))
            if (not isinstance(capabilities, list) or action not in capabilities
                    or not resource_scope_allowed or not request_scopes_valid
                    or not principal_scope_allowed):
                return self._deny("PRINCIPAL_SCOPE_DENIED", request, root, principal, candidate, policy, applicability, gate)
            rules = policy.get("rules")
            if policy_v2:
                matching_rules = [
                    rule for rule in rules if policy_rule_matches_v2(
                        rule, action=action, resource=resource, requested_scopes=requested_scopes,
                        task_ref=task_ref)
                ] if isinstance(rules, list) else []
            else:
                matching_rules = [
                    rule for rule in rules if isinstance(rule, dict)
                    and rule.get("action") == action and rule.get("resource") == resource
                    and isinstance(rule.get("scope"), list)
                    and set(requested_scopes).issubset(set(rule.get("scope", [])))
                ] if isinstance(rules, list) else []
            # Explicit DENY takes precedence over any overlapping ALLOW rule.
            if (not matching_rules
                    or any(rule.get("effect") == "DENY" for rule in matching_rules)
                    or not any(rule.get("effect") == "ALLOW" for rule in matching_rules)):
                return self._deny("POLICY_DENIED", request, root, principal, candidate, policy, applicability, gate)
            ttl = policy.get("grant_ttl_seconds")
            if not isinstance(ttl, int) or ttl < 1 or ttl > 300:
                return self._blocked("INVALID_POLICY_GRANT_TTL", request=request, root=root, principal=principal, candidate=candidate, policy=policy, applicability=applicability, gate=gate)
            issued_at = now.isoformat().replace("+00:00", "Z")
            expires_at = datetime.fromtimestamp(now.timestamp() + ttl, timezone.utc).isoformat().replace("+00:00", "Z")
            base = {
                "decision": "ALLOW", "principal_ref": principal["principal_id"],
                "action": action, "resource": resource, "task_ref": task_ref,
                "candidate_ref": candidate_ref, "root_generation": root.generation,
                "root_digest": root.record_digest, "policy_version": policy_version,
                "policy_digest": policy.get("policy_digest"),
                "applicability_ref": applicability.get("applicability_id"),
                "applicability_classification": applicability.get("classification"),
                "gate_ref": None if gate is None else gate.get("gate_id"),
                "gate_verified": gate is not None,
                "gate_evidence_refs": [] if gate is None else list(gate.get("evidence_refs", [])),
                "issued_at": issued_at, "expires_at": expires_at,
                "request_digest": _digest(request),
            }
            result = AuthorizationResult(
                decision=Decision.ALLOW, reason_codes=("AUTHORIZED",),
                principal_ref=base["principal_ref"], action=action, resource=resource,
                task_ref=task_ref, candidate_ref=candidate_ref,
                root_generation=root.generation, root_digest=root.record_digest,
                policy_version=policy_version, policy_digest=policy.get("policy_digest"),
                applicability_ref=base["applicability_ref"],
                applicability_classification=applicability.get("classification"),
                gate_ref=base["gate_ref"], gate_verified=base["gate_verified"],
                gate_evidence_refs=tuple(base["gate_evidence_refs"]),
                issued_at=issued_at, expires_at=expires_at,
                request_digest=base["request_digest"], decision_digest=_digest(base),
            )
            self._append("authorization.decision", result.as_record())
            return result
        except AuthorityError:
            return self._blocked("AUTHORITY_VALIDATION_FAILED", request=request)
        except Exception:
            # Provider exceptions and storage failures never degrade into ALLOW.
            return self._blocked("AUTHORITY_PROVIDER_OR_EVIDENCE_FAILURE", request=request)

    def recheck_before_effect(self, result: AuthorizationResult, *, request: dict[str, Any],
                              current_candidate_ref: str, current_root_generation: int,
                              current_root_digest: str, current_policy_version: str,
                              current_policy_digest: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if not isinstance(result, AuthorizationResult) or result.decision is not Decision.ALLOW:
            raise AuthorityError("no effect-capable authorization")
        if _parse_time(result.expires_at) <= now.astimezone(timezone.utc):
            raise AuthorityError("authorization grant expired")
        if result.request_digest != _digest(request):
            raise AuthorityError("request changed after authorization")
        if result.candidate_ref != current_candidate_ref:
            raise AuthorityError("candidate changed after authorization")
        if result.root_generation != current_root_generation or result.root_digest != current_root_digest:
            raise AuthorityError("trust root changed after authorization")
        if result.policy_version != current_policy_version or result.policy_digest != current_policy_digest:
            raise AuthorityError("policy changed after authorization")
        return True

    def _append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
            "payload_digest": _digest(payload),
        }
        ref = self.evidence_sink.append(event)
        if not _nonempty(ref):
            raise AuthorityError("durable evidence reference missing")

    def _blocked(self, reason, *, request, root=None, principal=None, candidate=None,
                 policy=None, applicability=None, gate=None):
        return self._record_nonallow(Decision.BLOCKED, reason, request, root, principal, candidate, policy, applicability, gate)

    def _deny(self, reason, request, root, principal, candidate, policy, applicability, gate):
        return self._record_nonallow(Decision.DENY, reason, request, root, principal, candidate, policy, applicability, gate)

    def _record_nonallow(self, decision, reason, request, root, principal, candidate, policy, applicability, gate):
        record = {
            "decision": decision.value, "reason_codes": [reason],
            "principal_ref": None if principal is None else principal.get("principal_id"),
            "action": request.get("action"), "resource": request.get("resource"),
            "task_ref": request.get("task_ref"),
            "candidate_ref": None if candidate is None else candidate.get("candidate_ref"),
            "root_generation": None if root is None else root.generation,
            "root_digest": None if root is None else root.record_digest,
            "policy_version": None if policy is None else policy.get("version"),
            "policy_digest": None if policy is None else policy.get("policy_digest"),
            "applicability_ref": None if applicability is None else applicability.get("applicability_id"),
            "applicability_classification": None if applicability is None else applicability.get("classification"),
            "gate_ref": None if gate is None else gate.get("gate_id"),
            "request_digest": _safe_digest(request),
            "issued_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        try:
            self._append("authorization." + decision.value.lower(), record)
        except Exception:
            # The caller still receives BLOCKED/DENY. Side-effect boundary must reject it.
            pass
        return AuthorizationResult(
            decision=decision, reason_codes=(reason,),
            principal_ref=record["principal_ref"], action=record["action"],
            resource=record["resource"], task_ref=record["task_ref"],
            candidate_ref=record["candidate_ref"], root_generation=record["root_generation"],
            root_digest=record["root_digest"], policy_version=record["policy_version"],
            policy_digest=record["policy_digest"], applicability_ref=record["applicability_ref"],
            applicability_classification=record["applicability_classification"],
            gate_ref=record["gate_ref"], issued_at=record["issued_at"],
            request_digest=record["request_digest"], decision_digest=_digest(record),
        )


class RecoveryManager:
    """Pure recovery decisions; never grants authority or blindly retries."""

    @staticmethod
    def classify_outcome(*, outcome: str, action_idempotent: bool,
                         live_state_reconciled: bool) -> str:
        if outcome not in {item.value for item in Outcome}:
            raise AuthorityError("unknown effect outcome")
        if outcome == Outcome.SUCCESS.value:
            return "VERIFY_RECEIPT"
        if outcome == Outcome.FAILURE.value and action_idempotent is True:
            return "RETRY_ONLY_AFTER_FRESH_AUTHORIZATION"
        if outcome == Outcome.UNKNOWN.value:
            return "RECONCILIATION_REQUIRED" if live_state_reconciled is not True else "FRESH_AUTHORIZATION_REQUIRED"
        return "RECONCILIATION_REQUIRED"


def load_json_strict(path) -> dict[str, Any]:
    """Strict UTF-8 JSON loader rejecting duplicate keys and non-object top-level data."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_reject_duplicate_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(AuthorityError("invalid JSON constant")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityError("authority record unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise AuthorityError("authority record must be a JSON object")
    return value
