"""Fail-closed applicability and MAEP-022 evidence providers.

These adapters do not establish a trust root. They require an owner-approved active
root/policy, a resolver backed by the authoritative evidence store, and a provenance
validator grounded in approved records. MAEP-029/030 prohibit signature features and
independent-review workflows; if allowed provenance cannot be established, operations
remain blocked. Caller-supplied booleans are never accepted as proof.
"""

from __future__ import annotations

from typing import Any, Protocol
import re

from maep.core import MAEPError, validate_capability_evolution_decision
from maep.native_authority import AuthorityError, TrustRootRecord


class TrustedRecordResolver(Protocol):
    def resolve_applicability(self, request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None: ...
    def resolve_gate(self, request: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None: ...
    def resolve_evidence(self, evidence_ref: str) -> dict[str, Any] | None: ...


class ApprovedRecordProvenanceVerifier(Protocol):
    """Validate record provenance against owner-approved sources and current root/policy binding.

    Implementations must not create, request, require, use, or verify digital signatures,
    and must not invoke an independent-review workflow. A missing approved source blocks.
    """
    def validate_record_provenance(self, record: dict[str, Any], *, record_type: str,
                                   root: TrustRootRecord, policy: dict[str, Any]) -> bool: ...


def _active_binding(root_store: Any, policy_provider: Any, expected_policy: dict[str, Any] | None = None):
    root = root_store.load_active()
    if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
        raise AuthorityError("trusted provider blocked: active trust root invalid")
    policy = policy_provider.load_active(root)
    if (not isinstance(policy, dict) or policy.get("status") != "ACTIVE"
            or policy.get("root_generation") != root.generation
            or policy.get("provenance_verified") is not True
            or not isinstance(policy.get("version"), str)
            or not policy.get("version")
            or not isinstance(policy.get("policy_digest"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", policy.get("policy_digest", "")) is None
            or not isinstance(policy.get("approval_evidence_refs"), list)
            or not policy.get("approval_evidence_refs")):
        raise AuthorityError("trusted provider blocked: active policy provenance invalid")
    if expected_policy is not None and (
            expected_policy.get("version") != policy.get("version")
            or expected_policy.get("policy_digest") != policy.get("policy_digest")
            or expected_policy.get("root_generation") != root.generation):
        raise AuthorityError("trusted provider blocked: policy binding changed")
    return root, policy


MEMORY_RESOURCE_PREFIX = "memory:"
_RULE_KEYS = frozenset({"rule_id", "actions", "resource_prefix", "classification"})


def _memory_rule(policy: dict[str, Any], request: dict[str, Any], memory_store_path: str | None):
    """Return the policy applicability rule covering this Memory data-plane request, or None.

    Rules live in the active, provenance-verified policy (owner-approved via D2). They are
    deliberately narrow: they can only classify `memory:` resources as NOT_REQUIRED, and
    only resources bound to the configured Memory store (MemoryStore appends
    " [store:<path>]"). Any malformed, duplicate or overlapping rule set blocks.
    """
    rules = policy.get("applicability_rules")
    if rules is None:
        return None
    if not isinstance(rules, list):
        raise AuthorityError("policy applicability rules are malformed")
    seen, matches = set(), []
    action, resource = request.get("action"), request.get("resource")
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != _RULE_KEYS:
            raise AuthorityError("policy applicability rule has unknown or missing fields")
        rule_id, actions, prefix = rule["rule_id"], rule["actions"], rule["resource_prefix"]
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen:
            raise AuthorityError("policy applicability rule identity is invalid or duplicated")
        seen.add(rule_id)
        if (not isinstance(actions, list) or not actions or len(actions) != len(set(actions))
                or any(not isinstance(item, str) or not item.strip() for item in actions)):
            raise AuthorityError("policy applicability rule actions are invalid")
        if not isinstance(prefix, str) or not prefix.startswith(MEMORY_RESOURCE_PREFIX):
            raise AuthorityError("policy applicability rules may only cover memory: resources")
        if rule["classification"] != "NOT_REQUIRED":
            raise AuthorityError("policy applicability rules may only declare NOT_REQUIRED")
        if (memory_store_path and isinstance(resource, str) and resource.startswith(prefix)
                and resource.endswith(f" [store:{memory_store_path}]") and action in actions):
            matches.append(rule)
    if len(matches) > 1:
        raise AuthorityError("policy applicability rules overlap for this request")
    return matches[0] if matches else None


def _rule_applicability(rule: dict[str, Any], request: dict[str, Any], candidate: dict[str, Any],
                        policy: dict[str, Any]) -> dict[str, Any]:
    return {"verified": True, "classification": "NOT_REQUIRED",
            "candidate_ref": candidate["candidate_ref"], "action": request["action"],
            "resource": request["resource"], "applicability_id": "policy-rule:" + rule["rule_id"],
            "rule_version": policy["version"],
            "facts_used": ["policy:" + policy["policy_digest"], "rule:" + rule["rule_id"],
                           "resource-class:memory-data-plane"],
            "evidence_refs": list(policy["approval_evidence_refs"])}


def _verify(verifier: ApprovedRecordProvenanceVerifier, record: Any, *, record_type: str,
            root: TrustRootRecord, policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise AuthorityError("trusted provider blocked: authoritative record missing")
    try:
        verified = verifier.validate_record_provenance(
            record, record_type=record_type, root=root, policy=policy)
    except Exception as exc:
        raise AuthorityError("trusted provider blocked: provenance validation failed") from exc
    if verified is not True:
        raise AuthorityError("trusted provider blocked: authoritative record provenance unverified")
    return record


def _resolve_verified_evidence(resolver: TrustedRecordResolver, verifier: ApprovedRecordProvenanceVerifier,
                               refs: Any, *, candidate_ref: str, root: TrustRootRecord,
                               policy: dict[str, Any], record_type: str) -> dict[str, dict[str, Any]]:
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise AuthorityError("trusted provider blocked: evidence references missing")
    resolved: dict[str, dict[str, Any]] = {}
    for ref in refs:
        record = resolver.resolve_evidence(ref)
        _verify(verifier, record, record_type=record_type, root=root, policy=policy)
        if record.get("evidence_id") != ref or record.get("candidate_ref") != candidate_ref:
            raise AuthorityError("trusted provider blocked: evidence reference/candidate mismatch")
        resolved[ref] = record
    return resolved


class TrustedApplicabilityProvider:
    """Resolve applicability by request/candidate, then validate authoritative provenance."""
    def __init__(self, *, root_store: Any, policy_provider: Any,
                 resolver: TrustedRecordResolver, verifier: ApprovedRecordProvenanceVerifier,
                 memory_store_path: str | None = None):
        if any(value is None for value in (root_store, policy_provider, resolver, verifier)):
            raise AuthorityError("trusted applicability provider requires root, policy, resolver and verifier")
        # Policy applicability rules only ever apply to resources bound to this store.
        self.memory_store_path = str(memory_store_path) if memory_store_path else None
        if not callable(getattr(resolver, "resolve_applicability", None)) or not callable(getattr(resolver, "resolve_evidence", None)):
            raise AuthorityError("trusted applicability resolver contract incomplete")
        if not callable(getattr(verifier, "validate_record_provenance", None)):
            raise AuthorityError("approved applicability provenance validator contract incomplete")
        self.root_store, self.policy_provider = root_store, policy_provider
        self.resolver, self.verifier = resolver, verifier

    def classify(self, request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
        root, policy = _active_binding(self.root_store, self.policy_provider)
        rule = _memory_rule(policy, request, self.memory_store_path)
        # Lookup errors propagate (never converted into a rule decision); only the
        # absence of a task-level record lets the policy rule decide.
        record = self.resolver.resolve_applicability(request, candidate)
        if record is None and rule is not None:
            return _rule_applicability(rule, request, candidate, policy)
        _verify(self.verifier, record, record_type="MAEP022_APPLICABILITY", root=root, policy=policy)
        expected = (candidate.get("candidate_ref"), request.get("action"), request.get("resource"))
        observed = (record.get("candidate_ref"), record.get("action"), record.get("resource"))
        if observed != expected:
            if rule is not None:
                # The task's approved record classifies another operation; this Memory
                # data-plane request is classified by the owner-approved policy rule.
                return _rule_applicability(rule, request, candidate, policy)
            raise AuthorityError("trusted applicability record does not bind candidate/action/resource")
        if record.get("classification") not in {"REQUIRED", "NOT_REQUIRED"}:
            raise AuthorityError("trusted applicability classification is unknown")
        facts = record.get("facts_used")
        refs = record.get("evidence_refs")
        if not isinstance(facts, list) or not facts or not isinstance(refs, list) or not refs:
            raise AuthorityError("trusted applicability facts/evidence missing")
        _resolve_verified_evidence(self.resolver, self.verifier, refs,
            candidate_ref=candidate["candidate_ref"], root=root, policy=policy,
            record_type="MAEP022_APPLICABILITY_EVIDENCE")
        if not isinstance(record.get("rule_version"), str) or not record["rule_version"]:
            raise AuthorityError("trusted applicability rule version missing")
        if not isinstance(record.get("applicability_id"), str) or not record["applicability_id"]:
            raise AuthorityError("trusted applicability identity missing")
        return {"verified": True, "classification": record["classification"],
                "candidate_ref": candidate["candidate_ref"], "action": request["action"],
                "resource": request["resource"], "applicability_id": record["applicability_id"],
                "rule_version": record["rule_version"], "facts_used": list(facts),
                "evidence_refs": list(refs)}


class TrustedGateEvidenceProvider:
    """Resolve authoritative provenance and canonically validate candidate-bound MAEP-022 evidence."""
    def __init__(self, *, root_store: Any, policy_provider: Any,
                 resolver: TrustedRecordResolver, verifier: ApprovedRecordProvenanceVerifier):
        if any(value is None for value in (root_store, policy_provider, resolver, verifier)):
            raise AuthorityError("trusted gate provider requires root, policy, resolver and verifier")
        if not callable(getattr(resolver, "resolve_gate", None)) or not callable(getattr(resolver, "resolve_evidence", None)):
            raise AuthorityError("trusted gate resolver contract incomplete")
        if not callable(getattr(verifier, "validate_record_provenance", None)):
            raise AuthorityError("approved gate provenance validator contract incomplete")
        self.root_store, self.policy_provider = root_store, policy_provider
        self.resolver, self.verifier = resolver, verifier

    def evaluate(self, request: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
        root, active_policy = _active_binding(self.root_store, self.policy_provider, policy)
        record = self.resolver.resolve_gate(request, candidate, active_policy)
        _verify(self.verifier, record, record_type="MAEP022_GATE_DECISION", root=root, policy=active_policy)
        candidate_ref = candidate.get("candidate_ref")
        if record.get("candidate_ref") != candidate_ref or record.get("policy_version") != active_policy.get("version"):
            raise AuthorityError("trusted gate record candidate/policy mismatch")
        if record.get("gate_status") != "PASS":
            return {"status": "BLOCKED", "verified": True, "evidence_verified": False,
                    "candidate_ref": candidate_ref, "policy_version": active_policy["version"],
                    "gate_id": record.get("decision_id"), "evidence_refs": []}
        refs = []
        for field in ("inventory_evidence_refs", "comparison_evidence_refs", "impact_analysis_refs", "regression_test_refs"):
            values = record.get(field)
            if not isinstance(values, list) or not values:
                raise AuthorityError("trusted gate decision lacks mandatory evidence references")
            refs.extend(values)
        if record.get("decision") in {"CONSOLIDATE_KEEP_SUPERIOR", "DEPRECATE_OBSOLETE"}:
            for field in ("retirement_authorization_ref", "recovery_plan_ref"):
                value = record.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise AuthorityError("trusted retirement gate lacks authorization/recovery evidence")
                refs.append(value)
        if record.get("decision") == "DEPRECATE_OBSOLETE":
            values = record.get("obsolescence_evidence_refs")
            if not isinstance(values, list) or not values:
                raise AuthorityError("trusted deprecation gate lacks obsolescence evidence")
            refs.extend(values)
        refs = list(dict.fromkeys(refs))
        evidence_by_id = _resolve_verified_evidence(self.resolver, self.verifier, refs,
            candidate_ref=candidate_ref, root=root, policy=active_policy,
            record_type="MAEP022_GATE_EVIDENCE")
        try:
            validate_capability_evolution_decision(record, evidence_by_id=evidence_by_id,
                candidate_ref=candidate_ref, policy_version=active_policy["version"])
        except (MAEPError, ValueError, TypeError) as exc:
            raise AuthorityError("trusted gate decision failed canonical MAEP validation") from exc
        return {"status": "PASS", "verified": True, "evidence_verified": True,
                "candidate_ref": candidate_ref, "policy_version": active_policy["version"],
                "gate_id": record.get("decision_id"), "evidence_refs": sorted(set(refs)),
                "record": record, "evidence_by_id": evidence_by_id}
