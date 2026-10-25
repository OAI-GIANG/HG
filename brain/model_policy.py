"""Deterministic L0-L4 model-selection policy; no provider calls or side effects."""
from __future__ import annotations

from dataclasses import dataclass

MODEL_POLICY_VERSION = "hg.model-selection.v1"


class ModelPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ModelPolicy:
    allow_local_model: bool = True
    allow_free_critic: bool = True
    allow_deepseek: bool = False
    max_deepseek_calls: int = 0
    max_local_retry_calls: int = 1
    max_deepseek_tokens_per_call: int = 2048

    def __post_init__(self):
        for name in ("allow_local_model", "allow_free_critic", "allow_deepseek"):
            if not isinstance(getattr(self, name), bool):
                raise ModelPolicyError(name + " must be boolean")
        if isinstance(self.max_deepseek_calls, bool) or not isinstance(self.max_deepseek_calls, int) or self.max_deepseek_calls < 0:
            raise ModelPolicyError("max_deepseek_calls must be a non-negative integer")
        if isinstance(self.max_local_retry_calls, bool) or not isinstance(self.max_local_retry_calls, int) or self.max_local_retry_calls < 0:
            raise ModelPolicyError("max_local_retry_calls must be a non-negative integer")
        if (isinstance(self.max_deepseek_tokens_per_call, bool)
                or not isinstance(self.max_deepseek_tokens_per_call, int)
                or not 1 <= self.max_deepseek_tokens_per_call <= 8192):
            raise ModelPolicyError("max_deepseek_tokens_per_call must be between 1 and 8192")
        if not self.allow_deepseek and self.max_deepseek_calls != 0:
            raise ModelPolicyError("DeepSeek call budget must be zero while DeepSeek is disabled")


@dataclass(frozen=True)
class ModelSelectionRequest:
    deterministic_sufficient: bool
    verified_memory_applicable: bool
    local_model_available: bool
    task_requires_reasoning: bool
    local_result_insufficient: bool = False
    local_provider_failed: bool = False
    critic_triggered: bool = False
    critic_available: bool = False
    high_complexity: bool = False
    deepseek_calls_used: int = 0
    deepseek_token_budget_remaining: int = 0
    local_retry_calls_used: int = 0


@dataclass(frozen=True)
class ModelSelection:
    level: str
    provider: str | None
    reason_code: str
    estimated_cost_known: bool = False
    provider_invoked: bool = False
    max_output_tokens: int | None = None


class ModelSelectionPolicy:
    """Select the cheapest permitted path; escalation is opt-in and evidence-bound."""

    def __init__(self, *, policy: ModelPolicy):
        if not isinstance(policy, ModelPolicy):
            raise ModelPolicyError("explicit ModelPolicy is required")
        self.policy = policy

    def select(self, request: ModelSelectionRequest) -> ModelSelection:
        if not isinstance(request, ModelSelectionRequest):
            raise ModelPolicyError("ModelSelectionRequest is required")
        for name in ("deterministic_sufficient", "verified_memory_applicable", "local_model_available",
                     "task_requires_reasoning", "local_result_insufficient", "local_provider_failed",
                     "critic_triggered", "critic_available", "high_complexity"):
            if not isinstance(getattr(request, name), bool):
                raise ModelPolicyError(name + " must be boolean")
        for name in ("deepseek_calls_used", "deepseek_token_budget_remaining", "local_retry_calls_used"):
            value = getattr(request, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ModelPolicyError(name + " must be a non-negative integer")

        if request.deterministic_sufficient and not request.task_requires_reasoning:
            return ModelSelection("L0", None, "DETERMINISTIC_SUFFICIENT")
        if request.verified_memory_applicable and not request.task_requires_reasoning:
            return ModelSelection("L0", None, "VERIFIED_MEMORY_APPLICABLE")
        if not request.task_requires_reasoning:
            return ModelSelection("BLOCKED", None, "NO_SAFE_EXECUTION_PATH")

        if (self.policy.allow_local_model and request.local_model_available
                and not request.local_result_insufficient and not request.local_provider_failed):
            return ModelSelection("L1", "LOCAL_MODEL", "LOCAL_FIRST")

        local_retry_needed = request.local_result_insufficient or request.local_provider_failed
        if (local_retry_needed and self.policy.allow_local_model and request.local_model_available
                and request.local_retry_calls_used < self.policy.max_local_retry_calls):
            return ModelSelection("L2", "LOCAL_MODEL_RETRY", "BOUNDED_LOCAL_RETRY_BEFORE_ESCALATION")

        if request.critic_triggered and self.policy.allow_free_critic and request.critic_available:
            return ModelSelection("L3", "FREE_CRITIC", "EXPLICIT_CRITIC_TRIGGER")

        escalation_needed = request.local_result_insufficient or request.local_provider_failed
        if (escalation_needed and request.high_complexity and self.policy.allow_deepseek
                and request.deepseek_calls_used < self.policy.max_deepseek_calls
                and request.deepseek_token_budget_remaining > 0):
            return ModelSelection(
                "L4", "DEEPSEEK", "LOCAL_INSUFFICIENT_AND_ESCALATION_ALLOWED",
                max_output_tokens=min(self.policy.max_deepseek_tokens_per_call,
                                      request.deepseek_token_budget_remaining),
            )
        if request.local_model_available and self.policy.allow_local_model:
            return ModelSelection("L1", "LOCAL_MODEL", "LOCAL_FALLBACK_BEFORE_PAID_ESCALATION")
        return ModelSelection("BLOCKED", None, "NO_ALLOWED_PROVIDER_OR_ESCALATION_GATE_FAILED")
