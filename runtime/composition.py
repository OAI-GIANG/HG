"""Explicit HG runtime composition root.

There are no test/mock defaults and no automatic trust-root bootstrap. This factory
refuses startup if the approved root/policy cannot be verified. Callers must provide
the authenticated providers and durable sinks from the approved runtime boundary.
"""
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from brain import BrainOrchestrator
from brain.critique import CritiqueEngine, CritiqueError
from brain.council import CritiqueCouncil, CouncilMember, CouncilError
from brain.simulation import ScenarioEngine
from brain.cost_router import CostRouter
from maep.native_authority import AuthorityError, NativePolicyEngine, TrustRootRecord
from memory import MemoryStore
from memory.authority_adapter import MemoryNativeAuthorityAdapter
from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider
from brain.planning import PlanningEngine, PlanningError


@dataclass(frozen=True)
class HGRuntime:
    authority: NativePolicyEngine
    brain: BrainOrchestrator
    memory: MemoryStore
    candidate_ref_provider: Any
    authenticated_context_provider: Any
    candidate_target_provider: Any
    runtime_profile: str = "production"
    planner: PlanningEngine | None = None
    critique_engine: Any | None = None
    scenario_engine: ScenarioEngine | None = None
    cost_router: CostRouter | None = None


def build_runtime(*, root_store, principal_provider, candidate_provider, policy_provider,
                  applicability_provider, gate_provider, evidence_sink,
                  authenticated_context_provider, candidate_target_provider,
                  memory_principal_provider, memory_candidate_ref_provider,
                  memory_db_path, live_state_provider, acceptance_provider,
                  adapter_registry, idempotency_ledger, receipt_sink,
                  reasoning_provider=None, context_resolver=None,
                  critique_provider=None, critique_providers=None, scenario_engine=None,
                  cost_router=None, routing_context_provider=None, routing_budget_ledger=None):
    """Construct HG's authority/Brain/Memory graph; never bootstrap or initialize data.

    All dependencies are explicit. This factory intentionally cannot invent a principal,
    policy, candidate identity, MAEP-022 result, evidence sink, or idempotency store.
    """
    required = {
        "root_store": root_store, "principal_provider": principal_provider,
        "candidate_provider": candidate_provider, "policy_provider": policy_provider,
        "applicability_provider": applicability_provider, "gate_provider": gate_provider,
        "evidence_sink": evidence_sink, "authenticated_context_provider": authenticated_context_provider,
        "candidate_target_provider": candidate_target_provider,
        "memory_principal_provider": memory_principal_provider,
        "memory_candidate_ref_provider": memory_candidate_ref_provider,
        "memory_db_path": memory_db_path, "live_state_provider": live_state_provider,
        "acceptance_provider": acceptance_provider, "adapter_registry": adapter_registry,
        "idempotency_ledger": idempotency_ledger, "receipt_sink": receipt_sink,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise AuthorityError("runtime composition missing dependencies: " + ", ".join(sorted(missing)))
    root = root_store.load_active()
    if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
        raise AuthorityError("runtime startup blocked: approved active TrustRoot unavailable")
    policy = policy_provider.load_active(root)
    if (not isinstance(policy, dict) or policy.get("status") != "ACTIVE"
            or not isinstance(policy.get("version"), str)
            or policy.get("root_generation") != root.generation
            or policy.get("provenance_verified") is not True
            or not isinstance(policy.get("policy_digest"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", policy.get("policy_digest", "")) is None
            or not isinstance(policy.get("approval_evidence_refs"), list)
            or not policy.get("approval_evidence_refs")):
        raise AuthorityError("runtime startup blocked: active policy provenance/root binding invalid")
    if not isinstance(applicability_provider, TrustedApplicabilityProvider):
        raise AuthorityError("runtime composition blocked: trusted applicability provider required")
    if not isinstance(gate_provider, TrustedGateEvidenceProvider):
        raise AuthorityError("runtime composition blocked: trusted MAEP-022 gate evidence provider required")
    provider_contracts = (
        (principal_provider, "resolve"), (candidate_provider, "inspect"),
        (policy_provider, "load_active"), (applicability_provider, "classify"),
        (gate_provider, "evaluate"), (evidence_sink, "append"),
        (idempotency_ledger, "claim"), (idempotency_ledger, "record_outcome"),
        (receipt_sink, "append"),
    )
    if any(not callable(getattr(provider, method, None)) for provider, method in provider_contracts):
        raise AuthorityError("runtime startup blocked: authority/evidence provider contract incomplete")
    callable_dependencies = (authenticated_context_provider, candidate_target_provider,
                             memory_principal_provider, memory_candidate_ref_provider,
                             live_state_provider, acceptance_provider)
    if any(not callable(item) for item in callable_dependencies):
        raise AuthorityError("runtime startup blocked: required runtime provider is not callable")
    if not isinstance(adapter_registry, dict) or not adapter_registry or any(
            not callable(getattr(adapter, "execute", None)) for adapter in adapter_registry.values()):
        raise AuthorityError("runtime startup blocked: adapter registry is invalid")
    if not Path(memory_db_path).expanduser().absolute().parent.exists():
        raise AuthorityError("runtime startup blocked: Memory database parent does not exist")
    if context_resolver is not None and not callable(getattr(context_resolver, "resolve", None)):
        raise AuthorityError("runtime composition blocked: context resolver contract invalid")
    if cost_router is not None:
        if not isinstance(cost_router, CostRouter):
            raise AuthorityError("runtime composition blocked: cost router contract invalid")
        if not callable(routing_context_provider):
            raise AuthorityError("runtime composition blocked: explicit routing context provider required")
        if (not callable(getattr(routing_budget_ledger, "get_usage", None))
                or not callable(getattr(routing_budget_ledger, "reserve_bound", None))):
            raise AuthorityError("runtime composition blocked: identity-bound atomic routing budget ledger required")
    elif routing_context_provider is not None or routing_budget_ledger is not None:
        raise AuthorityError("runtime composition blocked: routing dependencies require a cost router")
    if reasoning_provider is None and context_resolver is not None:
        raise AuthorityError("runtime composition blocked: context resolver requires reasoning provider")
    planner = None
    if reasoning_provider is not None:
        try:
            planner = PlanningEngine(
                provider=reasoning_provider, context_resolver=context_resolver,
                max_revisions=0 if cost_router is not None else 1,
            )
        except PlanningError as exc:
            raise AuthorityError("runtime composition blocked: planning provider contract invalid") from exc
    critique_engine = None
    if critique_provider is not None and critique_providers is not None:
        raise AuthorityError("runtime composition blocked: configure one critique provider mode only")
    if critique_providers is not None:
        if not isinstance(critique_providers, list):
            raise AuthorityError("runtime composition blocked: critique_providers must be an explicit list")
        members = []
        for item in critique_providers:
            if not isinstance(item, dict) or set(item) != {"name", "role", "provider"}:
                raise AuthorityError("runtime composition blocked: each council member requires name, role and provider")
            try:
                members.append(CouncilMember(
                    name=item["name"], role=item["role"], provider=item["provider"],
                ))
            except TypeError as exc:
                raise AuthorityError("runtime composition blocked: council member configuration invalid") from exc
        try:
            critique_engine = CritiqueCouncil(members=members)
        except CouncilError as exc:
            raise AuthorityError("runtime composition blocked: critique council contract invalid") from exc
    elif critique_provider is not None:
        try:
            critique_engine = CritiqueEngine(provider=critique_provider)
        except CritiqueError as exc:
            raise AuthorityError("runtime composition blocked: critique provider contract invalid") from exc
    if scenario_engine is None:
        scenario_engine = ScenarioEngine()
    elif not callable(getattr(scenario_engine, "run", None)):
        raise AuthorityError("runtime composition blocked: scenario engine contract invalid")

    authority = NativePolicyEngine(
        root_store=root_store, principal_provider=principal_provider,
        candidate_provider=candidate_provider, policy_provider=policy_provider,
        applicability_provider=applicability_provider, gate_provider=gate_provider,
        evidence_sink=evidence_sink,
    )
    memory_authority = MemoryNativeAuthorityAdapter(
        engine=authority,
        authenticated_context_provider=authenticated_context_provider,
        candidate_target_provider=candidate_target_provider,
    )
    memory = MemoryStore(
        memory_db_path,
        principal_provider=memory_principal_provider,
        policy_evaluator=memory_authority.policy_evaluator,
        live_state_provider=live_state_provider,
        acceptance_provider=acceptance_provider,
        applicability_provider=memory_authority.applicability_provider,
        candidate_ref_provider=memory_candidate_ref_provider,
        effect_recheck_provider=memory_authority.effect_recheck_provider,
        execution_mode="AUTHORIZED_EXECUTION",
    )
    brain = BrainOrchestrator(
        authority=authority, adapter_registry=adapter_registry,
        idempotency_ledger=idempotency_ledger, receipt_sink=receipt_sink,
        task_store=memory, planning_engine=planner,
        critique_engine=critique_engine, scenario_engine=scenario_engine,
        cost_router=cost_router, routing_context_provider=routing_context_provider,
        routing_budget_ledger=routing_budget_ledger,
    )
    return HGRuntime(
        authority=authority, brain=brain, memory=memory,
        candidate_ref_provider=memory_candidate_ref_provider,
        authenticated_context_provider=authenticated_context_provider,
        candidate_target_provider=candidate_target_provider,
        planner=planner, critique_engine=critique_engine, scenario_engine=scenario_engine,
        cost_router=cost_router,
    )
