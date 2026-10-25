import copy
import unittest

from brain.simulation import (
    SIMULATION_CONTRACT_VERSION, ScenarioEngine, SimulationError,
)


def request():
    return {
        "contract_version": SIMULATION_CONTRACT_VERSION,
        "scenario_id": "scenario-set:1",
        "task_ref": "task:simulation-1",
        "candidate_ref": "candidate:1",
        "policy_version": "MAEP-1.2.0",
        "state_variables": [
            {"name": "score", "value": 10, "unit": "points", "min_value": 0, "max_value": 100},
        ],
        "transition_rules": [
            {"rule_id": "increment", "variable": "score", "operation": "ADD",
             "value": 1, "value_unit": "points"},
        ],
        "scenarios": [
            {"scenario_id": "baseline", "overrides": [], "assumptions": ["baseline conditions"]},
            {"scenario_id": "high-start", "overrides": [{"variable": "score", "value": 15}],
             "assumptions": ["higher initial score"]},
        ],
        "horizon_steps": 2,
        "assumptions": ["rule repeats once per transition"],
    }


class ScenarioEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ScenarioEngine()

    def test_deterministic_results_are_labelled_simulated(self):
        result = self.engine.run(request=request())
        self.assertEqual(result["status"], "SIMULATED")
        self.assertEqual(result["epistemic_label"], "SIMULATED")
        self.assertEqual(result["authority_effect"], "NONE")
        self.assertFalse(result["side_effects_performed"])
        self.assertEqual(result["results"][0]["final_state"]["score"], 12)
        self.assertEqual(result["results"][1]["final_state"]["score"], 17)
        self.assertEqual(result["resource_usage"]["scenario_count"], 2)
        self.assertGreater(result["resource_usage"]["output_bytes"], 0)

    def test_same_input_has_same_digest_and_state_results(self):
        first = self.engine.run(request=request())
        second = self.engine.run(request=request())
        self.assertEqual(first["input_digest"], second["input_digest"])
        self.assertEqual(first["results"], second["results"])
        self.assertEqual(first["sensitivity"], second["sensitivity"])

    def test_range_violation_stops_scenario_without_clamping(self):
        value = request()
        value["state_variables"][0]["value"] = 9
        value["state_variables"][0]["max_value"] = 10
        value["scenarios"] = value["scenarios"][:1]
        value["transition_rules"][0]["value"] = 2
        value["horizon_steps"] = 1
        result = self.engine.run(request=value)
        self.assertEqual(result["results"][0]["status"], "STOPPED_RANGE_VIOLATION")
        self.assertEqual(result["results"][0]["final_state"]["score"], 9)
        self.assertEqual(result["results"][0]["violations"][0]["rule_id"], "increment")

    def test_unknown_variable_rejected(self):
        value = request()
        value["transition_rules"][0]["variable"] = "not-defined"
        with self.assertRaisesRegex(SimulationError, "unknown variable"):
            self.engine.run(request=value)

    def test_unit_mismatch_rejected(self):
        value = request()
        value["transition_rules"][0]["value_unit"] = "seconds"
        with self.assertRaisesRegex(SimulationError, "unit does not match"):
            self.engine.run(request=value)

    def test_override_outside_domain_rejected(self):
        value = request()
        value["scenarios"][1]["overrides"][0]["value"] = 101
        with self.assertRaisesRegex(SimulationError, "outside variable domain"):
            self.engine.run(request=value)

    def test_duplicate_variable_rejected(self):
        value = request()
        value["state_variables"].append(copy.deepcopy(value["state_variables"][0]))
        with self.assertRaisesRegex(SimulationError, "names must be unique"):
            self.engine.run(request=value)

    def test_bool_is_not_accepted_as_number_or_horizon(self):
        value = request()
        value["state_variables"][0]["value"] = True
        with self.assertRaisesRegex(SimulationError, "finite numeric value"):
            self.engine.run(request=value)
        value = request()
        value["horizon_steps"] = True
        with self.assertRaisesRegex(SimulationError, "horizon_steps"):
            self.engine.run(request=value)

    def test_horizon_and_scenario_caps_are_enforced(self):
        value = request()
        value["horizon_steps"] = 21
        with self.assertRaisesRegex(SimulationError, "horizon_steps"):
            self.engine.run(request=value)
        value = request()
        value["scenarios"] *= 11
        with self.assertRaisesRegex(SimulationError, "scenarios count"):
            self.engine.run(request=value)

    def test_unknown_fields_and_malformed_inputs_fail_closed(self):
        value = request()
        value["shell_command"] = "should never be executed"
        with self.assertRaisesRegex(SimulationError, "unknown or missing fields"):
            self.engine.run(request=value)
        with self.assertRaisesRegex(SimulationError, "request must be an object"):
            self.engine.run(request="not-an-object")

    def test_multiply_requires_dimensionless_unit(self):
        value = request()
        value["transition_rules"][0] = {
            "rule_id": "scale", "variable": "score", "operation": "MULTIPLY",
            "value": 2, "value_unit": "points",
        }
        with self.assertRaisesRegex(SimulationError, "unit does not match"):
            self.engine.run(request=value)

    def test_output_budget_is_enforced(self):
        engine = ScenarioEngine(max_output_bytes=1024)
        with self.assertRaisesRegex(SimulationError, "output exceeds size limit"):
            engine.run(request=request())

    def test_no_eval_or_executable_transition_language(self):
        value = request()
        value["transition_rules"][0]["operation"] = "__import__('os').system"
        with self.assertRaisesRegex(SimulationError, "unsupported transition operation"):
            self.engine.run(request=value)


if __name__ == "__main__":
    unittest.main()
