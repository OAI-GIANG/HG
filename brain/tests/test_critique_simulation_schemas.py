import json
import unittest
from pathlib import Path


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


class CritiqueSimulationSchemaTests(unittest.TestCase):
    def test_new_json_schemas_parse_and_are_versioned(self):
        expected = {
            "critique-v1.schema.json": "urn:hg:brain:critique-v1.schema.json",
            "scenario-request-v1.schema.json": "urn:hg:brain:scenario-request-v1.schema.json",
            "scenario-result-v1.schema.json": "urn:hg:brain:scenario-result-v1.schema.json",
            "review-and-simulate-request-v1.schema.json": "urn:hg:runtime:review-and-simulate-request-v1.schema.json",
        }
        for filename, schema_id in expected.items():
            with self.subTest(filename=filename):
                schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertEqual(schema["$id"], schema_id)
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertTrue(schema["required"])

    def test_critique_schema_encodes_unverified_non_authorizing_boundary(self):
        schema = json.loads((SCHEMA_DIR / "critique-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["status"]["const"], "CRITIQUE_RECORDED_UNVERIFIED")
        self.assertEqual(schema["properties"]["epistemic_label"]["const"], "MODEL_CRITIQUE_NOT_FACT_VERIFICATION")
        self.assertEqual(schema["properties"]["authority_effect"]["const"], "NONE")
        self.assertEqual(schema["properties"]["side_effects_performed"]["const"], False)
        self.assertIn("reviewed_items", schema["required"])
        self.assertLessEqual(schema["properties"]["provider_timeout_seconds"]["maximum"], 30)

    def test_scenario_schema_encodes_simulated_non_authorizing_boundary(self):
        schema = json.loads((SCHEMA_DIR / "scenario-result-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["epistemic_label"]["const"], "SIMULATED")
        self.assertEqual(schema["properties"]["authority_effect"]["const"], "NONE")
        self.assertEqual(schema["properties"]["side_effects_performed"]["const"], False)
        self.assertEqual(schema["properties"]["status"]["enum"], ["SIMULATED", "BUDGET_EXCEEDED"])


if __name__ == "__main__":
    unittest.main()
