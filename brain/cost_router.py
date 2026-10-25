"""Deterministic, fail-closed decision policy for HG reasoning cost routing.

The router does not call providers, infer freshness, grant authority, or execute tasks.
The caller must supply observed task risk, memory applicability/freshness, and an
explicit policy. Unknown state blocks model routing rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROUTER_CONTRACT_VERSION = "hg.cost-router.v1"
ROUTE_DECISIONS = {
    "DETERMINISTIC_ONLY", "REUSE_VERIFIED_EXPERIENCE", "SINGLE_MODEL",
    "CRITIQUE_COUNCIL", "BLOCKED",
}
RISK_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RISK_LEVELS = set(RISK_ORDER)
MEMORY_STATES = {"NOT_NEEDED", "CURRENT_VERIFIED", "STALE", "CONFLICTING", "UNKNOWN", "UNVERIFIED"}


class CostRouterError(ValueError):
    """Invalid routing inputs or policy configuration."""


@dataclass(frozen=True)
class CostRouterPolicy:
    """Explicit owner/policy-supplied bounds; no implicit price or risk thresholds."""
    max_reasoning_calls: int
    max_revision_calls: int
    max_council_calls: int
    council_min_risk: str
    council_on_ambiguity: bool
    council_on_conflict: bool

    def __post_init__(self) -> None:
        for name in ("max_reasoning_calls", "max_revision_calls", "max_council_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CostRouterError(name + " must be a non-negative integer")
        if self.council_min_risk not in RISK_LEVELS:
            raise CostRouterError("council_min_risk is invalid")
        if not isinstance(self.council_on_ambiguity, bool) or not isinstance(self.council_on_conflict, bool):
            raise CostRouterError("council policy switches must be boolean")


@dataclass(frozen=True)
class RouteRequest:
    risk_level: str
    memory_state: str
    deterministic_sufficient: bool
    reasoning_needed: bool
    ambiguity_detected: bool
    conflict_detected: bool
    reasoning_calls_used: int
    revision_calls_used: int
    council_calls_used: int
    reasoning_provider_available: bool
    council_provider_available: bool


@dataclass(frozen=True)
class RouteDecision:
    contract_version: str
    decision: str
    reason_code: str
    reasoning_calls_remaining: int
    revision_calls_remaining: int
    council_calls_remaining: int
    authority_effect: str = "NONE"
    provider_invoked: bool = False


class CostRouter:
    """Choose the least expensive policy-permitted next route without side effects."""

    def __init__(self, *, policy: CostRouterPolicy):
        if not isinstance(policy, CostRouterPolicy):
            raise CostRouterError("an explicit CostRouterPolicy is required")
        self.policy = policy

    def route(self, request: RouteRequest) -> RouteDecision:
        if not isinstance(request, RouteRequest):
            raise CostRouterError("a RouteRequest is required")
        if request.risk_level not in RISK_LEVELS or request.memory_state not in MEMORY_STATES:
            raise CostRouterError("risk or memory state is unknown; routing inputs are invalid")
        for name in ("deterministic_sufficient", "reasoning_needed", "ambiguity_detected",
                     "conflict_detected", "reasoning_provider_available", "council_provider_available"):
            if not isinstance(getattr(request, name), bool):
                raise CostRouterError(name + " must be boolean")
        for name in ("reasoning_calls_used", "revision_calls_used", "council_calls_used"):
            value = getattr(request, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CostRouterError(name + " must be a non-negative integer")

        p = self.policy
        reasoning_left = max(0, p.max_reasoning_calls - request.reasoning_calls_used)
        revision_left = max(0, p.max_revision_calls - request.revision_calls_used)
        council_left = max(0, p.max_council_calls - request.council_calls_used)

        def result(decision: str, reason: str) -> RouteDecision:
            return RouteDecision(ROUTER_CONTRACT_VERSION, decision, reason,
                                 reasoning_left, revision_left, council_left)

        if request.memory_state in {"STALE", "CONFLICTING", "UNKNOWN", "UNVERIFIED"}:
            # Do not let untrusted/stale memory become a routing shortcut. A fresh
            # reasoning route may still be allowed, but conflict requiring evidence
            # resolution is not something the model router can silently resolve.
            if request.memory_state == "CONFLICTING" or request.conflict_detected:
                if p.council_on_conflict and request.council_provider_available and council_left > 0:
                    return result("CRITIQUE_COUNCIL", "CONFLICT_REQUIRES_BOUNDED_REVIEW")
                return result("BLOCKED", "CONFLICT_REQUIRES_EVIDENCE_RESOLUTION")
            if request.memory_state in {"UNKNOWN", "UNVERIFIED"} and not request.reasoning_needed:
                return result("BLOCKED", "MEMORY_APPLICABILITY_NOT_ESTABLISHED")

        if request.deterministic_sufficient and not request.reasoning_needed:
            return result("DETERMINISTIC_ONLY", "DETERMINISTIC_PATH_SUFFICIENT")

        council_required = (
            request.risk_level in RISK_LEVELS and
            RISK_ORDER.index(request.risk_level) >= RISK_ORDER.index(p.council_min_risk)
        ) or (p.council_on_ambiguity and request.ambiguity_detected) or (
            p.council_on_conflict and request.conflict_detected
        )
        if council_required:
            if request.reasoning_needed and not request.reasoning_provider_available:
                return result("BLOCKED", "REASONING_PROVIDER_UNAVAILABLE_FOR_REQUIRED_PLAN")
            if not request.council_provider_available:
                return result("BLOCKED", "COUNCIL_REQUIRED_PROVIDER_UNAVAILABLE")
            if council_left <= 0:
                return result("BLOCKED", "COUNCIL_BUDGET_EXHAUSTED")
            return result("CRITIQUE_COUNCIL", "RISK_OR_AMBIGUITY_POLICY_GATE")

        if request.memory_state == "CURRENT_VERIFIED" and not request.reasoning_needed:
            return result("REUSE_VERIFIED_EXPERIENCE", "CURRENT_VERIFIED_MEMORY_APPLICABLE")
        if not request.reasoning_needed:
            return result("BLOCKED", "NO_SAFE_ROUTE_ESTABLISHED")
        if not request.reasoning_provider_available:
            return result("BLOCKED", "REASONING_PROVIDER_UNAVAILABLE")
        if reasoning_left <= 0:
            return result("BLOCKED", "REASONING_BUDGET_EXHAUSTED")
        if request.revision_calls_used > p.max_revision_calls:
            return result("BLOCKED", "REVISION_BUDGET_EXHAUSTED")
        return result("SINGLE_MODEL", "REASONING_REQUIRED_WITHIN_BUDGET")
