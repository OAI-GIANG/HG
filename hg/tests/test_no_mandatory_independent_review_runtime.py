"""OD-IR-20261109 on the HG runtime path: no task waits for an independent reviewer.

The owner decision `docs/governance/OWNER_DECISION_OD-IR-20261109.md` sets
`INDEPENDENT_REVIEW_REQUIRED = false`. These tests run real tasks through BrainOrchestrator,
ActionGateway, AcceptanceGate and the canonical TaskStore and check the decision's adversarial
cases:

1-2, 4-5. No reviewer at all (no human, no Gemini or other AI, no second agent): the executor's
          own verifier evidence closes the task.
3.        One identity only: the executing principal is the only principal involved; nothing
          compares a reviewer identity with the author.
6.        No external approval: the grant carries no approval condition and the task still closes.
8.        Real technical failures still stop the task: a failing verifier, a missing verifier and
          a missing authorization are refused exactly as before.

Case 7 (a HOLD held only for independent review) is a record and GitHub state, not runtime
code; it is handled in ledger reconciliation 2026-11-09 C.
These are characterization tests: the runtime path never enforced an independent review, and
they keep it that way.
"""
from maep.ledger import read_events
from hg.brain.orchestrator import COLLECTOR
from hg.runtime import DEFAULT_PRINCIPAL
from hg.tests.support import TempDirMixin, content_verifier, grant, make_task, write_step

REVIEW_TYPES = {"REVIEW"}


class NoIndependentReviewerTests(TempDirMixin):
    def test_task_closes_with_no_reviewer_of_any_kind(self):
        final = self.build([grant()]).orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        evidence = list(final["evidence"].values())
        self.assertTrue(evidence)
        self.assertFalse([e for e in evidence if e["evidence_type"] in REVIEW_TYPES],
                         "closure needed no review evidence")
        self.assertEqual({e["collector"] for e in evidence}, {COLLECTOR},
                         "the executor's own verification is the only evidence")

    def test_single_identity_and_no_external_approval_close_the_task(self):
        only = grant()
        self.assertEqual(only["principal"], DEFAULT_PRINCIPAL)
        self.assertEqual(only["conditions"], [], "no approval condition on the grant")
        final = self.build([only]).orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        events = read_events(self.workdir / "tasks.jsonl")
        principals = {e["data"].get("principal") for e in events
                      if isinstance(e.get("data"), dict) and e["data"].get("principal")}
        self.assertLessEqual(principals, {DEFAULT_PRINCIPAL}, "no second principal was involved")


class TechnicalControlsStillHoldTests(TempDirMixin):
    def test_failing_verifier_still_blocks_closure(self):
        rt = self.build([grant()], verifiers={"AC-1": content_verifier(self.root, expected="other")})
        final = rt.orch.execute_task(make_task(), [write_step()])
        self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")

    def test_missing_verifier_is_unverified_not_closed(self):
        rt = self.build([grant()], verifiers={})
        self.assertEqual(rt.orch.execute_task(make_task(), [write_step()])["task"]["state"], "UNVERIFIED")

    def test_missing_authorization_still_prevents_the_effect(self):
        final = self.build([]).orch.execute_task(make_task(), [write_step()])
        self.assertNotEqual(final["task"]["state"], "CLOSED_VERIFIED")
        self.assertFalse((self.root / "out/hello.txt").exists(), "no effect without an ALLOW")
