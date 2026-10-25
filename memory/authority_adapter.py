"""Adapter binding MemoryStore's legacy MAEP seam to NativePolicyEngine.

The adapter is not a trust root. All providers and the engine must be constructed
by the reviewed runtime composition root. Missing candidate identity fails closed.
"""
import hashlib
import json
from threading import RLock

from maep.core import MAEPError
from maep.native_authority import Decision, NativePolicyEngine, TrustRootRecord


class MemoryNativeAuthorityAdapter:
    def __init__(self, *, engine: NativePolicyEngine, authenticated_context_provider,
                 candidate_target_provider):
        if engine is None or not callable(authenticated_context_provider) or not callable(candidate_target_provider):
            raise MAEPError("native Memory authority requires engine, authenticated context and candidate providers")
        self.engine = engine
        self.authenticated_context_provider = authenticated_context_provider
        self.candidate_target_provider = candidate_target_provider
        self._decisions = {}
        self._lock = RLock()

    @staticmethod
    def _key(request):
        fields = {key: request.get(key) for key in (
            "principal", "action", "resource", "scope", "task_id", "policy_version", "candidate_ref"
        )}
        raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def policy_evaluator(self, request):
        if not isinstance(request, dict) or not request.get("candidate_ref"):
            raise MAEPError("BLOCKED: Memory action requires exact candidate identity")
        try:
            context = self.authenticated_context_provider()
            target = self.candidate_target_provider(request)
            native_request = {
                "action": request.get("action"),
                "resource": request.get("resource"),
                "scope": request.get("scope"),
                "task_ref": request.get("task_id"),
                "candidate_ref": request.get("candidate_ref"),
            }
            result = self.engine.authorize(
                native_request, authenticated_context=context, candidate_target=target
            )
        except Exception as exc:
            raise MAEPError("BLOCKED: native Memory authority evaluation failed") from exc
        if result.decision is not Decision.ALLOW:
            raise MAEPError("BLOCKED: native authority denied Memory action: " + ",".join(result.reason_codes))
        if result.policy_version != request.get("policy_version"):
            raise MAEPError("BLOCKED: active policy version differs from Memory contract")
        if result.principal_ref != request.get("principal"):
            raise MAEPError("BLOCKED: native principal differs from Memory runtime identity")
        grant = {
            "authorization_id": result.decision_digest,
            "principal": result.principal_ref,
            "action": result.action,
            "resource": result.resource,
            "scope": list(request["scope"]),
            "conditions": [],
            "task_id": request["task_id"],
            "policy_version": result.policy_version,
            "decision": "ALLOW",
            "issued_at": result.issued_at,
            "expires_at": result.expires_at,
        }
        with self._lock:
            self._decisions[self._key(request)] = result
        return {"grant": grant, "trusted_policy_allow": True, "satisfied_conditions": []}

    def applicability_provider(self, request):
        key = self._key(request)
        with self._lock:
            result = self._decisions.get(key)
        if result is None or result.decision is not Decision.ALLOW:
            raise MAEPError("BLOCKED: no matching native authority decision")
        if result.candidate_ref != request.get("candidate_ref"):
            raise MAEPError("BLOCKED: native applicability candidate mismatch")
        classification = result.applicability_classification
        if classification not in {"REQUIRED", "NOT_REQUIRED"}:
            raise MAEPError("BLOCKED: applicability is unknown")
        applicability = {
            "verified": True,
            "candidate_ref": result.candidate_ref,
            "action": result.action,
            "resource": result.resource,
            "capability_affecting": classification == "REQUIRED",
            "applicability_id": result.applicability_ref,
        }
        if classification == "REQUIRED":
            if (result.gate_verified is not True or not result.gate_ref
                    or not result.gate_evidence_refs):
                raise MAEPError("BLOCKED: Native Authority has no canonical MAEP-022 gate attestation")
            applicability["gate_decision"] = {
                "status": "PASS", "verified": True,
                "candidate_ref": result.candidate_ref,
                "policy_version": result.policy_version,
                "gate_id": result.gate_ref,
                "evidence_refs": list(result.gate_evidence_refs),
            }
        return applicability

    def effect_recheck_provider(self, request):
        key = self._key(request)
        with self._lock:
            result = self._decisions.pop(key, None)
        if result is None or result.decision is not Decision.ALLOW:
            raise MAEPError("BLOCKED: no matching native decision for pre-effect recheck")
        target = self.candidate_target_provider(request)
        context = self.authenticated_context_provider()
        native_request = {
            "action": request.get("action"), "resource": request.get("resource"),
            "scope": request.get("scope"), "task_ref": request.get("task_id"),
            "candidate_ref": request.get("candidate_ref"),
        }
        fresh = self.engine.authorize(
            native_request, authenticated_context=context, candidate_target=target
        )
        if fresh.decision is not Decision.ALLOW:
            raise MAEPError("BLOCKED: fresh Memory authority denied at effect boundary")
        if (fresh.principal_ref != request.get("principal")
                or fresh.policy_version != request.get("policy_version")
                or fresh.candidate_ref != request.get("candidate_ref")):
            raise MAEPError("BLOCKED: Memory identity, policy or candidate changed before effect")
        root = self.engine.root_store.load_active()
        policy = self.engine.policy_provider.load_active(root) if root is not None else None
        candidate = self.engine.candidate_provider.inspect(target)
        if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
            raise MAEPError("BLOCKED: TrustRoot unavailable at Memory effect boundary")
        if not isinstance(candidate, dict) or not isinstance(policy, dict):
            raise MAEPError("BLOCKED: current candidate/policy unavailable at Memory effect boundary")
        self.engine.recheck_before_effect(
            fresh, request=native_request,
            current_candidate_ref=candidate.get("candidate_ref"),
            current_root_generation=root.generation, current_root_digest=root.record_digest,
            current_policy_version=policy.get("version"),
            current_policy_digest=policy.get("policy_digest"),
        )
        return True
