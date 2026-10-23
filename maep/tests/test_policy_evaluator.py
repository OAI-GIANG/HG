"""PolicyEvaluator: authority comes from the evaluator's own sources, never from the request (P1-02)."""
import unittest
from datetime import datetime, timezone
from maep.core import MAEPError
from maep.policy import PolicyEvaluator

NOW = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


def grant(**overrides):
    record = {
        "authorization_id": "AUTH-1", "principal": "owner", "action": "WRITE",
        "resource": "repo:HG/maep", "scope": ["maep/"], "conditions": ["owner-approved"],
        "task_id": "T-1", "policy_version": "MAEP-1.0.0", "decision": "ALLOW",
        "issued_at": "2026-10-22T09:00:00+00:00", "expires_at": "2026-10-23T09:00:00+00:00"
    }
    record.update(overrides)
    return record


def request(**overrides):
    record = {"authorization_id": "AUTH-1", "principal": "owner", "action": "WRITE",
              "resource": "repo:HG/maep", "scope": ["maep/"], "task_id": "T-1",
              "policy_version": "MAEP-1.0.0"}
    record.update(overrides)
    return record


def facts(*verified):
    return lambda condition, _request: condition in verified


class AllowTests(unittest.TestCase):
    def test_matching_request_with_verified_conditions_allowed(self):
        decision = PolicyEvaluator([grant()], facts("owner-approved")).evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "ALLOW")
        self.assertEqual(decision["authorization_id"], "AUTH-1")
        self.assertEqual(decision["policy_version"], "MAEP-1.0.0")
        self.assertEqual(decision["evaluated_at"], NOW.isoformat())

    def test_non_expiring_grant_allowed_only_when_configured(self):
        evaluator = PolicyEvaluator([grant(expires_at=None)], facts("owner-approved"), allow_non_expiring=True)
        self.assertEqual(evaluator.evaluate(request(), now=NOW)["decision"], "ALLOW")


class CallerAssertionTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = PolicyEvaluator([grant()], facts())

    def test_caller_asserted_conditions_denied(self):
        decision = self.evaluator.evaluate(request(satisfied_conditions=["owner-approved"]), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_caller_supplied_decision_denied(self):
        decision = self.evaluator.evaluate(request(decision="ALLOW"), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_caller_supplied_trust_flag_denied(self):
        decision = self.evaluator.evaluate(request(trusted_policy_allow=True), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_caller_supplied_grant_denied(self):
        decision = self.evaluator.evaluate(request(grant=grant(conditions=[])), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_extra_fields_denied_even_when_conditions_hold(self):
        evaluator = PolicyEvaluator([grant()], facts("owner-approved"))
        decision = evaluator.evaluate(request(satisfied_conditions=["owner-approved"]), now=NOW)
        self.assertEqual(decision["decision"], "DENY")


class ConditionProviderTests(unittest.TestCase):
    def test_unverified_condition_denied(self):
        decision = PolicyEvaluator([grant()], facts()).evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "DENY")
        self.assertIn("owner-approved", decision["reason"])

    def test_provider_exception_denied(self):
        def broken(_condition, _request):
            raise RuntimeError("fact source unavailable")
        decision = PolicyEvaluator([grant()], broken).evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_truthy_non_true_provider_result_denied(self):
        decision = PolicyEvaluator([grant()], lambda c, r: "yes").evaluate(request(), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_provider_cannot_mutate_request(self):
        def mutating(_condition, req):
            req["scope"].append("secrets/")
            return True
        original = request()
        PolicyEvaluator([grant()], mutating).evaluate(original, now=NOW)
        self.assertEqual(original["scope"], ["maep/"])

    def test_non_allow_grant_denied_without_consulting_provider(self):
        calls = []
        evaluator = PolicyEvaluator([grant(decision="DENY")], lambda c, r: calls.append(c) or True)
        self.assertEqual(evaluator.evaluate(request(), now=NOW)["decision"], "DENY")
        self.assertEqual(calls, [])


class GrantValidityTests(unittest.TestCase):
    def test_expired_grant_denied(self):
        later = datetime(2026, 10, 23, 9, tzinfo=timezone.utc)
        decision = PolicyEvaluator([grant()], facts("owner-approved")).evaluate(request(), now=later)
        self.assertEqual(decision["decision"], "DENY")

    def test_not_yet_valid_grant_denied(self):
        earlier = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
        decision = PolicyEvaluator([grant()], facts("owner-approved")).evaluate(request(), now=earlier)
        self.assertEqual(decision["decision"], "DENY")

    def test_null_expiry_rejected_by_default(self):
        with self.assertRaises(MAEPError):
            PolicyEvaluator([grant(expires_at=None)], facts("owner-approved"))

    def test_naive_evaluation_time_rejected(self):
        with self.assertRaises(MAEPError):
            PolicyEvaluator([grant()], facts("owner-approved")).evaluate(request(), now=datetime(2026, 10, 22, 10))

    def test_store_is_isolated_from_later_mutation(self):
        source = grant()
        evaluator = PolicyEvaluator([source], facts("owner-approved"))
        source["scope"].append("secrets/")
        decision = evaluator.evaluate(request(scope=["maep/", "secrets/"]), now=NOW)
        self.assertEqual(decision["decision"], "DENY")


class RequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = PolicyEvaluator([grant()], facts("owner-approved"))

    def test_missing_request_field_denied(self):
        for field in request():
            with self.subTest(field=field):
                incomplete = request()
                del incomplete[field]
                self.assertEqual(self.evaluator.evaluate(incomplete, now=NOW)["decision"], "DENY")

    def test_non_object_request_denied(self):
        for value in (None, "AUTH-1", ["AUTH-1"]):
            with self.subTest(value=value):
                self.assertEqual(self.evaluator.evaluate(value, now=NOW)["decision"], "DENY")

    def test_unknown_authorization_id_denied(self):
        decision = self.evaluator.evaluate(request(authorization_id="AUTH-404"), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_unhashable_authorization_id_denied(self):
        decision = self.evaluator.evaluate(request(authorization_id=["AUTH-1"]), now=NOW)
        self.assertEqual(decision["decision"], "DENY")

    def test_binding_mismatches_denied(self):
        for field, value in (("principal", "agent"), ("action", "PUSH"), ("resource", "repo:other"),
                             ("scope", ["maep/", "secrets/"]), ("task_id", "T-2"),
                             ("policy_version", "MAEP-0.9.0")):
            with self.subTest(field=field):
                decision = self.evaluator.evaluate(request(**{field: value}), now=NOW)
                self.assertEqual(decision["decision"], "DENY")


class InvalidPolicyTests(unittest.TestCase):
    def test_invalid_grants_rejected_at_construction(self):
        missing_field = grant()
        del missing_field["expires_at"]
        cases = {
            "not an object": "AUTH-1",
            "missing field": missing_field,
            "unknown decision": grant(decision="MAYBE"),
            "unknown action": grant(action="FORMAT_DISK"),
            "policy version mismatch": grant(policy_version="MAEP-0.9.0"),
            "empty scope": grant(scope=[]),
            "non-string condition": grant(conditions=[None]),
            "blank authorization_id": grant(authorization_id=" "),
            "naive issue time": grant(issued_at="2026-10-22T09:00:00"),
            "unparseable expiry": grant(expires_at="tomorrow"),
        }
        for name, bad in cases.items():
            with self.subTest(case=name), self.assertRaises(MAEPError):
                PolicyEvaluator([bad], facts())

    def test_duplicate_authorization_id_rejected(self):
        with self.assertRaises(MAEPError):
            PolicyEvaluator([grant(), grant()], facts())

    def test_non_callable_provider_rejected(self):
        with self.assertRaises(MAEPError):
            PolicyEvaluator([grant()], {"owner-approved": True})


if __name__ == "__main__":
    unittest.main()
