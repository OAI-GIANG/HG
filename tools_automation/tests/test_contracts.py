import unittest

from tools_automation import (
    AdapterError,
    AdapterOutcome,
    validate_adapter_request,
    validate_adapter_result,
)


class ToolsAutomationContractTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "contract_version": "hg.tool-adapter.v1",
            "task_ref": "task:42",
            "action": "FILE_WRITE",
            "resource": "hg://workspace/docs/note.txt",
            "scope": ["hg://workspace/docs"],
            "deadline": "2026-10-22T23:00:00+07:00",
        }

    def test_valid_request_is_normalized_without_granting_authority(self):
        parsed = validate_adapter_request(self.request, idempotency_key="idem:42")
        self.assertEqual(parsed.action, "FILE_WRITE")
        self.assertEqual(parsed.scope, ("hg://workspace/docs",))
        self.assertEqual(parsed.contract_version, "hg.tool-adapter.v1")

    def test_missing_action_is_rejected(self):
        invalid = dict(self.request)
        invalid.pop("action")
        with self.assertRaisesRegex(AdapterError, "missing task/action/resource/scope"):
            validate_adapter_request(invalid, idempotency_key="idem:42")

    def test_empty_or_duplicate_scope_is_rejected(self):
        for scope in ([], ["scope:1", "scope:1"], [""]):
            invalid = dict(self.request, scope=scope)
            with self.subTest(scope=scope), self.assertRaises(AdapterError):
                validate_adapter_request(invalid, idempotency_key="idem:42")

    def test_unsupported_contract_version_is_rejected(self):
        invalid = dict(self.request, contract_version="hg.tool-adapter.v99")
        with self.assertRaisesRegex(AdapterError, "unsupported"):
            validate_adapter_request(invalid, idempotency_key="idem:42")

    def test_invalid_idempotency_key_is_rejected(self):
        for key in ("", "../same", None):
            with self.subTest(key=key), self.assertRaises(AdapterError):
                validate_adapter_request(self.request, idempotency_key=key)

    def test_success_failure_and_unknown_are_explicit(self):
        for outcome in AdapterOutcome:
            self.assertEqual(validate_adapter_result({"outcome": outcome.value})["outcome"], outcome.value)

    def test_malformed_or_ambiguous_result_is_rejected(self):
        for result in (None, {}, {"outcome": "MAYBE"}, {"outcome": "SUCCESS", "provider_ref": "../escape"}):
            with self.subTest(result=result), self.assertRaises(AdapterError):
                validate_adapter_result(result)

    def test_adapter_does_not_treat_arbitrary_truthy_idempotency_as_boolean(self):
        with self.assertRaisesRegex(AdapterError, "idempotent must be boolean"):
            validate_adapter_result({"outcome": "SUCCESS", "idempotent": "yes"})


if __name__ == "__main__":
    unittest.main()
