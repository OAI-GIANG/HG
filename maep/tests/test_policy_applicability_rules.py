"""N1 root fix: owner-approved policy rules classify Memory data-plane applicability.

MAEP_CONSTITUTION_V1_2 (line 50): MAEP-022 is not a blanket prerequisite for Memory
data-plane operations whose assessed effect does not change HG capability. The assessment
comes from the active, provenance-verified policy (D2), never from the caller. Rules are
narrow: only `memory:` resources bound to the configured Memory store, only NOT_REQUIRED.
"""
import unittest

from maep.native_authority import AuthorityError, TrustRootRecord
from maep.trusted_providers import TrustedApplicabilityProvider

STORE = "/data/hg/memory/hg.sqlite3"
CANDIDATE = {"candidate_ref": "candidate-1"}
RULE = {"rule_id": "memory-data-plane", "actions": ["READ", "WRITE"],
        "resource_prefix": "memory:", "classification": "NOT_REQUIRED"}


def memory_request(action="WRITE", kind="task", task="T-1", store=STORE):
    return {"action": action, "resource": f"memory:{kind}/{task} [store:{store}]",
            "task_ref": task, "scope": [f"memory:task:{task}:write"]}


class Root:
    root = TrustRootRecord.create(
        root_id="r", generation=1, created_at="2026-10-26T00:00:00Z", bootstrap_authorization_ref="f",
        verification_method="f", verification_material_ref="f", policy_change_rule_ref="f", evidence_ref="f")

    def load_active(self):
        return self.root


class Policy:
    def __init__(self, rules=None):
        self.rules = rules

    def load_active(self, root):
        policy = {"status": "ACTIVE", "version": "MAEP-1.2.0", "root_generation": 1, "provenance_verified": True,
                  "policy_digest": "sha256:" + "e" * 64, "approval_evidence_refs": ["approval:policy-1"]}
        if self.rules is not None:
            policy["applicability_rules"] = self.rules
        return policy


class Resolver:
    """No task-level record for the request (task absent or no reference)."""
    def __init__(self, record=None, error=None):
        self.record, self.error = record, error

    def resolve_applicability(self, request, candidate):
        if self.error:
            raise self.error
        return self.record

    def resolve_gate(self, request, candidate, policy):
        return None

    def resolve_evidence(self, ref):
        return {"evidence_id": ref, "candidate_ref": "candidate-1"}


class Verifier:
    def __init__(self, ok=True):
        self.ok = ok

    def validate_record_provenance(self, record, *, record_type, root, policy):
        return self.ok


def provider(rules=None, resolver=None, verifier=None, store=STORE):
    return TrustedApplicabilityProvider(root_store=Root(), policy_provider=Policy(rules),
                                        resolver=resolver or Resolver(), verifier=verifier or Verifier(),
                                        memory_store_path=store)


class PolicyApplicabilityRuleTests(unittest.TestCase):
    def test_without_rules_a_missing_record_still_blocks(self):
        with self.assertRaisesRegex(AuthorityError, "record missing"):
            provider().classify(memory_request(), CANDIDATE)

    def test_rule_classifies_memory_data_plane_without_a_task_record(self):
        result = provider([RULE]).classify(memory_request(), CANDIDATE)
        self.assertEqual(result["classification"], "NOT_REQUIRED")
        self.assertEqual(result["applicability_id"], "policy-rule:memory-data-plane")
        self.assertEqual(result["evidence_refs"], ["approval:policy-1"])
        self.assertEqual((result["action"], result["candidate_ref"]), ("WRITE", "candidate-1"))
        self.assertIn("policy:sha256:" + "e" * 64, result["facts_used"])

    def test_rule_never_applies_outside_the_configured_memory_store(self):
        for request in (memory_request(action="EXECUTE"),
                        memory_request(store="/other/hg.sqlite3"),
                        {"action": "WRITE", "resource": "memory:task/T-1", "task_ref": "T-1"},
                        {"action": "WRITE", "resource": "tool:fs.write", "task_ref": "T-1"},
                        {"action": "WRITE", "resource": f"tool:x [store:{STORE}]", "task_ref": "T-1"}):
            with self.subTest(resource=request["resource"], action=request["action"]):
                with self.assertRaises(AuthorityError):
                    provider([RULE]).classify(request, CANDIDATE)
        with self.assertRaises(AuthorityError):
            provider([RULE], store=None).classify(memory_request(), CANDIDATE)

    def test_malformed_or_ambiguous_rules_block_every_request(self):
        bad_sets = [
            "not-a-list",
            [dict(RULE, resource_prefix="tool:")],
            [dict(RULE, resource_prefix="")],
            [dict(RULE, classification="REQUIRED")],
            [dict(RULE, actions=[])],
            [dict(RULE, actions=["READ", "READ"])],
            [dict(RULE, extra=True)],
            [{k: v for k, v in RULE.items() if k != "rule_id"}],
            [RULE, dict(RULE)],                                      # duplicate rule id
            [RULE, dict(RULE, rule_id="second")],                    # two rules match
        ]
        for rules in bad_sets:
            with self.subTest(rules=rules):
                with self.assertRaises(AuthorityError):
                    provider(rules).classify(memory_request(), CANDIDATE)

    def test_record_lookup_error_is_not_converted_into_a_rule_decision(self):
        resolver = Resolver(error=AuthorityError("Memory evidence event-chain verification failed"))
        with self.assertRaisesRegex(AuthorityError, "event-chain"):
            provider([RULE], resolver=resolver).classify(memory_request(), CANDIDATE)

    def test_unapproved_task_record_blocks_even_when_a_rule_matches(self):
        record = {"candidate_ref": "candidate-1", "action": "EXECUTE", "resource": "tool:x"}
        with self.assertRaisesRegex(AuthorityError, "provenance"):
            provider([RULE], resolver=Resolver(record=record), verifier=Verifier(ok=False)).classify(
                memory_request(), CANDIDATE)

    def test_record_binding_another_action_defers_to_the_rule_for_memory_only(self):
        record = {"candidate_ref": "candidate-1", "action": "EXECUTE", "resource": "tool:fixture:echo",
                  "classification": "NOT_REQUIRED", "facts_used": ["f"], "evidence_refs": ["EV-1"],
                  "rule_version": "v", "applicability_id": "APP-1"}
        result = provider([RULE], resolver=Resolver(record=record)).classify(memory_request(), CANDIDATE)
        self.assertEqual(result["applicability_id"], "policy-rule:memory-data-plane")
        with self.assertRaisesRegex(AuthorityError, "does not bind"):
            provider([RULE], resolver=Resolver(record=record)).classify(
                {"action": "EXECUTE", "resource": "tool:other", "task_ref": "T-1"}, CANDIDATE)

    def test_record_binding_the_exact_request_wins_over_the_rule(self):
        request = memory_request()
        record = {"candidate_ref": "candidate-1", "action": "WRITE", "resource": request["resource"],
                  "classification": "REQUIRED", "facts_used": ["capability change"], "evidence_refs": ["EV-1"],
                  "rule_version": "v", "applicability_id": "APP-REQ"}
        result = provider([RULE], resolver=Resolver(record=record)).classify(request, CANDIDATE)
        self.assertEqual((result["classification"], result["applicability_id"]), ("REQUIRED", "APP-REQ"))


if __name__ == "__main__":
    unittest.main()
