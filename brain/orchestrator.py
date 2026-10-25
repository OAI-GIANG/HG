"""BrainOrchestrator: the single task coordinator for HG.

No adapter is invoked unless NativePolicyEngine returns ALLOW, a durable
idempotency claim succeeds, and authorization is rechecked immediately before
dispatch. This module is not a production runtime by itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from maep.core import MAEPError, POLICY_VERSION, validate_task
from maep.native_authority import (
    AuthorityError, Decision, NativePolicyEngine, RecoveryManager, TrustRootRecord,
)
from tools_automation import AdapterError, validate_adapter_request, validate_adapter_result
from .planning import PlanningEngine, PlanningError, _trusted_context, verify_plan_digest
from .critique import CritiqueEngine, CritiqueError
from .simulation import ScenarioEngine, SimulationError
from .cost_router import CostRouter, CostRouterError, RouteRequest
from .council import CritiqueCouncil
from .provider_guard import authorize_provider_calls, guard_provider


class OrchestrationError(RuntimeError):
    pass


def _canonical_digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class BrainOrchestrator:
    """Coordinate tasks and dispatch only through registered scoped adapters."""

    def __init__(self, *, authority: NativePolicyEngine, adapter_registry: dict[str, Any],
                 idempotency_ledger: Any, receipt_sink: Any, task_store: Any,
                 planning_engine: PlanningEngine | None = None,
                 critique_engine: CritiqueEngine | None = None,
                 scenario_engine: ScenarioEngine | None = None,
                 cost_router: CostRouter | None = None,
                 routing_context_provider: Any | None = None,
                 routing_budget_ledger: Any | None = None):
        if authority is None or not isinstance(adapter_registry, dict) or not adapter_registry:
            raise OrchestrationError("authority and explicit adapter registry are required")
        if idempotency_ledger is None or receipt_sink is None:
            raise OrchestrationError("durable idempotency ledger and receipt sink are required")
        if task_store is None or not callable(getattr(task_store, "get_task", None)):
            raise OrchestrationError("canonical MAEP task store is required")
        if any(not callable(getattr(adapter, "execute", None)) for adapter in adapter_registry.values()):
            raise OrchestrationError("every registered adapter must implement execute")
        self.authority = authority
        self.adapter_registry = dict(adapter_registry)
        self.idempotency_ledger = idempotency_ledger
        self.receipt_sink = receipt_sink
        self.task_store = task_store
        self.planning_engine = planning_engine
        if critique_engine is not None and not callable(getattr(critique_engine, "critique", None)):
            raise OrchestrationError("critique engine contract is invalid")
        if scenario_engine is not None and not callable(getattr(scenario_engine, "run", None)):
            raise OrchestrationError("scenario engine contract is invalid")
        self.critique_engine = critique_engine
        self.scenario_engine = scenario_engine
        if cost_router is not None:
            if not isinstance(cost_router, CostRouter):
                raise OrchestrationError("cost router contract is invalid")
            if not callable(routing_context_provider):
                raise OrchestrationError("BLOCKED: cost router requires an explicit routing context provider")
            if not callable(getattr(routing_budget_ledger, "get_usage", None)) or not callable(
                    getattr(routing_budget_ledger, "reserve_bound", None)):
                raise OrchestrationError("BLOCKED: cost router requires identity-bound atomic budget reservations")
            if planning_engine is not None and getattr(planning_engine, "max_revisions", 0) != 0:
                raise OrchestrationError("BLOCKED: router-enabled planner must disable internal unmetered retries")
        elif routing_context_provider is not None or routing_budget_ledger is not None:
            raise OrchestrationError("routing context and budget ledger require an explicit cost router")
        self.cost_router = cost_router
        self.routing_context_provider = routing_context_provider
        self.routing_budget_ledger = routing_budget_ledger
        if cost_router is not None:
            # Router-enabled runtime engine entrypoints must not retain an unguarded
            # provider path. Standalone engines without a router remain compatible.
            if self.planning_engine is not None:
                self.planning_engine.provider = guard_provider(self.planning_engine.provider)
            if isinstance(self.critique_engine, CritiqueCouncil):
                for _, member_engine in self.critique_engine.members:
                    member_engine.provider = guard_provider(member_engine.provider)
            elif self.critique_engine is not None and hasattr(self.critique_engine, "provider"):
                self.critique_engine.provider = guard_provider(self.critique_engine.provider)

    def _route_cost(self, *, task_ref: str, snapshot: dict[str, Any], phase: str,
                    allow_council_prerequisite: bool = False) -> str | None:
        """Choose a permitted route; the guarded provider reserves before each actual call."""
        if self.cost_router is None:
            return None
        task = snapshot.get("task") if isinstance(snapshot, dict) else None
        if not isinstance(task, dict):
            raise OrchestrationError("BLOCKED: canonical task unavailable for cost routing")
        try:
            context = self.routing_context_provider(task_snapshot=snapshot, phase=phase)
            if not isinstance(context, dict):
                raise CostRouterError("routing context must be an object")
            if (context.get("candidate_ref") != snapshot.get("candidate_ref")
                    or context.get("policy_version") != task.get("policy_version")):
                raise CostRouterError("routing context candidate/policy binding mismatch")
            usage = self.routing_budget_ledger.get_usage(task_ref)
            if not isinstance(usage, dict):
                raise CostRouterError("routing budget ledger returned invalid usage")
            council_available = isinstance(self.critique_engine, CritiqueCouncil)
            if phase == "planning":
                reasoning_available = self.planning_engine is not None
            else:
                reasoning_available = self.critique_engine is not None
            request = RouteRequest(
                risk_level=context["risk_level"], memory_state=context["memory_state"],
                deterministic_sufficient=context.get("deterministic_sufficient", False),
                reasoning_needed=context.get("reasoning_needed", True),
                ambiguity_detected=context.get("ambiguity_detected", False),
                conflict_detected=context.get("conflict_detected", False),
                reasoning_calls_used=usage.get("reasoning", 0),
                revision_calls_used=usage.get("revision", 0),
                council_calls_used=usage.get("council", 0),
                reasoning_provider_available=reasoning_available,
                council_provider_available=council_available,
            )
            decision = self.cost_router.route(request)
            if decision.decision == "BLOCKED":
                raise OrchestrationError("BLOCKED by Cost Router: " + decision.reason_code)
            if decision.decision == "DETERMINISTIC_ONLY":
                return decision.decision
            if decision.decision == "REUSE_VERIFIED_EXPERIENCE":
                return decision.decision
            if decision.decision == "CRITIQUE_COUNCIL":
                if phase == "planning" and allow_council_prerequisite:
                    # A plan must exist before it can be critiqued. Council is still
                    # mandatory at the review phase; direct plan_task cannot bypass it.
                    category = "reasoning"
                elif phase == "critique" and council_available:
                    category = "council"
                else:
                    raise OrchestrationError("BLOCKED by Cost Router: council route requires plan_and_review and an explicit council")
            elif decision.decision == "SINGLE_MODEL":
                if phase == "critique" and isinstance(self.critique_engine, CritiqueCouncil):
                    raise OrchestrationError("BLOCKED by Cost Router: policy selected single reviewer but only council is configured")
                category = "reasoning"
            else:
                raise OrchestrationError("BLOCKED by Cost Router: unsupported route decision")
            # Actual reservations occur immediately inside GuardedJSONProvider,
            # once per provider invocation, after canonical bindings are established.
            return decision.decision
        except OrchestrationError:
            raise
        except Exception as exc:
            raise OrchestrationError("BLOCKED: routing context or budget could not be verified") from exc

    def plan_task(self, *, task_ref: str, candidate_target: Any,
                  context_refs: list[str] | None = None) -> dict[str, Any]:
        """Public planning entrypoint; council-required routes need plan_and_review."""
        return self._plan_task(
            task_ref=task_ref, candidate_target=candidate_target,
            context_refs=context_refs, revision_feedback=None,
            allow_council_prerequisite=False,
        )

    def _plan_task(self, *, task_ref: str, candidate_target: Any,
                   context_refs: list[str] | None = None,
                   revision_feedback: list[str] | None = None,
                   allow_council_prerequisite: bool = False) -> dict[str, Any]:
        """Create a candidate-bound plan from the canonical ASSESSED task.

        The active trust root, policy and candidate are re-read before prompting.
        This method does not transition task state, authorize, persist a plan,
        invoke tool adapters, or execute any side effect.
        """
        if self.planning_engine is None and self.cost_router is None:
            raise OrchestrationError("BLOCKED: reasoning provider is not configured")
        if not isinstance(task_ref, str) or not task_ref.strip():
            raise OrchestrationError("BLOCKED: canonical task reference is required")
        try:
            snapshot = self.task_store.get_task(task_ref)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("task"), dict):
                raise PlanningError("canonical task snapshot unavailable")
            task = snapshot["task"]
            if task.get("task_id") != task_ref:
                raise PlanningError("canonical task identity mismatch")
            root = self.authority.root_store.load_active()
            if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
                raise PlanningError("active trusted root is unavailable or invalid")
            policy = self.authority.policy_provider.load_active(root)
            if (not isinstance(policy, dict) or policy.get("status") != "ACTIVE"
                    or policy.get("version") != task.get("policy_version")
                    or policy.get("root_generation") != root.generation
                    or policy.get("provenance_verified") is not True
                    or not isinstance(policy.get("policy_digest"), str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", policy.get("policy_digest", "")) is None
                    or not isinstance(policy.get("approval_evidence_refs"), list)
                    or not policy.get("approval_evidence_refs")):
                raise PlanningError("active policy is stale, unproven or root-mismatched")
            candidate = self.authority.candidate_provider.inspect(candidate_target)
            if (not isinstance(candidate, dict) or candidate.get("verified") is not True
                    or candidate.get("repository") != "OAI-GIANG/HG"
                    or not isinstance(candidate.get("candidate_ref"), str)
                    or not candidate.get("candidate_ref")):
                raise PlanningError("current HG candidate is missing or unverified")
            if snapshot.get("candidate_ref") != candidate.get("candidate_ref"):
                raise PlanningError("canonical task candidate does not match the live candidate")
            if self.cost_router is not None:
                route = self._route_cost(
                    task_ref=task_ref, snapshot=snapshot, phase="planning",
                    allow_council_prerequisite=allow_council_prerequisite,
                )
                if route in {"DETERMINISTIC_ONLY", "REUSE_VERIFIED_EXPERIENCE"}:
                    raise OrchestrationError(
                        "BLOCKED: this planning entrypoint requires a validated plan; "
                        "deterministic/reuse route needs a dedicated verified plan adapter"
                    )
            if self.planning_engine is None:
                raise OrchestrationError("BLOCKED: reasoning provider is not configured")
            if self.cost_router is None:
                return self.planning_engine.create_plan(
                    snapshot, context_refs=context_refs, revision_feedback=revision_feedback,
                )
            category = "revision" if revision_feedback else "reasoning"
            limit = (self.cost_router.policy.max_revision_calls if category == "revision"
                     else self.cost_router.policy.max_reasoning_calls)
            with authorize_provider_calls(
                ledger=self.routing_budget_ledger, task_ref=task_ref,
                candidate_ref=candidate["candidate_ref"], policy_version=task["policy_version"],
                route=(route + "_REVISION" if category == "revision" else route),
                category=category, limit=limit,
            ):
                return self.planning_engine.create_plan(
                    snapshot, context_refs=context_refs, revision_feedback=revision_feedback,
                )
        except OrchestrationError:
            raise
        except PlanningError as exc:
            raise OrchestrationError("BLOCKED: plan validation failed: " + str(exc)) from exc
        except Exception as exc:
            raise OrchestrationError("BLOCKED: canonical task/policy/candidate lookup failed") from exc

    def plan_and_review(self, *, task_ref: str, candidate_target: Any,
                        context_refs: list[str] | None = None,
                        scenario_request: dict[str, Any] | None = None,
                        claims: list[dict[str, Any]] | None = None,
                        evidence_refs: list[str] | None = None,
                        assumptions: list[str] | None = None,
                        constraints: list[str] | None = None) -> dict[str, Any]:
        """Create and critique a plan, with at most one review-driven revision.

        A revised plan is always revalidated by PlanningEngine and re-reviewed.
        Scenario simulation is performed only after an ACCEPT verdict. This method
        never persists Memory, changes task state, authorizes, or executes a plan.
        """
        if self.critique_engine is None:
            raise OrchestrationError("BLOCKED: critique provider is not configured")
        plan = self._plan_task(
            task_ref=task_ref, candidate_target=candidate_target,
            context_refs=context_refs, revision_feedback=None,
            allow_council_prerequisite=self.cost_router is not None,
        )
        critiques: list[dict[str, Any]] = []
        first = self.critique_plan(
            task_ref=task_ref, candidate_target=candidate_target, plan=plan,
            claims=claims, evidence_refs=evidence_refs,
            assumptions=assumptions, constraints=constraints,
        )
        critiques.append(first)
        revision_count = 0
        if first.get("verdict") == "REVISE":
            feedback = list(first.get("revision_requests", []))
            for item in first.get("reviewed_items", []):
                if isinstance(item, dict) and item.get("assessment") in {"BLOCKER", "UNRESOLVED"}:
                    rationale = item.get("rationale")
                    if isinstance(rationale, str) and rationale.strip():
                        feedback.append("Review finding for " + str(item.get("item_id", "item")) + ": " + rationale)
            # Keep the feedback bounded; it remains untrusted input to the planner.
            feedback = feedback[:16]
            plan = self._plan_task(
                task_ref=task_ref, candidate_target=candidate_target,
                context_refs=context_refs, revision_feedback=feedback,
                allow_council_prerequisite=self.cost_router is not None,
            )
            revision_count = 1
            second = self.critique_plan(
                task_ref=task_ref, candidate_target=candidate_target, plan=plan,
                claims=claims, evidence_refs=evidence_refs,
                assumptions=assumptions, constraints=constraints,
            )
            critiques.append(second)

        final_critique = critiques[-1]
        simulation = None
        if final_critique.get("verdict") == "ACCEPT" and scenario_request is not None:
            simulation = self.simulate_scenarios(
                task_ref=task_ref, candidate_target=candidate_target,
                request=scenario_request,
            )
            if simulation.get("status") == "SIMULATED":
                final_critique = self.critique_plan(
                    task_ref=task_ref, candidate_target=candidate_target, plan=plan,
                    claims=claims, evidence_refs=evidence_refs,
                    assumptions=assumptions, constraints=constraints,
                    scenario_result=simulation,
                )
                critiques.append(final_critique)

        verdict = final_critique.get("verdict")
        if simulation is not None and simulation.get("status") != "SIMULATED":
            status = "STOPPED_SIMULATION_BUDGET"
        elif verdict == "ACCEPT":
            status = "PLAN_REVIEW_COMPLETE"
        elif verdict == "REVISE":
            status = "PLAN_REVIEW_NEEDS_REVISION"
        elif verdict == "REJECT":
            status = "PLAN_REVIEW_REJECTED"
        else:
            status = "PLAN_REVIEW_INSUFFICIENT_EVIDENCE"
        return {
            "status": status,
            "task_ref": task_ref,
            "candidate_ref": plan.get("candidate_ref"),
            "plan": plan,
            "critique_rounds": critiques,
            "final_critique": final_critique,
            "revision_count": revision_count,
            "simulation": simulation,
            "authority_effect": "NONE",
            "side_effects_performed": False,
        }

    def _load_current_planning_binding(self, *, task_ref: str, candidate_target: Any):
        """Return current canonical task/candidate only after live policy rechecks."""
        if not isinstance(task_ref, str) or not task_ref.strip():
            raise OrchestrationError("BLOCKED: canonical task reference is required")
        try:
            snapshot = self.task_store.get_task(task_ref)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("task"), dict):
                raise MAEPError("canonical task snapshot is unavailable")
            task = snapshot["task"]
            validate_task(task)
            if task.get("task_id") != task_ref or task.get("state") != "ASSESSED":
                raise MAEPError("canonical task identity/state is not eligible for planning review")
            if task.get("policy_version") != POLICY_VERSION or snapshot.get("policy_status") != "CURRENT":
                raise MAEPError("canonical task policy is stale")
            root = self.authority.root_store.load_active()
            if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
                raise MAEPError("active trust root is unavailable or invalid")
            policy = self.authority.policy_provider.load_active(root)
            if (not isinstance(policy, dict) or policy.get("status") != "ACTIVE"
                    or policy.get("version") != task.get("policy_version")
                    or policy.get("root_generation") != root.generation
                    or policy.get("provenance_verified") is not True
                    or not isinstance(policy.get("policy_digest"), str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", policy.get("policy_digest", "")) is None
                    or not isinstance(policy.get("approval_evidence_refs"), list)
                    or not policy.get("approval_evidence_refs")):
                raise MAEPError("active policy provenance/root binding is stale or unproven")
            candidate = self.authority.candidate_provider.inspect(candidate_target)
            if (not isinstance(candidate, dict) or candidate.get("verified") is not True
                    or candidate.get("repository") != "OAI-GIANG/HG"
                    or not isinstance(candidate.get("candidate_ref"), str)
                    or not candidate.get("candidate_ref")):
                raise MAEPError("current HG candidate is missing or unverified")
            if snapshot.get("candidate_ref") != candidate.get("candidate_ref"):
                raise MAEPError("canonical task candidate differs from current candidate")
            return snapshot, task, candidate
        except OrchestrationError:
            raise
        except Exception as exc:
            raise OrchestrationError(
                "BLOCKED: canonical task, policy, trust root or candidate binding is unavailable"
            ) from exc

    def critique_plan(self, *, task_ref: str, candidate_target: Any, plan: dict[str, Any],
                      claims: list[dict[str, Any]] | None = None,
                      evidence_refs: list[str] | None = None,
                      assumptions: list[str] | None = None,
                      constraints: list[str] | None = None,
                      scenario_result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Critique an already validated plan only after rereading live task/policy/candidate."""
        if self.critique_engine is None:
            raise OrchestrationError("BLOCKED: critique provider is not configured")
        snapshot, task, candidate = self._load_current_planning_binding(
            task_ref=task_ref, candidate_target=candidate_target
        )
        candidate_ref = candidate["candidate_ref"]
        if (not isinstance(plan, dict) or not verify_plan_digest(plan)
                or plan.get("task_id") != task_ref
                or plan.get("candidate_ref") != candidate_ref
                or plan.get("policy_version") != task.get("policy_version")):
            raise OrchestrationError("BLOCKED: plan identity/digest does not match current task")
        try:
            verified_context = _trusted_context(
                getattr(self.planning_engine, "context_resolver", None),
                plan.get("context_record_refs", []), candidate_ref=candidate_ref,
                policy_version=task["policy_version"],
            )
        except PlanningError as exc:
            raise OrchestrationError("BLOCKED: plan context could not be reverified") from exc
        route = None
        if self.cost_router is not None:
            route = self._route_cost(task_ref=task_ref, snapshot=snapshot, phase="critique")
            if route not in {"SINGLE_MODEL", "CRITIQUE_COUNCIL"}:
                raise OrchestrationError("BLOCKED by Cost Router: critique requires an explicitly permitted provider route")
        try:
            kwargs = dict(
                task_ref=task_ref, candidate_ref=candidate_ref,
                policy_version=task["policy_version"], plan=plan, claims=claims,
                evidence_refs=evidence_refs, assumptions=assumptions,
                constraints=constraints, scenario_result=scenario_result, task=task,
                verified_context=verified_context,
            )
            if self.cost_router is None:
                return self.critique_engine.critique(**kwargs)
            category = "council" if route == "CRITIQUE_COUNCIL" else "reasoning"
            limit = (self.cost_router.policy.max_council_calls if category == "council"
                     else self.cost_router.policy.max_reasoning_calls)
            if category == "council" and isinstance(self.critique_engine, CritiqueCouncil):
                if self.routing_budget_ledger.get_usage(task_ref).get("council", 0) + len(self.critique_engine.members) > limit:
                    raise OrchestrationError("BLOCKED by Cost Router: council per-provider-call budget insufficient")
            with authorize_provider_calls(
                ledger=self.routing_budget_ledger, task_ref=task_ref,
                candidate_ref=candidate_ref, policy_version=task["policy_version"],
                route=route, category=category, limit=limit,
            ):
                return self.critique_engine.critique(**kwargs)
        except CritiqueError as exc:
            raise OrchestrationError("BLOCKED: critique output failed validation") from exc

    def simulate_scenarios(self, *, task_ref: str, candidate_target: Any,
                            request: dict[str, Any]) -> dict[str, Any]:
        """Run bounded numerical scenarios after verifying current task/policy/candidate."""
        if self.scenario_engine is None:
            raise OrchestrationError("BLOCKED: scenario engine is not configured")
        _, task, candidate = self._load_current_planning_binding(
            task_ref=task_ref, candidate_target=candidate_target
        )
        if (not isinstance(request, dict) or request.get("task_ref") != task_ref
                or request.get("candidate_ref") != candidate["candidate_ref"]
                or request.get("policy_version") != task["policy_version"]):
            raise OrchestrationError("BLOCKED: scenario input identity does not match current task")
        try:
            return self.scenario_engine.run(request=request)
        except SimulationError as exc:
            raise OrchestrationError("BLOCKED: scenario input or resource budget is invalid") from exc

    def review_and_simulate(self, *, task_ref: str, candidate_target: Any,
                            plan: dict[str, Any],
                            scenario_request: dict[str, Any] | None = None,
                            claims: list[dict[str, Any]] | None = None,
                            evidence_refs: list[str] | None = None,
                            assumptions: list[str] | None = None,
                            constraints: list[str] | None = None) -> dict[str, Any]:
        """Bounded flow: critique once; optionally simulate and critique that result once.

        This function never revises or executes a plan. A REVISE result is returned
        to the caller; a revised plan requires a separate explicit planning request.
        """
        initial = self.critique_plan(
            task_ref=task_ref, candidate_target=candidate_target, plan=plan, claims=claims,
            evidence_refs=evidence_refs, assumptions=assumptions, constraints=constraints,
        )
        result = {
            "status": "CRITIQUE_COMPLETE",
            "task_ref": task_ref,
            "candidate_ref": plan.get("candidate_ref") if isinstance(plan, dict) else None,
            "plan_digest": plan.get("plan_digest") if isinstance(plan, dict) else None,
            "initial_critique": initial,
            "simulation": None,
            "final_critique": None,
            "authority_effect": "NONE",
            "side_effects_performed": False,
        }
        if initial.get("verdict") != "ACCEPT":
            result["status"] = "STOPPED_CRITIQUE_" + initial["verdict"]
            return result
        if scenario_request is None:
            return result
        simulation = self.simulate_scenarios(
            task_ref=task_ref, candidate_target=candidate_target, request=scenario_request
        )
        result["simulation"] = simulation
        if simulation.get("status") != "SIMULATED":
            result["status"] = "STOPPED_SIMULATION_BUDGET"
            return result
        final = self.critique_plan(
            task_ref=task_ref, candidate_target=candidate_target, plan=plan, claims=claims,
            evidence_refs=evidence_refs, assumptions=assumptions, constraints=constraints,
            scenario_result=simulation,
        )
        result["final_critique"] = final
        result["status"] = (
            "REVIEW_COMPLETE" if final.get("verdict") == "ACCEPT"
            else "STOPPED_FINAL_CRITIQUE_" + str(final.get("verdict"))
        )
        return result

    def dispatch(self, *, request: dict[str, Any], authenticated_context: Any,
                 candidate_target: Any, adapter_name: str, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(request, dict) or not idempotency_key or not isinstance(idempotency_key, str):
            raise OrchestrationError("request and idempotency key are required")
        adapter = self.adapter_registry.get(adapter_name)
        if adapter is None:
            raise OrchestrationError("adapter is not registered")
        if request.get("action") is None or request.get("resource") is None or request.get("task_ref") is None:
            raise OrchestrationError("action/resource/task_ref are required")
        # The branch-4 contract is a structural boundary, never an authority grant.
        # Validate before consulting authority or invoking any adapter.
        try:
            validate_adapter_request(request, idempotency_key=idempotency_key)
        except AdapterError as exc:
            raise OrchestrationError("BLOCKED: invalid tools-and-automation request") from exc

        # Bind every external effect to the canonical, persisted MAEP task. A caller
        # supplied task object or state label is never accepted as the source of truth.
        try:
            task_snapshot = self.task_store.get_task(request["task_ref"])
            if not isinstance(task_snapshot, dict):
                raise MAEPError("canonical task snapshot is missing")
            task = task_snapshot.get("task")
            validate_task(task)
            if task.get("task_id") != request["task_ref"]:
                raise MAEPError("canonical task identity mismatch")
            if task.get("state") != "RUNNING":
                raise MAEPError("task must be in canonical RUNNING state before dispatch")
            if task.get("policy_version") != POLICY_VERSION or task_snapshot.get("policy_status") != "CURRENT":
                raise MAEPError("task MAEP policy version is stale")
            task_scope = task.get("scope", {})
            included = set(task_scope.get("include", []))
            excluded = set(task_scope.get("exclude", []))
            requested_scope = set(request.get("scope", []))
            if not requested_scope.issubset(included) or request.get("resource") not in included:
                raise MAEPError("dispatch resource/scope exceeds canonical task scope")
            if request.get("resource") in excluded or requested_scope.intersection(excluded):
                raise MAEPError("dispatch resource/scope is excluded by canonical task scope")
            current_candidate = self.authority.candidate_provider.inspect(candidate_target)
            if (not isinstance(current_candidate, dict)
                    or current_candidate.get("verified") is not True
                    or not isinstance(current_candidate.get("candidate_ref"), str)
                    or not current_candidate.get("candidate_ref")):
                raise MAEPError("current candidate is missing or unverified")
            if task_snapshot.get("candidate_ref") != current_candidate.get("candidate_ref"):
                raise MAEPError("canonical task candidate does not match dispatch candidate")
        except Exception as exc:
            raise OrchestrationError("BLOCKED before side effect: canonical MAEP task contract unavailable or invalid") from exc

        request_digest = _canonical_digest(request)
        decision = self.authority.authorize(
            request, authenticated_context=authenticated_context,
            candidate_target=candidate_target,
        )
        if decision.decision is not Decision.ALLOW:
            self._record_receipt({
                "receipt_id": "deny:" + request_digest,
                "outcome": decision.decision.value,
                "reason_codes": list(decision.reason_codes),
                "request_digest": request_digest,
                "candidate_ref": decision.candidate_ref,
                "decision_digest": decision.decision_digest,
            })
            raise OrchestrationError("BLOCKED before side effect: " + ",".join(decision.reason_codes))

        # Durable idempotency reservation is mandatory before any adapter invocation.
        try:
            reservation = self.idempotency_ledger.claim(
                idempotency_key=idempotency_key, request_digest=request_digest,
                decision_digest=decision.decision_digest,
            )
        except Exception as exc:
            raise OrchestrationError("BLOCKED: idempotency reservation failed") from exc
        if not isinstance(reservation, dict) or reservation.get("status") != "RESERVED":
            raise OrchestrationError("BLOCKED: duplicate, conflicting, or unresolved idempotency key")

        # Re-run the complete authorization chain immediately before dispatch so
        # revocation, policy, applicability and MAEP-022 gate changes are observed.
        decision = self.authority.authorize(
            request, authenticated_context=authenticated_context, candidate_target=candidate_target
        )
        if decision.decision is not Decision.ALLOW:
            self._record_receipt({
                "receipt_id": "blocked:" + request_digest,
                "outcome": "BLOCKED",
                "reason_codes": list(decision.reason_codes),
                "request_digest": request_digest,
                "decision_digest": decision.decision_digest,
            })
            raise OrchestrationError("BLOCKED before side effect: fresh authorization denied")
        # Re-read current authority and candidate immediately before dispatch.
        root = self.authority.root_store.load_active()
        if root is None:
            raise OrchestrationError("BLOCKED: trust root unavailable before effect")
        candidate = self.authority.candidate_provider.inspect(candidate_target)
        policy = self.authority.policy_provider.load_active(root)
        if not isinstance(candidate, dict) or not isinstance(policy, dict):
            raise OrchestrationError("BLOCKED: candidate/policy recheck failed")
        try:
            self.authority.recheck_before_effect(
                decision, request=request,
                current_candidate_ref=candidate.get("candidate_ref"),
                current_root_generation=root.generation, current_root_digest=root.record_digest,
                current_policy_version=policy.get("version"),
                current_policy_digest=policy.get("policy_digest"),
            )
        except AuthorityError as exc:
            self._record_receipt({
                "receipt_id": "blocked:" + request_digest,
                "outcome": "BLOCKED",
                "reason_codes": [str(exc)],
                "request_digest": request_digest,
                "decision_digest": decision.decision_digest,
            })
            raise OrchestrationError("BLOCKED before side effect: authorization stale") from exc

        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            adapter_result = adapter.execute(
                request=dict(request), authorization=decision,
                idempotency_key=idempotency_key,
            )
            try:
                adapter_result = validate_adapter_result(adapter_result)
                outcome = adapter_result["outcome"]
            except AdapterError:
                outcome = "UNKNOWN"
                adapter_result = {"outcome": outcome, "reason": "adapter returned invalid/ambiguous result"}
        except TimeoutError:
            outcome = "UNKNOWN"
            adapter_result = {"outcome": outcome, "reason": "adapter timeout"}
        except Exception as exc:
            # An exception after invocation does not prove the external effect did not happen.
            outcome = "UNKNOWN"
            adapter_result = {"outcome": outcome, "reason": "adapter exception: " + type(exc).__name__}

        receipt = {
            "receipt_id": "effect:" + idempotency_key,
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "decision_digest": decision.decision_digest,
            "candidate_ref": decision.candidate_ref,
            "policy_version": decision.policy_version,
            "root_generation": decision.root_generation,
            "adapter": adapter_name,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "outcome": outcome,
            "adapter_receipt": adapter_result,
        }
        try:
            self.idempotency_ledger.record_outcome(
                idempotency_key=idempotency_key, request_digest=request_digest,
                outcome=outcome, receipt=receipt,
            )
            self._record_receipt(receipt)
        except Exception as exc:
            # Side effect may already have occurred; do not retry. Require reconciliation.
            raise OrchestrationError("OUTCOME_UNKNOWN: durable receipt failed; reconciliation required") from exc
        if outcome == "UNKNOWN":
            action_idempotent = adapter_result.get("idempotent") is True
            recovery = RecoveryManager.classify_outcome(
                outcome=outcome, action_idempotent=action_idempotent,
                live_state_reconciled=False,
            )
            raise OrchestrationError("OUTCOME_UNKNOWN: " + recovery)
        return receipt

    def _record_receipt(self, receipt: dict[str, Any]) -> None:
        ref = self.receipt_sink.append({
            "event_type": "brain.effect.receipt",
            "payload": receipt,
            "payload_digest": _canonical_digest(receipt),
        })
        if not isinstance(ref, str) or not ref.strip():
            raise OrchestrationError("durable effect receipt reference missing")
