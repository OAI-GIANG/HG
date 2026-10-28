import hashlib
import json
import unittest

from maep.native_authority import (
    Applicability, Decision, NativePolicyEngine, TrustRootRecord,
)
from maep.policy_templates import (
    POLICY_SCHEMA_V2, PolicyTemplateError, policy_rule_matches_v2,
    resource_grant_matches, resource_template_matches, safe_relative_path,
    scope_grants_cover, validate_effective_policy_v2, validate_policy_source_v2,
)


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def root_record():
    return TrustRootRecord.create(
        root_id="test-root", generation=1, created_at="2026-10-28T00:00:00Z",
        bootstrap_authorization_ref="fixture:owner", verification_method="fixture-only",
        verification_material_ref="fixture://root", policy_change_rule_ref="fixture://label",
        evidence_ref="fixture://bootstrap",
    )


def v2_policy(rules=None):
    policy = {
        "schema_version": POLICY_SCHEMA_V2,
        "status": "ACTIVE",
        "version": "hg-policy-v2-test",
        "root_generation": 1,
        "approval_evidence_refs": ["owner:test-policy-v2"],
        "grant_ttl_seconds": 30,
        "rules": rules if rules is not None else [{
            "action": "READ",
            "resource": "memory:task/{task_id} [store:/state/memory.sqlite3]",
            "match_mode": "TEMPLATE",
            "effect": "ALLOW",
            "scope": ["memory:task:{task_id}:read"],
        }],
    }
    return policy


class PolicyTemplateUnitTests(unittest.TestCase):
    def test_task_resource_is_bound_to_the_request_task_reference(self):
        template = "memory:task/{task_id} [store:/state/memory.sqlite3]"
        self.assertTrue(resource_template_matches(
            template, "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1"))
        self.assertFalse(resource_template_matches(
            template, "memory:task/T-2 [store:/state/memory.sqlite3]", "T-1"))
        self.assertFalse(resource_template_matches(
            template, "memory:task/T-1 [store:/other/memory.sqlite3]", "T-1"))
        self.assertFalse(resource_template_matches(
            template, "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1/../T-2"))
        self.assertFalse(resource_template_matches(
            "memory:task/{unknown} [store:/state/memory.sqlite3]",
            "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1"))
        self.assertFalse(resource_template_matches(
            "memory:task/{task_id}", "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1"))

    def test_evidence_and_knowledge_templates_are_segment_bounded(self):
        cases = (
            ("memory:evidence/{evidence_id} [store:/state/memory.sqlite3]",
             "memory:evidence/EV-1 [store:/state/memory.sqlite3]"),
            ("memory:knowledge/verify/{claim_id} [store:/state/memory.sqlite3]",
             "memory:knowledge/verify/CLM-1 [store:/state/memory.sqlite3]"),
            ("memory:knowledge/task/{task_id} [store:/state/memory.sqlite3]",
             "memory:knowledge/task/T-1 [store:/state/memory.sqlite3]"),
        )
        for template, resource in cases:
            with self.subTest(template=template):
                self.assertTrue(resource_template_matches(template, resource, "T-1"))
                if "{task_id}" in template:
                    self.assertFalse(resource_template_matches(template, resource.replace("T-1", "T-2"), "T-1"))
        self.assertFalse(resource_template_matches(
            "memory:evidence/{evidence_id} [store:/state/memory.sqlite3]",
            "memory:evidence/../secret [store:/state/memory.sqlite3]", "T-1"))
        self.assertFalse(resource_template_matches(
            "memory:knowledge/{claim_id} [store:/state/memory.sqlite3]",
            "memory:knowledge/CLM/extra [store:/state/memory.sqlite3]", "T-1"))

    def test_file_template_rejects_absolute_and_traversal_paths(self):
        self.assertTrue(resource_template_matches("file:{relative_path}", "file:out/report.txt", "T-1"))
        for path in (
            "file:/etc/passwd", "file:../secret", "file:out/../secret",
            "file:out//secret", "file:out/", "file:out\\secret", "file:out/./secret",
        ):
            with self.subTest(path=path):
                self.assertFalse(resource_template_matches("file:{relative_path}", path, "T-1"))
        self.assertFalse(safe_relative_path(""))

    def test_scope_templates_bind_only_supported_task_scopes(self):
        self.assertTrue(scope_grants_cover(
            ["memory:task:T-1:read"],
            ["memory:task:{task_id}:read"], "T-1", templates_allowed=True))
        self.assertFalse(scope_grants_cover(
            ["memory:task:T-2:read"],
            ["memory:task:{task_id}:read"], "T-1", templates_allowed=True))
        self.assertFalse(scope_grants_cover(
            ["memory:task:T-1:admin"],
            ["memory:task:{task_id}:admin"], "T-1", templates_allowed=True))
        self.assertFalse(scope_grants_cover(
            ["memory:task:T-1:read", "memory:task:T-1:write"],
            ["memory:task:{task_id}:read"], "T-1", templates_allowed=True))

    def test_session_resource_grants_require_explicit_v2_template_mode(self):
        self.assertTrue(resource_grant_matches(
            ["memory:task/{task_id} [store:/state/memory.sqlite3]"],
            "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1", templates_allowed=True))
        self.assertFalse(resource_grant_matches(
            ["memory:task/{task_id} [store:/state/memory.sqlite3]"],
            "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1", templates_allowed=False))
        self.assertFalse(resource_grant_matches(
            ["memory:task/{unknown} [store:/state/memory.sqlite3]"],
            "memory:task/T-1 [store:/state/memory.sqlite3]", "T-1", templates_allowed=True))

    def test_v2_source_policy_validates_and_rejects_unknown_or_unsafe_rules(self):
        policy = v2_policy()
        validate_policy_source_v2(policy, expected_root_generation=1)
        with self.assertRaises(PolicyTemplateError):
            validate_policy_source_v2(policy, expected_root_generation=2)
        bad_cases = []
        bad_cases.append(dict(policy, extra="not allowed"))
        bad_cases.append(dict(policy, grant_ttl_seconds=0))
        bad_cases.append(dict(policy, approval_evidence_refs=[]))
        bad_cases.append(dict(policy, rules=[dict(policy["rules"][0], resource="memory:task/{user_input} [store:/state/memory.sqlite3]")]))
        bad_cases.append(dict(policy, rules=[dict(policy["rules"][0], match_mode="EXACT")]))
        bad_cases.append(dict(policy, rules=[dict(policy["rules"][0], scope=["memory:task:{task_id}:admin"])]))
        bad_cases.append(dict(policy, rules=[dict(policy["rules"][0], extra="not allowed")]))
        for bad in bad_cases:
            with self.subTest(bad=bad):
                with self.assertRaises(PolicyTemplateError):
                    validate_policy_source_v2(bad)

    def test_v2_applicability_rules_follow_trusted_provider_contract(self):
        policy = v2_policy()
        policy["applicability_rules"] = [{
            "rule_id": "memory-read", "actions": ["READ"],
            "resource_prefix": "memory:", "classification": "NOT_REQUIRED",
        }]
        validate_policy_source_v2(policy, expected_root_generation=1)
        invalid_rules = [
            [{"rule_id": "bad", "actions": ["READ"], "resource_prefix": "file:", "classification": "NOT_REQUIRED"}],
            [{"rule_id": "bad", "actions": ["READ"], "resource_prefix": "memory:", "classification": "REQUIRED"}],
            [{"rule_id": "bad", "actions": ["READ", "READ"], "resource_prefix": "memory:", "classification": "NOT_REQUIRED"}],
            [{"rule_id": "bad", "actions": ["READ"], "resource_prefix": "memory:", "classification": "NOT_REQUIRED", "extra": True}],
        ]
        for rules in invalid_rules:
            with self.subTest(rules=rules):
                broken = dict(policy, applicability_rules=rules)
                with self.assertRaises(PolicyTemplateError):
                    validate_policy_source_v2(broken)

    def test_effective_v2_policy_requires_verified_provenance_and_digest(self):
        policy = v2_policy()
        effective = dict(policy, policy_digest=digest(policy), provenance_verified=True)
        validate_effective_policy_v2(effective, expected_root_generation=1)
        with self.assertRaises(PolicyTemplateError):
            validate_effective_policy_v2(dict(effective, provenance_verified=False))
        with self.assertRaises(PolicyTemplateError):
            validate_effective_policy_v2(dict(effective, policy_digest="sha256:broken"))

    def test_rule_match_is_exactly_task_and_scope_bound(self):
        rule = v2_policy()["rules"][0]
        self.assertTrue(policy_rule_matches_v2(
            rule, action="READ", resource="memory:task/T-1 [store:/state/memory.sqlite3]",
            requested_scopes=["memory:task:T-1:read"], task_ref="T-1"))
        self.assertFalse(policy_rule_matches_v2(
            rule, action="READ", resource="memory:task/T-2 [store:/state/memory.sqlite3]",
            requested_scopes=["memory:task:T-2:read"], task_ref="T-1"))
        self.assertFalse(policy_rule_matches_v2(
            rule, action="WRITE", resource="memory:task/T-1 [store:/state/memory.sqlite3]",
            requested_scopes=["memory:task:T-1:read"], task_ref="T-1"))


class _RootStore:
    def __init__(self, root):
        self.root = root
    def load_active(self):
        return self.root


class _Principal:
    def __init__(self, *, templates=True):
        self.templates = templates
    def resolve(self, context):
        if context != "authenticated-session":
            return None
        return {
            "principal_id": "owner-test", "status": "ACTIVE", "verified": True,
            "identity_evidence_ref": "test:identity", "capabilities": ["READ", "WRITE"],
            "resource_scopes": (["memory:task/{task_id} [store:/state/memory.sqlite3]",
                                 "memory:evidence/{evidence_id} [store:/state/memory.sqlite3]",
                                 "memory:knowledge/{claim_id} [store:/state/memory.sqlite3]",
                                 "memory:knowledge/verify/{claim_id} [store:/state/memory.sqlite3]"] if self.templates
                                else ["memory:task/T-1 [store:/state/memory.sqlite3]"]),
            "allowed_scopes": (["memory:task:{task_id}:read", "memory:task:{task_id}:evidence:read",
                                "memory:task:{task_id}:knowledge:read", "memory:task:{task_id}:knowledge:verify"]
                               if self.templates else ["memory:task:T-1:read"]),
        }


class _Candidate:
    def inspect(self, target):
        if target != "known-candidate":
            return None
        return {"verified": True, "repository": "OAI-GIANG/HG",
                "source_manifest_digest": "sha256:" + "0" * 64,
                "candidate_ref": "candidate:test"}


class _Policy:
    def __init__(self, policy):
        self.policy = policy
    def load_active(self, root):
        return self.policy


class _Applicability:
    def classify(self, request, candidate):
        return {"verified": True, "classification": Applicability.NOT_REQUIRED.value,
                "candidate_ref": candidate["candidate_ref"], "action": request["action"],
                "resource": request["resource"], "applicability_id": "app:test",
                "rule_version": "rules:test", "facts_used": ["unit-test"],
                "evidence_refs": ["evidence:applicability"]}


class _Gate:
    def evaluate(self, request, candidate, policy):
        raise AssertionError("NOT_REQUIRED applicability must not invoke the gate")


class _Sink:
    def __init__(self):
        self.events = []
    def append(self, event):
        self.events.append(event)
        return "ledger:test"


class PolicyV2EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = root_record()
        self.sink = _Sink()
        self.policy_source = v2_policy()
        self.policy = dict(self.policy_source, policy_digest=digest(self.policy_source),
                           provenance_verified=True)
        self.engine = self._engine(self.policy, _Principal(templates=True))
        self.request = {"action": "READ", "resource": "memory:task/T-1 [store:/state/memory.sqlite3]",
                        "scope": ["memory:task:T-1:read"], "task_ref": "T-1"}

    def _engine(self, policy, principal):
        return NativePolicyEngine(
            root_store=_RootStore(self.root), principal_provider=principal,
            candidate_provider=_Candidate(), policy_provider=_Policy(policy),
            applicability_provider=_Applicability(), gate_provider=_Gate(), evidence_sink=self.sink,
        )

    def authorize(self, request=None):
        return self.engine.authorize(
            request or self.request, authenticated_context="authenticated-session",
            candidate_target="known-candidate")

    def test_v2_template_allows_only_matching_task(self):
        result = self.authorize()
        self.assertIs(result.decision, Decision.ALLOW)
        self.assertEqual(result.resource, "memory:task/T-1 [store:/state/memory.sqlite3]")
        cross_task = dict(self.request, resource="memory:task/T-2 [store:/state/memory.sqlite3]",
                          scope=["memory:task:T-2:read"])
        self.assertIs(self.authorize(cross_task).decision, Decision.DENY)

    def test_v2_evidence_knowledge_scope_must_match_request_task(self):
        cases = (
            ("memory:evidence/{evidence_id} [store:/state/memory.sqlite3]",
             "memory:evidence/EV-1 [store:/state/memory.sqlite3]", "memory:task:T-1:evidence:read"),
            ("memory:knowledge/{claim_id} [store:/state/memory.sqlite3]",
             "memory:knowledge/CL-1 [store:/state/memory.sqlite3]", "memory:task:T-1:knowledge:read"),
            ("memory:knowledge/verify/{claim_id} [store:/state/memory.sqlite3]",
             "memory:knowledge/verify/CL-1 [store:/state/memory.sqlite3]", "memory:task:T-1:knowledge:verify"),
        )
        for template, resource, task_scope in cases:
            with self.subTest(resource=resource):
                source = v2_policy(rules=[{
                    "action": "READ", "resource": template, "match_mode": "TEMPLATE",
                    "effect": "ALLOW", "scope": [task_scope],
                }])
                principal = _Principal(templates=True)
                original_resolve = principal.resolve
                cross_scope = task_scope.replace("T-1", "T-2")
                def resolve_with_cross_task_grant(context, _resolve=original_resolve, _scope=cross_scope):
                    record = _resolve(context)
                    record["allowed_scopes"] = list(record["allowed_scopes"]) + [_scope]
                    return record
                principal.resolve = resolve_with_cross_task_grant
                self.engine = self._engine(
                    dict(source, policy_digest=digest(source), provenance_verified=True), principal)
                allowed = dict(self.request, resource=resource, scope=[task_scope])
                result = self.authorize(allowed)
                self.assertIs(result.decision, Decision.ALLOW, result.reason_codes)
                cross_task = dict(allowed, task_ref="T-2", scope=[cross_scope])
                # Principal deliberately grants both scopes; the policy rule must still
                # bind this evidence/knowledge operation to T-1 and deny T-2.
                self.assertIs(self.authorize(cross_task).decision, Decision.DENY)

    def test_v2_template_denies_same_task_in_another_memory_store(self):
        # The [store:...] suffix is a literal binding: the same task id in another
        # database, a look-alike path or a non-canonical spelling must not match.
        for resource in ("memory:task/T-1 [store:/other/memory.sqlite3]",
                         "memory:task/T-1 [store:/state/memory.sqlite3.bak]",
                         "memory:task/T-1 [store:/state/../state/memory.sqlite3]",
                         "memory:task/T-1"):
            with self.subTest(resource=resource):
                request = dict(self.request, resource=resource)
                self.assertIs(self.authorize(request).decision, Decision.DENY)

    def test_v2_deny_rule_overrides_template_allow(self):
        source = v2_policy(rules=[
            {"action": "READ", "resource": "memory:task/{task_id} [store:/state/memory.sqlite3]", "match_mode": "TEMPLATE",
             "effect": "ALLOW", "scope": ["memory:task:{task_id}:read"]},
            {"action": "READ", "resource": "memory:task/T-1 [store:/state/memory.sqlite3]", "match_mode": "EXACT",
             "effect": "DENY", "scope": ["memory:task:T-1:read"]},
        ])
        self.engine = self._engine(
            dict(source, policy_digest=digest(source), provenance_verified=True),
            _Principal(templates=True))
        self.assertIs(self.authorize().decision, Decision.DENY)

    def test_v2_unknown_template_blocks_instead_of_falling_back(self):
        source = v2_policy(rules=[{
            "action": "READ", "resource": "memory:task/{anything}", "match_mode": "TEMPLATE",
            "effect": "ALLOW", "scope": ["memory:task:{task_id}:read"],
        }])
        self.engine = self._engine(
            dict(source, policy_digest=digest(source), provenance_verified=True),
            _Principal(templates=True))
        self.assertIs(self.authorize().decision, Decision.BLOCKED)

    def test_v1_keeps_literal_exact_matching(self):
        legacy = {
            "schema_version": "hg.policy.v1", "status": "ACTIVE", "version": "legacy",
            "root_generation": 1, "provenance_verified": True,
            "policy_digest": "sha256:" + "0" * 64, "approval_evidence_refs": ["approval:test"],
            "grant_ttl_seconds": 30, "rules": [{
                "action": "READ", "resource": "memory:task/{task_id} [store:/state/memory.sqlite3]",
                "effect": "ALLOW", "scope": ["memory:task:{task_id}:read"],
            }],
        }
        self.engine = self._engine(legacy, _Principal(templates=False))
        self.assertIs(self.authorize().decision, Decision.DENY)


if __name__ == "__main__":
    unittest.main()
