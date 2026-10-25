import hashlib
import json
import unittest
from types import SimpleNamespace

from brain import (
    BrainOrchestrator, CritiqueEngine, PlanningEngine, ScenarioEngine,
    CRITIQUE_CONTRACT_VERSION,
)
from brain.planning import PLAN_CONTRACT_VERSION
from maep.core import POLICY_VERSION
from maep.native_authority import TrustRootRecord


TASK_REF = "task:critique-sim-integration"
CANDIDATE_REF = "candidate:integration-1"


def task_snapshot(*, candidate_ref=CANDIDATE_REF):
    return {
        "task": {
            "task_id": TASK_REF,
            "objective": "Validate a bounded HG plan and compare explicit scenarios.",
            "scope": {"include": ["repo://HG"], "exclude": ["repo://HG/secrets"]},
            "inputs": [{"ref_id": "input:spec", "kind": "FILE"}],
            "outputs": ["review result"],
            "acceptance_criteria": ["The plan remains within the HG scope."],
            "evidence_requirements": ["The plan cites its input and test evidence."],
            "risks": ["unsupported inference"],
            "stop_conditions": ["candidate or policy mismatch"],
            "next_action": "Review the plan",
            "state": "ASSESSED",
            "policy_version": POLICY_VERSION,
        },
        "candidate_ref": candidate_ref,
        "policy_status": "CURRENT",
    }


def valid_plan_candidate():
    return {
        "contract_version": PLAN_CONTRACT_VERSION,
        "task_id": TASK_REF,
        "objective_summary": "Inspect and validate the defined HG scope.",
        "assumptions": [],
        "steps": [{
            "step_id": "S1", "objective": "Inspect the supplied specification.",
            "effect_class": "READ_ONLY", "depends_on": [],
            "resource_ref": "repo://HG", "input_refs": ["input:spec"],
            "expected_output": "Scope and evidence checklist",
            "acceptance_criteria_indices": [0], "evidence_requirement_indices": [0],
            "verification_method": "Check the plan references and scope",
            "risk_level": "LOW", "authorization_required": False,
            "preconditions": [], "recovery_action": "No side effect; repeat the read-only check",
            "stop_condition": "Stop if candidate identity changes",
        }],
    }


def sim_request():
    return {
        "contract_version": "hg.scenario.v1",
        "scenario_id": "scenario-set:integration",
        "task_ref": TASK_REF,
        "candidate_ref": CANDIDATE_REF,
        "policy_version": POLICY_VERSION,
        "state_variables": [
            {"name": "score", "value": 10, "unit": "points", "min_value": 0, "max_value": 100}
        ],
        "transition_rules": [
            {"rule_id": "increment", "variable": "score", "operation": "ADD",
             "value": 1, "value_unit": "points"}
        ],
        "scenarios": [
            {"scenario_id": "baseline", "overrides": [], "assumptions": ["baseline"]}
        ],
        "horizon_steps": 2,
        "assumptions": ["The increment repeats each transition."],
    }


class FixedReasoningProvider:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def generate_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        return self.output


class CritiqueProvider:
    def __init__(self, *, verdict="ACCEPT", plan=None):
        self.timeout_seconds = 30.0
        self.verdict = verdict
        self.plan = plan
        self.calls = 0
        self.prompts = []

    def generate_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        self.prompts.append(user_prompt)
        assessment = "NO_BLOCKER" if self.verdict == "ACCEPT" else "BLOCKER"
        return {
            "contract_version": CRITIQUE_CONTRACT_VERSION,
            "task_ref": TASK_REF,
            "candidate_ref": CANDIDATE_REF,
            "policy_version": POLICY_VERSION,
            "reviewed_plan_digest": self.plan["plan_digest"],
            "verdict": self.verdict,
            "reviewed_items": [{
                "item_id": "step:S1", "assessment": assessment,
                "rationale": "Bounded integration-test rationale.",
                "evidence_refs": ["input:spec"],
            }],
            "supported_claims": [],
            "unsupported_claims": [],
            "contradictions": [],
            "counterarguments": [],
            "missing_evidence": [],
            "uncertainty": [],
            "revision_requests": ["Clarify the unsupported transition."] if self.verdict == "REVISE" else [],
            "severity": "HIGH" if self.verdict == "REJECT" else "LOW",
            "stop_reason": "",
        }


class TaskStore:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot or task_snapshot()
        self.calls = 0

    def get_task(self, task_id):
        self.calls += 1
        result = json.loads(json.dumps(self.snapshot))
        if isinstance(result.get("task"), dict):
            # Preserve an identity mismatch as a testable failure; do not rewrite task id.
            pass
        return result


class RootStore:
    def __init__(self):
        self.root = TrustRootRecord.create(
            root_id="root:critique-sim-test", generation=1,
            created_at="2026-10-24T00:00:00Z",
            bootstrap_authorization_ref="approved:test",
            verification_method="test fixture",
            verification_material_ref="fixture:root",
            policy_change_rule_ref="fixture:policy",
            evidence_ref="fixture:ledger",
        )

    def load_active(self):
        return self.root


class PolicyProvider:
    def load_active(self, root):
        return {
            "status": "ACTIVE", "version": POLICY_VERSION,
            "root_generation": root.generation, "provenance_verified": True,
            "policy_digest": "sha256:" + "b" * 64,
            "approval_evidence_refs": ["approval:test"],
        }


class CandidateProvider:
    def __init__(self, candidate_ref=CANDIDATE_REF):
        self.candidate_ref = candidate_ref

    def inspect(self, target):
        return {
            "verified": True, "repository": "OAI-GIANG/HG",
            "candidate_ref": self.candidate_ref,
            "source_manifest_digest": "sha256:" + "c" * 64,
        }


class NoopAdapter:
    def __init__(self):
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        raise AssertionError("Critique/simulation must never dispatch an adapter")


def make_plan():
    planner = PlanningEngine(provider=FixedReasoningProvider(valid_plan_candidate()))
    return planner.create_plan(task_snapshot())


def make_brain(*, plan, critique_verdict="ACCEPT", task_data=None, candidate_ref=CANDIDATE_REF):
    provider = CritiqueProvider(verdict=critique_verdict, plan=plan)
    authority = SimpleNamespace(
        root_store=RootStore(),
        policy_provider=PolicyProvider(),
        candidate_provider=CandidateProvider(candidate_ref),
    )
    adapter = NoopAdapter()
    brain = BrainOrchestrator(
        authority=authority,
        adapter_registry={"unused": adapter},
        idempotency_ledger=object(), receipt_sink=object(),
        task_store=TaskStore(task_data),
        critique_engine=CritiqueEngine(provider=provider),
        scenario_engine=ScenarioEngine(),
    )
    return brain, provider, adapter


class CritiqueSimulationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()

    def test_review_then_simulation_then_second_critique_is_bounded(self):
        brain, provider, adapter = make_brain(plan=self.plan)
        result = brain.review_and_simulate(
            task_ref=TASK_REF, candidate_target="current-candidate",
            plan=self.plan, scenario_request=sim_request(),
        )
        self.assertEqual(result["status"], "REVIEW_COMPLETE")
        self.assertEqual(result["simulation"]["epistemic_label"], "SIMULATED")
        self.assertEqual(result["final_critique"]["epistemic_label"], "MODEL_CRITIQUE_NOT_FACT_VERIFICATION")
        self.assertEqual(provider.calls, 2)
        self.assertIn('"scenario_result"', provider.prompts[1])
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(result["authority_effect"], "NONE")
        self.assertFalse(result["side_effects_performed"])

    def test_non_accepting_critique_stops_before_simulation(self):
        brain, provider, adapter = make_brain(plan=self.plan, critique_verdict="REVISE")
        result = brain.review_and_simulate(
            task_ref=TASK_REF, candidate_target="current-candidate",
            plan=self.plan, scenario_request=sim_request(),
        )
        self.assertEqual(result["status"], "STOPPED_CRITIQUE_REVISE")
        self.assertIsNone(result["simulation"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(adapter.calls, 0)

    def test_wrong_candidate_binding_blocks_before_critique(self):
        brain, provider, adapter = make_brain(plan=self.plan, candidate_ref="candidate:changed")
        with self.assertRaisesRegex(Exception, "candidate binding is unavailable"):
            brain.critique_plan(task_ref=TASK_REF, candidate_target="current-candidate", plan=self.plan)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(adapter.calls, 0)

    def test_simulation_request_identity_mismatch_blocks(self):
        brain, provider, adapter = make_brain(plan=self.plan)
        bad = sim_request()
        bad["candidate_ref"] = "candidate:attacker"
        with self.assertRaisesRegex(Exception, "scenario input identity"):
            brain.simulate_scenarios(task_ref=TASK_REF, candidate_target="current-candidate", request=bad)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(adapter.calls, 0)

    def test_missing_critique_provider_fails_closed(self):
        authority = SimpleNamespace(root_store=RootStore(), policy_provider=PolicyProvider(),
                                    candidate_provider=CandidateProvider())
        brain = BrainOrchestrator(
            authority=authority, adapter_registry={"unused": NoopAdapter()},
            idempotency_ledger=object(), receipt_sink=object(),
            task_store=TaskStore(), scenario_engine=ScenarioEngine(),
        )
        with self.assertRaisesRegex(Exception, "critique provider is not configured"):
            brain.critique_plan(task_ref=TASK_REF, candidate_target="current-candidate", plan=self.plan)


if __name__ == "__main__":
    unittest.main()
