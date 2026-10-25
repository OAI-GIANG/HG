import unittest

from brain.council import (
    COUNCIL_CONTRACT_VERSION,
    CouncilError,
    CouncilMember,
    CritiqueCouncil,
)
from brain.tests.test_critique import FakeProvider, make_plan, make_task, response


class RaisingProvider:
    timeout_seconds = 1.0

    def generate_json(self, *, system_prompt, user_prompt):
        raise RuntimeError("provider error must not leak")


class RecordingProvider(FakeProvider):
    def __init__(self, result):
        super().__init__(result)
        self.system_prompts = []

    def generate_json(self, *, system_prompt, user_prompt):
        self.system_prompts.append(system_prompt)
        return super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt)


def member(name, role, provider):
    return CouncilMember(name=name, role=role, provider=provider)


def critique_kwargs(plan):
    return {
        "task_ref": plan["task_id"],
        "candidate_ref": plan["candidate_ref"],
        "policy_version": plan["policy_version"],
        "plan": plan,
        "task": make_task(plan),
        "evidence_refs": ["evidence:1"],
    }


class CritiqueCouncilTests(unittest.TestCase):
    def test_all_members_accept_and_roles_are_independent(self):
        plan = make_plan()
        first = RecordingProvider(response(plan))
        second = RecordingProvider(response(plan))
        council = CritiqueCouncil(members=[
            member("reviewer-architecture", "architecture", first),
            member("reviewer-evidence", "evidence", second),
        ])

        result = council.critique(**critique_kwargs(plan))

        self.assertEqual(result["contract_version"], COUNCIL_CONTRACT_VERSION)
        self.assertEqual(result["verdict"], "ACCEPT")
        self.assertEqual(result["council"]["completed_count"], 2)
        self.assertFalse(result["council"]["dissent_detected"])
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 1)
        self.assertIn("Review role: architecture", first.system_prompts[0])
        self.assertIn("Review role: evidence", second.system_prompts[0])
        self.assertEqual(result["authority_effect"], "NONE")
        self.assertFalse(result["side_effects_performed"])

    def test_dissent_is_preserved_and_accept_is_not_majority_voted(self):
        plan = make_plan()
        blocker = {
            "item_id": "step:S1", "assessment": "BLOCKER",
            "rationale": "A required precondition is not explicit.",
            "evidence_refs": ["evidence:1"],
        }
        revise = response(
            plan, verdict="REVISE", reviewed_items=[blocker],
            revision_requests=["Specify the missing precondition."], severity="MEDIUM",
        )
        council = CritiqueCouncil(members=[
            member("reviewer-a", "architecture", FakeProvider(response(plan))),
            member("reviewer-b", "adversarial", FakeProvider(revise)),
        ])

        result = council.critique(**critique_kwargs(plan))

        self.assertEqual(result["verdict"], "REVISE")
        self.assertTrue(result["council"]["dissent_detected"])
        self.assertEqual(result["revision_requests"], ["Specify the missing precondition."])

    def test_provider_failure_is_unresolved_and_blocks_acceptance(self):
        plan = make_plan()
        council = CritiqueCouncil(members=[
            member("reviewer-a", "architecture", FakeProvider(response(plan))),
            member("reviewer-b", "evidence", RaisingProvider()),
        ])

        result = council.critique(**critique_kwargs(plan))

        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["status"], "COUNCIL_REVIEW_INSUFFICIENT")
        self.assertEqual(result["council"]["completed_count"], 1)
        self.assertEqual(result["council"]["members"][1]["status"], "UNRESOLVED")
        self.assertNotIn("provider error", str(result))

    def test_reject_takes_precedence_over_member_failure(self):
        plan = make_plan()
        blocker = {
            "item_id": "step:S1", "assessment": "BLOCKER",
            "rationale": "The plan violates a stated stop condition.",
            "evidence_refs": ["evidence:1"],
        }
        rejected = response(
            plan, verdict="REJECT", reviewed_items=[blocker],
            revision_requests=["Stop and redesign the plan."], severity="HIGH",
        )
        council = CritiqueCouncil(members=[
            member("reviewer-a", "adversarial", FakeProvider(rejected)),
            member("reviewer-b", "evidence", RaisingProvider()),
        ])

        result = council.critique(**critique_kwargs(plan))

        self.assertEqual(result["verdict"], "REJECT")
        self.assertEqual(result["status"], "COUNCIL_REVIEW_INSUFFICIENT")

    def test_rejects_single_member_duplicate_names_and_timeout_over_budget(self):
        provider = FakeProvider(response(make_plan()))
        with self.assertRaisesRegex(CouncilError, "between 2 and 5"):
            CritiqueCouncil(members=[member("only", "architecture", provider)])
        with self.assertRaisesRegex(CouncilError, "unique"):
            CritiqueCouncil(members=[
                member("same", "architecture", provider),
                member("same", "evidence", FakeProvider(response(make_plan()))),
            ])
        with self.assertRaisesRegex(CouncilError, "timeout budget"):
            CritiqueCouncil(
                members=[
                    member("a", "architecture", provider),
                    member("b", "evidence", FakeProvider(response(make_plan()))),
                ],
                max_total_timeout_seconds=1,
            )


if __name__ == "__main__":
    unittest.main()
