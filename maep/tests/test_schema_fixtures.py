"""Contract tests for the six MAEP JSON Schemas, runnable without a third-party validator.

`SCHEMA_VALIDATION_REPORT_V1.md` records a one-off check with `jsonschema==4.17.3`. That run cannot
be repeated in CI, so before this file the contracts only had parsing tests: an instance violating
`enum`, `$ref`, `minItems`, `format` or `additionalProperties: false` would still have passed
(WP2 item 8: a validator that starts is not evidence that an instance is valid).

The fixtures in `maep/schemas/fixtures.json` are written out by hand, not generated, and every
negative case names the violation it must produce. `maep/schema_check.py` enforces the subset of
JSON Schema the contracts use and refuses any other keyword, so a contract cannot gain a
constraint that nothing checks.
"""
import hashlib
import json
import unittest
from pathlib import Path

from maep import schema_check

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
FIXTURES = SCHEMA_DIR / "fixtures.json"
SUMS = SCHEMA_DIR / "SHA256SUMS"


def schema_paths():
    return sorted(SCHEMA_DIR.glob("*.schema.json"))


def load_fixtures():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


class SchemaSubsetValidatorTests(unittest.TestCase):
    def test_every_contract_uses_only_keywords_this_validator_enforces(self):
        for path in schema_paths():
            with self.subTest(schema=path.name):
                schema_check.check_supported(
                    json.loads(path.read_text(encoding="utf-8")), path.name)

    def test_an_unenforceable_keyword_is_refused_rather_than_ignored(self):
        for schema in ({"type": "object", "oneOf": []},
                       {"type": "object", "properties": {"a": {"format": "uri"}}},
                       {"type": "object", "properties": {"a": {"pattern": "^x$"}}}):
            with self.subTest(schema=schema):
                with self.assertRaises(schema_check.UnsupportedSchemaKeyword):
                    schema_check.check_supported(schema)

    def test_the_validator_does_not_treat_booleans_as_numbers(self):
        schema = {"type": "object", "properties": {"n": {"type": "number"}}}
        self.assertEqual(schema_check.validate({"n": 1}, schema), [])
        self.assertTrue(schema_check.validate({"n": True}, schema))

    def test_a_dangling_reference_is_an_error_not_a_pass(self):
        with self.assertRaises(schema_check.SchemaError):
            schema_check.validate({}, {"$ref": "#/$defs/missing", "$defs": {}})

    def test_every_contract_still_declares_the_dialect_and_a_versioned_id(self):
        for path in schema_paths():
            with self.subTest(schema=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertRegex(data["$id"], r"-1\.0\.0\.schema\.json$")


class SchemaFixtureTests(unittest.TestCase):
    def test_fixtures_cover_every_contract_in_both_directions(self):
        cases = load_fixtures()
        kinds = {}
        for case in cases:
            kinds.setdefault(case["schema"], set()).add(case["expect"])
        self.assertEqual(set(kinds), {path.name for path in schema_paths()})
        for name, verdicts in kinds.items():
            with self.subTest(schema=name):
                self.assertEqual(verdicts, {"VALID", "INVALID"})

    def test_every_negative_case_names_the_violation_it_must_produce(self):
        for case in load_fixtures():
            if case["expect"] == "INVALID":
                with self.subTest(schema=case["schema"], case=case["name"]):
                    self.assertTrue(case.get("reason"), "a negative case must name its violation")

    def test_every_fixture_reaches_its_expected_verdict_and_reason(self):
        cases = load_fixtures()
        schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in schema_paths()}
        self.assertGreater(len(cases), 30)
        for case in cases:
            with self.subTest(schema=case["schema"], case=case["name"]):
                errors = schema_check.validate(case["instance"], schemas[case["schema"]])
                if case["expect"] == "VALID":
                    self.assertEqual(errors, [], "a conforming instance was rejected")
                else:
                    self.assertTrue(errors, "a non-conforming instance was accepted")
                    self.assertTrue(any(case["reason"] in error for error in errors),
                                    f"expected a {case['reason']!r} violation, got {errors}")


class SchemaProvenanceTests(unittest.TestCase):
    """A digest proves the bytes did not change; it does not prove they are the right bytes."""

    def test_contract_and_fixture_bytes_match_the_recorded_digests(self):
        recorded = {}
        for line in SUMS.read_text(encoding="utf-8").splitlines():
            digest, name = line.split()
            recorded[name] = digest
        actual = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in schema_paths()}
        actual[FIXTURES.name] = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
        self.assertEqual(actual, recorded,
                         "a contract changed without updating maep/schemas/SHA256SUMS")

    def test_canonical_serialization_is_deterministic_and_change_sensitive(self):
        def canonical(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        instance = load_fixtures()[0]["instance"]
        digest = hashlib.sha256(canonical(instance)).hexdigest()
        self.assertEqual(digest, hashlib.sha256(
            canonical(dict(reversed(list(instance.items()))))).hexdigest())
        self.assertNotEqual(digest, hashlib.sha256(
            canonical(dict(instance, task_id="T-2"))).hexdigest())

    def test_field_order_does_not_change_the_verdict(self):
        schema = json.loads((SCHEMA_DIR / "task.schema.json").read_text(encoding="utf-8"))
        instance = load_fixtures()[0]["instance"]
        self.assertEqual(schema_check.validate(instance, schema), [])
        self.assertEqual(schema_check.validate(dict(reversed(list(instance.items()))), schema), [])


if __name__ == "__main__":
    unittest.main()
