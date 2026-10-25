import unittest

from brain.model_policy import (
    ModelPolicy, ModelPolicyError, ModelSelectionPolicy, ModelSelectionRequest,
)


def req(**changes):
    values = dict(
        deterministic_sufficient=False, verified_memory_applicable=False,
        local_model_available=True, task_requires_reasoning=True,
    )
    values.update(changes)
    return ModelSelectionRequest(**values)


class ModelSelectionPolicyTests(unittest.TestCase):
    def test_deterministic_and_verified_memory_avoid_models(self):
        policy = ModelSelectionPolicy(policy=ModelPolicy())
        self.assertEqual(policy.select(req(deterministic_sufficient=True, task_requires_reasoning=False)).level, "L0")
        self.assertEqual(policy.select(req(verified_memory_applicable=True, task_requires_reasoning=False)).level, "L0")

    def test_simple_reasoning_defaults_to_local_model(self):
        selected = ModelSelectionPolicy(policy=ModelPolicy()).select(req())
        self.assertEqual((selected.level, selected.provider), ("L1", "LOCAL_MODEL"))

    def test_local_retry_precedes_paid_escalation(self):
        policy = ModelSelectionPolicy(policy=ModelPolicy(allow_deepseek=True, max_deepseek_calls=1))
        first = policy.select(req(local_result_insufficient=True, high_complexity=True,
                                  deepseek_token_budget_remaining=100))
        self.assertEqual((first.level, first.provider), ("L2", "LOCAL_MODEL_RETRY"))
        second = policy.select(req(local_result_insufficient=True, local_retry_calls_used=1,
                                   high_complexity=True, deepseek_token_budget_remaining=100))
        self.assertEqual((second.level, second.provider), ("L4", "DEEPSEEK"))

    def test_deepseek_requires_explicit_high_complexity_escalation_and_budgets(self):
        policy = ModelSelectionPolicy(policy=ModelPolicy(allow_deepseek=True, max_deepseek_calls=1))
        base = req(local_result_insufficient=True, high_complexity=True,
                   local_model_available=False, deepseek_token_budget_remaining=100)
        selected = policy.select(base)
        self.assertEqual(selected.provider, "DEEPSEEK")
        self.assertEqual(selected.max_output_tokens, 100)
        constrained = policy.select(req(local_result_insufficient=True, high_complexity=True,
                                         local_model_available=False, deepseek_token_budget_remaining=7))
        self.assertEqual(constrained.max_output_tokens, 7)
        self.assertEqual(policy.select(req(local_result_insufficient=True, high_complexity=False,
                                           local_model_available=False, deepseek_token_budget_remaining=100)).level, "BLOCKED")
        self.assertEqual(policy.select(req(local_result_insufficient=True, high_complexity=True,
                                           local_model_available=False, deepseek_token_budget_remaining=0)).level, "BLOCKED")
        self.assertEqual(policy.select(req(local_result_insufficient=True, high_complexity=True,
                                           local_model_available=False, deepseek_calls_used=1,
                                           deepseek_token_budget_remaining=100)).level, "BLOCKED")

    def test_free_critic_is_optional_and_triggered(self):
        policy = ModelSelectionPolicy(policy=ModelPolicy())
        selected = policy.select(req(critic_triggered=True, critic_available=True,
                                     local_model_available=False))
        self.assertEqual((selected.level, selected.provider), ("L3", "FREE_CRITIC"))

    def test_disabled_deepseek_cannot_have_positive_budget(self):
        with self.assertRaises(ModelPolicyError):
            ModelPolicy(allow_deepseek=False, max_deepseek_calls=1)


if __name__ == "__main__":
    unittest.main()
