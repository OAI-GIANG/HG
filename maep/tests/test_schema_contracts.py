import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
EXPECTED = {
    "task.schema.json": {"task_id", "objective", "scope", "acceptance_criteria", "state", "policy_version"},
    "authorization.schema.json": {"authorization_id", "principal", "action", "resource", "scope", "decision"},
    "state-transition.schema.json": {"transition_id", "task_id", "from_state", "to_state", "decision"},
    "evidence.schema.json": {"evidence_id", "source_ref", "candidate_ref", "method", "result"},
    "acceptance-gate.schema.json": {"gate_id", "task_id", "status", "criteria_refs", "evidence_refs"},
    "closure.schema.json": {"closure_id", "task_id", "final_state", "candidate_ref", "criteria_results", "gate_refs"},
    "native-authority-v1.schema.json": {"schema_version", "root_id", "generation", "status", "bootstrap_authorization_ref", "record_digest", "evidence_ref"},
    "runtime-policy-v2.schema.json": {"policy", "policy_digest"}
}


class SchemaFileTests(unittest.TestCase):
    def test_all_eight_contracts_exist_and_parse(self):
        self.assertEqual({p.name for p in SCHEMA_DIR.glob("*.schema.json")}, set(EXPECTED))
        for name in EXPECTED:
            with self.subTest(schema=name):
                data = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(data["type"], "object")
                self.assertIs(data["additionalProperties"], False)
                self.assertTrue(data["$id"].endswith(".schema.json"))

    def test_required_fields_are_declared(self):
        for name, expected in EXPECTED.items():
            with self.subTest(schema=name):
                data = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
                self.assertTrue(expected.issubset(set(data["required"])))
                self.assertTrue(set(data["required"]).issubset(set(data["properties"])))


if __name__ == "__main__":
    unittest.main()
