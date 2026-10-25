import hashlib
import json
import unittest

from brain.critique import (
    CRITIQUE_CONTRACT_VERSION, CritiqueEngine, CritiqueError,
)


def make_plan():
    plan = {
        "contract_version": "hg.plan.v1",
        "status": "VALIDATED_PLAN_NOT_AUTHORIZED",
        "task_id": "task:critique-1",
        "candidate_ref": "candidate:1",
        "policy_version": "MAEP-1.2.0",
        "objective_summary": "Review a bounded candidate plan.",
        "assumptions": [],
        "steps": [{
            "step_id": "S1", "objective": "Inspect the supplied specification.",
            "effect_class": "READ_ONLY", "depends_on": [], "resource_ref": "repo://HG",
            "input_refs": ["evidence:1"], "expected_output": "A bounded acceptance map",
            "acceptance_criteria_indices": [0], "evidence_requirement_indices": [0],
            "verification_method": "Check the plan against its supplied specification",
            "risk_level": "LOW", "authorization_required": False, "preconditions": [],
            "recovery_action": "No side effect; repeat the bounded check",
            "stop_condition": "Stop if scope becomes unclear",
        }],
        "execution_order": ["S1"],
        "acceptance_coverage": {"0": ["S1"]},
        "evidence_coverage": {"0": ["S1"]},
        "context_record_refs": [],
        "authority_effect": "NONE",
        "side_effects_performed": False,
        "ready_to_execute": False,
        "limitations": ["This is a test fixture, not execution authority."],
    }
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    plan["plan_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return plan


def make_task(plan=None):
    plan = plan or make_plan()
    return {
        "task_id": plan["task_id"], "objective": "Review a bounded plan in the HG repository.",
        "scope": {"include": ["repo://HG"], "exclude": ["repo://HG/secrets"]},
        "inputs": [{"ref_id": "evidence:1", "kind": "FILE"}],
        "outputs": ["bounded critique"], "acceptance_criteria": ["stay within the declared scope"],
        "evidence_requirements": ["cite the supplied input"], "risks": ["unsupported inference"],
        "stop_conditions": ["candidate or policy mismatch"], "next_action": "stop if scope changes",
        "state": "ASSESSED", "policy_version": plan["policy_version"],
    }


def response(plan=None, **changes):
    plan = plan or make_plan()
    value = {
        "contract_version": CRITIQUE_CONTRACT_VERSION,
        "task_ref": plan["task_id"],
        "candidate_ref": plan["candidate_ref"],
        "policy_version": plan["policy_version"],
        "reviewed_plan_digest": plan["plan_digest"],
        "verdict": "ACCEPT",
        "reviewed_items": [{
            "item_id": "step:S1", "assessment": "NO_BLOCKER",
            "rationale": "No blocking issue identified in the supplied plan structure.",
            "evidence_refs": ["evidence:1"],
        }],
        "supported_claims": [],
        "unsupported_claims": [],
        "contradictions": [],
        "counterarguments": [],
        "missing_evidence": [],
        "uncertainty": [],
        "revision_requests": [],
        "severity": "LOW",
        "stop_reason": "",
    }
    value.update(changes)
    return value


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.timeout_seconds = 30.0
        self.result = result
        self.error = error
        self.calls = 0
        self.prompts = []

    def generate_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        self.prompts.append(user_prompt)
        if self.error:
            raise self.error
        return self.result if self.result is not None else response()


class CritiqueEngineTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.task = make_task(self.plan)
        self.provider = FakeProvider()
        self.engine = CritiqueEngine(provider=self.provider)

    def critique(self, **changes):
        args = {
            "task_ref": self.plan["task_id"],
            "candidate_ref": self.plan["candidate_ref"],
            "policy_version": self.plan["policy_version"],
            "plan": self.plan,
            "task": self.task,
        }
        args.update(changes)
        return self.engine.critique(**args)

    def test_provider_timeout_must_be_finite_and_at_most_30_seconds(self):
        self.provider.timeout_seconds = 31.0
        with self.assertRaisesRegex(CritiqueError, "must enforce timeout_seconds"):
            CritiqueEngine(provider=self.provider)
        self.provider.timeout_seconds = 30.0
        self.assertIsInstance(CritiqueEngine(provider=self.provider), CritiqueEngine)

    def test_provider_timeout_missing_is_blocked(self):
        provider = FakeProvider()
        del provider.timeout_seconds
        with self.assertRaisesRegex(CritiqueError, "must enforce timeout_seconds"):
            CritiqueEngine(provider=provider)

    def test_accept_is_unverified_and_has_no_authority(self):
        result = self.critique()
        self.assertEqual(result["verdict"], "ACCEPT")
        self.assertEqual(result["status"], "CRITIQUE_RECORDED_UNVERIFIED")
        self.assertEqual(result["epistemic_label"], "MODEL_CRITIQUE_NOT_FACT_VERIFICATION")
        self.assertEqual(result["authority_effect"], "NONE")
        self.assertLessEqual(result["provider_timeout_seconds"], 30)
        self.assertLessEqual(result["output_bytes"], self.engine.max_output_bytes)
        self.assertFalse(result["side_effects_performed"])
        self.assertEqual(self.provider.calls, 1)

    def test_tampered_plan_digest_rejected_before_provider(self):
        self.plan["steps"][0]["objective"] = "tampered"
        with self.assertRaisesRegex(CritiqueError, "valid digest"):
            self.critique()
        self.assertEqual(self.provider.calls, 0)

    def test_wrong_candidate_rejected_before_provider(self):
        with self.assertRaisesRegex(CritiqueError, "candidate_ref does not match"):
            self.critique(candidate_ref="candidate:attacker")
        self.assertEqual(self.provider.calls, 0)

    def test_wrong_policy_rejected_before_provider(self):
        with self.assertRaisesRegex(CritiqueError, "policy_version does not match"):
            self.critique(policy_version="MAEP-stale")
        self.assertEqual(self.provider.calls, 0)

    def test_fabricated_evidence_reference_rejected(self):
        self.provider.result = response(self.plan, counterarguments=[{
            "argument": "This claim is wrong.",
            "basis": "SOURCE_SUPPORTED",
            "evidence_refs": ["evidence:not-supplied"],
        }])
        with self.assertRaisesRegex(CritiqueError, "not supplied"):
            self.critique()

    def test_source_supported_counterargument_requires_reference(self):
        self.provider.result = response(self.plan, counterarguments=[{
            "argument": "Counterargument without evidence.",
            "basis": "SOURCE_SUPPORTED",
            "evidence_refs": [],
        }])
        with self.assertRaisesRegex(CritiqueError, "requires supplied evidence"):
            self.critique()

    def test_supported_claim_requires_existing_evidence_reference(self):
        self.provider.result = response(self.plan, supported_claims=[{
            "claim_id": "claim:1", "rationale": "Looks sound.", "evidence_refs": [],
        }])
        claims = [{"claim_id": "claim:1", "statement": "A test assertion.",
                  "source_refs": [], "evidence_refs": ["evidence:1"], "limitations": []}]
        with self.assertRaisesRegex(CritiqueError, "supported claims require"):
            self.critique(claims=claims)

    def test_accept_cannot_hide_missing_evidence(self):
        self.provider.result = response(self.plan, missing_evidence=[{
            "requirement": "implementation result",
            "reason": "No result was supplied.",
        }])
        with self.assertRaisesRegex(CritiqueError, "ACCEPT cannot contain"):
            self.critique()

    def test_revise_requires_revision_request(self):
        self.provider.result = response(self.plan, verdict="REVISE")
        with self.assertRaisesRegex(CritiqueError, "requires a blocker"):
            self.critique()

    def test_reject_requires_high_severity(self):
        self.provider.result = response(self.plan, verdict="REJECT", severity="LOW")
        with self.assertRaisesRegex(CritiqueError, "HIGH or CRITICAL"):
            self.critique()

    def test_insufficient_evidence_requires_gap_or_uncertainty(self):
        self.provider.result = response(self.plan, verdict="INSUFFICIENT_EVIDENCE")
        with self.assertRaisesRegex(CritiqueError, "must disclose"):
            self.critique()

    def test_unknown_claim_id_rejected(self):
        self.provider.result = response(self.plan, supported_claims=[{
            "claim_id": "claim:invented", "rationale": "Unsupported identification.",
            "evidence_refs": ["evidence:1"],
        }])
        with self.assertRaisesRegex(CritiqueError, "unknown claim"):
            self.critique()

    def test_scenario_result_must_be_bound_and_labelled_simulated(self):
        bad = {
            "task_ref": self.plan["task_id"], "candidate_ref": self.plan["candidate_ref"],
            "policy_version": self.plan["policy_version"], "status": "VERIFIED",
            "epistemic_label": "VERIFIED_FACT", "input_digest": "sha256:" + "a" * 64,
            "results": [],
        }
        with self.assertRaisesRegex(CritiqueError, "not labelled SIMULATED"):
            self.critique(scenario_result=bad)
        self.assertEqual(self.provider.calls, 0)

    def test_one_provider_call_only_no_critique_loop(self):
        self.provider.result = "{not json"
        with self.assertRaises(CritiqueError):
            self.critique()
        self.assertEqual(self.provider.calls, 1)

    def test_canonical_task_scope_is_revalidated_before_critique_provider(self):
        plan = self.plan
        plan["steps"][0]["resource_ref"] = "repo://HG/secrets"
        unsigned = dict(plan)
        unsigned.pop("plan_digest")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        plan["plan_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
        task = {
            "task_id": plan["task_id"], "objective": "Validate the plan scope.",
            "scope": {"include": ["repo://HG"], "exclude": ["repo://HG/secrets"]},
            "inputs": [{"ref_id": "evidence:1", "kind": "FILE"}],
            "outputs": ["review"], "acceptance_criteria": ["stay within scope"],
            "evidence_requirements": ["check source input"], "risks": ["scope escape"],
            "stop_conditions": ["candidate mismatch"], "next_action": "stop on escape",
            "state": "ASSESSED", "policy_version": plan["policy_version"],
        }
        with self.assertRaisesRegex(CritiqueError, "outside canonical task scope"):
            self.critique(task=task)
        self.assertEqual(self.provider.calls, 0)

    def test_accept_cannot_ignore_scenario_violation(self):
        scenario = {
            "status": "SIMULATED", "epistemic_label": "SIMULATED",
            "task_ref": self.plan["task_id"], "candidate_ref": self.plan["candidate_ref"],
            "policy_version": self.plan["policy_version"], "input_digest": "sha256:" + "a" * 64,
            "results": [{
                "scenario_id": "edge-case", "status": "STOPPED_RANGE_VIOLATION",
                "epistemic_label": "SIMULATED", "final_state": {"score": 10},
                "violations": [{"variable": "score", "reason": "range exceeded"}],
            }],
        }
        with self.assertRaisesRegex(CritiqueError, "cannot ignore stopped scenarios"):
            self.critique(scenario_result=scenario)
        self.assertEqual(self.provider.calls, 1)

    def test_plan_context_ref_is_not_trusted_without_reverification(self):
        plan = self.plan
        plan["context_record_refs"] = ["context:forged"]
        unsigned = dict(plan)
        unsigned.pop("plan_digest")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        plan["plan_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
        with self.assertRaisesRegex(CritiqueError, "not currently verified"):
            self.critique()
        self.assertEqual(self.provider.calls, 0)

    def test_verified_context_is_bound_to_plan_and_candidate_policy(self):
        plan = self.plan
        plan["context_record_refs"] = ["context:1"]
        unsigned = dict(plan)
        unsigned.pop("plan_digest")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        plan["plan_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
        self.provider.result = response(plan)
        context = [{
            "record_id": "context:1", "content": "A verified bounded context record.",
            "source_ref": "memory:record:1", "evidence_refs": ["evidence:context:1"],
            "verification_status": "VERIFIED", "candidate_ref": plan["candidate_ref"],
            "policy_version": plan["policy_version"],
        }]
        result = self.critique(verified_context=context)
        self.assertEqual(result["verdict"], "ACCEPT")
        self.assertIn("\"verified_context_records\"", self.provider.prompts[0])

    def test_provider_failure_is_fail_closed(self):
        engine = CritiqueEngine(provider=FakeProvider(error=TimeoutError()))
        with self.assertRaisesRegex(CritiqueError, "provider failed"):
            engine.critique(task_ref=self.plan["task_id"],
                            candidate_ref=self.plan["candidate_ref"],
                            policy_version=self.plan["policy_version"], plan=self.plan,
                            task=self.task)


if __name__ == "__main__":
    unittest.main()
