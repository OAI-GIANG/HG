import unittest

from brain.cost_router import (
    CostRouter, CostRouterError, CostRouterPolicy, RouteRequest,
    ROUTER_CONTRACT_VERSION,
)


class CostRouterTests(unittest.TestCase):
    def setUp(self):
        self.policy = CostRouterPolicy(
            max_reasoning_calls=2, max_revision_calls=1, max_council_calls=1,
            council_min_risk="HIGH", council_on_ambiguity=True,
            council_on_conflict=True,
        )
        self.router = CostRouter(policy=self.policy)

    def request(self, **overrides):
        values = dict(
            risk_level="LOW", memory_state="NOT_NEEDED",
            deterministic_sufficient=False, reasoning_needed=True,
            ambiguity_detected=False, conflict_detected=False,
            reasoning_calls_used=0, revision_calls_used=0, council_calls_used=0,
            reasoning_provider_available=True, council_provider_available=True,
        )
        values.update(overrides)
        return RouteRequest(**values)

    def test_deterministic_path_avoids_model_call(self):
        result = self.router.route(self.request(deterministic_sufficient=True, reasoning_needed=False))
        self.assertEqual(result.decision, "DETERMINISTIC_ONLY")
        self.assertFalse(result.provider_invoked)
        self.assertEqual(result.authority_effect, "NONE")

    def test_current_verified_memory_can_be_reused_when_reasoning_unneeded(self):
        result = self.router.route(self.request(memory_state="CURRENT_VERIFIED", reasoning_needed=False))
        self.assertEqual(result.decision, "REUSE_VERIFIED_EXPERIENCE")

    def test_stale_memory_never_becomes_reuse_shortcut(self):
        result = self.router.route(self.request(memory_state="STALE", reasoning_needed=False))
        self.assertEqual(result.decision, "BLOCKED")

    def test_unknown_memory_blocks_if_no_independent_reasoning_route(self):
        result = self.router.route(self.request(memory_state="UNKNOWN", reasoning_needed=False))
        self.assertEqual(result.reason_code, "MEMORY_APPLICABILITY_NOT_ESTABLISHED")

    def test_conflict_uses_bounded_council_only_when_policy_allows(self):
        result = self.router.route(self.request(memory_state="CONFLICTING", conflict_detected=True))
        self.assertEqual(result.decision, "CRITIQUE_COUNCIL")

    def test_conflict_blocks_when_council_budget_exhausted(self):
        result = self.router.route(self.request(memory_state="CONFLICTING", conflict_detected=True, council_calls_used=1))
        self.assertEqual(result.decision, "BLOCKED")
        self.assertEqual(result.reason_code, "CONFLICT_REQUIRES_EVIDENCE_RESOLUTION")

    def test_high_risk_requires_council(self):
        result = self.router.route(self.request(risk_level="HIGH"))
        self.assertEqual(result.decision, "CRITIQUE_COUNCIL")
        self.assertEqual(result.reason_code, "RISK_OR_AMBIGUITY_POLICY_GATE")

    def test_high_risk_blocks_if_council_provider_unavailable(self):
        result = self.router.route(self.request(risk_level="HIGH", council_provider_available=False))
        self.assertEqual(result.decision, "BLOCKED")

    def test_reasoning_budget_exhaustion_fails_closed(self):
        result = self.router.route(self.request(reasoning_calls_used=2))
        self.assertEqual(result.reason_code, "REASONING_BUDGET_EXHAUSTED")

    def test_revision_budget_exhaustion_fails_closed(self):
        result = self.router.route(self.request(revision_calls_used=2))
        self.assertEqual(result.reason_code, "REVISION_BUDGET_EXHAUSTED")

    def test_provider_unavailable_fails_closed(self):
        result = self.router.route(self.request(reasoning_provider_available=False))
        self.assertEqual(result.reason_code, "REASONING_PROVIDER_UNAVAILABLE")

    def test_ambiguity_gates_council(self):
        result = self.router.route(self.request(ambiguity_detected=True))
        self.assertEqual(result.decision, "CRITIQUE_COUNCIL")

    def test_decision_is_non_authorizing_and_never_invokes_provider(self):
        result = self.router.route(self.request())
        self.assertEqual(result.contract_version, ROUTER_CONTRACT_VERSION)
        self.assertFalse(result.provider_invoked)
        self.assertEqual(result.authority_effect, "NONE")

    def test_invalid_policy_must_not_guess(self):
        with self.assertRaises(CostRouterError):
            CostRouterPolicy(2, 1, 1, "UNKNOWN", False, False)

    def test_invalid_input_counter_rejected(self):
        with self.assertRaises(CostRouterError):
            self.router.route(self.request(reasoning_calls_used=-1))


if __name__ == "__main__":
    unittest.main()
