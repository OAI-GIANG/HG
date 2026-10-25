"""Deterministic, bounded scenario simulation for HG.

No eval/exec, network, tools, persistence, or authorization is exposed here.
Every output is SIMULATED and must not be treated as factual verification.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

SIMULATION_CONTRACT_VERSION = "hg.scenario.v1"
MAX_SCENARIOS = 20
MAX_HORIZON_STEPS = 20
MAX_STATE_VARIABLES = 16
MAX_TRANSITION_RULES = 32
MAX_ASSUMPTIONS = 64
MAX_OUTPUT_BYTES = 180_000
MAX_DURATION_MS = 5_000
OPERATIONS = {"SET", "ADD", "MULTIPLY", "MIN", "MAX"}


class SimulationError(ValueError):
    """Scenario input violates the bounded deterministic simulation contract."""


def _string(value: Any, field: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SimulationError(field + " must be a bounded non-empty string")
    if any(ord(ch) < 32 and ch not in "\n\t\r" for ch in value):
        raise SimulationError(field + " contains control characters")
    return value


def _number(value: Any, field: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationError(field + " must be a finite numeric value")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite or abs(value) > 1e100:
        raise SimulationError(field + " must be finite and within the numeric magnitude bound")
    return value


def _text_list(value: Any, field: str, *, maximum: int = MAX_ASSUMPTIONS) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SimulationError(field + " must be a bounded list")
    result = [_string(item, field + " item", maximum=1000) for item in value]
    if len(set(result)) != len(result):
        raise SimulationError(field + " contains duplicates")
    return result


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class ScenarioEngine:
    """Run a finite set of explicit numerical state-transition scenarios."""

    def __init__(self, *, max_scenarios: int = MAX_SCENARIOS,
                 max_horizon_steps: int = MAX_HORIZON_STEPS,
                 max_duration_ms: int = MAX_DURATION_MS,
                 max_output_bytes: int = MAX_OUTPUT_BYTES):
        limits = (
            ("max_scenarios", max_scenarios, 1, MAX_SCENARIOS),
            ("max_horizon_steps", max_horizon_steps, 1, MAX_HORIZON_STEPS),
            ("max_duration_ms", max_duration_ms, 1, MAX_DURATION_MS),
            ("max_output_bytes", max_output_bytes, 1024, MAX_OUTPUT_BYTES),
        )
        for name, value, lower, upper in limits:
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise SimulationError(name + " is outside the allowed bound")
        self.max_scenarios = max_scenarios
        self.max_horizon_steps = max_horizon_steps
        self.max_duration_ms = max_duration_ms
        self.max_output_bytes = max_output_bytes

    def run(self, *, request: dict[str, Any]) -> dict[str, Any]:
        """Simulate scenarios using only declared numeric values and operations.

        Rules execute in listed order at each transition. Scenarios begin with
        the same initial state, then apply their explicit overrides. Any value
        leaving its declared domain stops that scenario; it is never clamped
        silently or reinterpreted as an observed real-world outcome.
        """
        if not isinstance(request, dict):
            raise SimulationError("simulation request must be an object")
        required = {
            "contract_version", "scenario_id", "task_ref", "candidate_ref", "policy_version",
            "state_variables", "transition_rules", "scenarios", "horizon_steps", "assumptions",
        }
        if set(request) != required:
            raise SimulationError("simulation request has unknown or missing fields")
        if request["contract_version"] != SIMULATION_CONTRACT_VERSION:
            raise SimulationError("unsupported simulation contract version")
        identity = {
            "scenario_id": _string(request["scenario_id"], "scenario_id"),
            "task_ref": _string(request["task_ref"], "task_ref"),
            "candidate_ref": _string(request["candidate_ref"], "candidate_ref"),
            "policy_version": _string(request["policy_version"], "policy_version"),
        }
        horizon = request["horizon_steps"]
        if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= self.max_horizon_steps:
            raise SimulationError("horizon_steps is outside the configured bound")
        assumptions = _text_list(request["assumptions"], "assumptions")
        raw_variables = request["state_variables"]
        if not isinstance(raw_variables, list) or not 1 <= len(raw_variables) <= MAX_STATE_VARIABLES:
            raise SimulationError("state_variables must contain 1 to 16 entries")
        variables: dict[str, dict[str, Any]] = {}
        for item in raw_variables:
            if not isinstance(item, dict) or set(item) != {"name", "value", "unit", "min_value", "max_value"}:
                raise SimulationError("state variable has unknown or missing fields")
            name = _string(item["name"], "state variable name", maximum=128)
            if name in variables:
                raise SimulationError("state variable names must be unique")
            unit = _string(item["unit"], "state variable unit", maximum=64)
            value = _number(item["value"], name + ".value")
            minimum = _number(item["min_value"], name + ".min_value")
            maximum = _number(item["max_value"], name + ".max_value")
            if minimum > maximum or not minimum <= value <= maximum:
                raise SimulationError(name + " initial value/domain is invalid")
            variables[name] = {"value": value, "unit": unit, "min_value": minimum, "max_value": maximum}

        raw_rules = request["transition_rules"]
        if not isinstance(raw_rules, list) or len(raw_rules) > MAX_TRANSITION_RULES:
            raise SimulationError("transition_rules exceeds the configured bound")
        rules = []
        rule_ids = set()
        for item in raw_rules:
            if not isinstance(item, dict) or set(item) != {"rule_id", "variable", "operation", "value", "value_unit"}:
                raise SimulationError("transition rule has unknown or missing fields")
            rule_id = _string(item["rule_id"], "rule_id", maximum=128)
            variable = _string(item["variable"], "rule.variable", maximum=128)
            operation = item["operation"]
            value_unit = _string(item["value_unit"], "rule.value_unit", maximum=64)
            if rule_id in rule_ids:
                raise SimulationError("transition rule ids must be unique")
            rule_ids.add(rule_id)
            if variable not in variables:
                raise SimulationError("transition rule refers to an unknown variable")
            if operation not in OPERATIONS:
                raise SimulationError("unsupported transition operation")
            expected_unit = "1" if operation == "MULTIPLY" else variables[variable]["unit"]
            if value_unit != expected_unit:
                raise SimulationError("transition rule unit does not match variable/operation")
            rules.append({
                "rule_id": rule_id, "variable": variable, "operation": operation,
                "value": _number(item["value"], "rule.value"), "value_unit": value_unit,
            })

        raw_scenarios = request["scenarios"]
        if not isinstance(raw_scenarios, list) or not 1 <= len(raw_scenarios) <= self.max_scenarios:
            raise SimulationError("scenarios count is outside the configured bound")
        scenarios = []
        scenario_ids = set()
        for item in raw_scenarios:
            if not isinstance(item, dict) or set(item) != {"scenario_id", "overrides", "assumptions"}:
                raise SimulationError("scenario has unknown or missing fields")
            scenario_id = _string(item["scenario_id"], "scenario.scenario_id")
            if scenario_id in scenario_ids:
                raise SimulationError("scenario ids must be unique")
            scenario_ids.add(scenario_id)
            scenario_assumptions = _text_list(item["assumptions"], "scenario.assumptions")
            overrides_raw = item["overrides"]
            if not isinstance(overrides_raw, list) or len(overrides_raw) > len(variables):
                raise SimulationError("scenario overrides exceed the variable bound")
            overrides = {}
            for override in overrides_raw:
                if not isinstance(override, dict) or set(override) != {"variable", "value"}:
                    raise SimulationError("scenario override has unknown or missing fields")
                name = _string(override["variable"], "override.variable", maximum=128)
                if name not in variables or name in overrides:
                    raise SimulationError("scenario override variable is unknown or duplicated")
                value = _number(override["value"], "override.value")
                spec = variables[name]
                if not spec["min_value"] <= value <= spec["max_value"]:
                    raise SimulationError("scenario override is outside variable domain")
                overrides[name] = value
            scenarios.append({"scenario_id": scenario_id, "overrides": overrides,
                              "assumptions": scenario_assumptions})

        canonical_input = {
            "contract_version": SIMULATION_CONTRACT_VERSION,
            **identity, "horizon_steps": horizon, "assumptions": assumptions,
            "state_variables": [
                {"name": name, **spec} for name, spec in sorted(variables.items())
            ],
            "transition_rules": rules,
            "scenarios": [
                {"scenario_id": s["scenario_id"], "overrides": s["overrides"],
                 "assumptions": s["assumptions"]} for s in scenarios
            ],
        }
        input_digest = _digest(canonical_input)
        started = time.monotonic()
        deadline = started + self.max_duration_ms / 1000
        results = []
        timed_out = False
        for scenario in scenarios:
            state = {name: spec["value"] for name, spec in variables.items()}
            state.update(scenario["overrides"])
            trace = []
            violations = []
            status = "COMPLETED"
            for step_index in range(1, horizon + 1):
                if time.monotonic() > deadline:
                    status = "BUDGET_EXCEEDED"
                    timed_out = True
                    break
                changed = {}
                for rule in rules:
                    name, operation, operand = rule["variable"], rule["operation"], rule["value"]
                    current = state[name]
                    if operation == "SET":
                        new_value = operand
                    elif operation == "ADD":
                        new_value = current + operand
                    elif operation == "MULTIPLY":
                        new_value = current * operand
                    elif operation == "MIN":
                        new_value = min(current, operand)
                    else:  # MAX
                        new_value = max(current, operand)
                    if not math.isfinite(new_value):
                        status = "STOPPED_NONFINITE"
                        violations.append({"step": step_index, "variable": name, "rule_id": rule["rule_id"],
                                           "reason": "transition produced non-finite value"})
                        break
                    spec = variables[name]
                    if not spec["min_value"] <= new_value <= spec["max_value"]:
                        status = "STOPPED_RANGE_VIOLATION"
                        violations.append({
                            "step": step_index, "variable": name, "rule_id": rule["rule_id"],
                            "value": new_value, "min_value": spec["min_value"],
                            "max_value": spec["max_value"],
                        })
                        break
                    state[name] = new_value
                    changed[name] = new_value
                trace.append({"step": step_index, "changed": changed, "state": dict(state)})
                if status != "COMPLETED":
                    break
            results.append({
                "scenario_id": scenario["scenario_id"],
                "assumptions": assumptions + scenario["assumptions"],
                "initial_state": dict({name: spec["value"] for name, spec in variables.items()},
                                      **scenario["overrides"]),
                "final_state": dict(state),
                "trace": trace,
                "violations": violations,
                "status": status,
                "epistemic_label": "SIMULATED",
            })
            if timed_out:
                break

        finals_by_variable: dict[str, list[float | int]] = {name: [] for name in variables}
        for result in results:
            for name, value in result["final_state"].items():
                finals_by_variable[name].append(value)
        sensitivity = {
            name: {"min_final": min(values), "max_final": max(values),
                   "scenario_count": len(values), "unit": variables[name]["unit"]}
            for name, values in finals_by_variable.items() if values
        }
        outcome = {
            "contract_version": SIMULATION_CONTRACT_VERSION,
            **identity,
            "input_digest": input_digest,
            "status": "BUDGET_EXCEEDED" if timed_out else "SIMULATED",
            "epistemic_label": "SIMULATED",
            "authority_effect": "NONE",
            "side_effects_performed": False,
            "horizon_steps_requested": horizon,
            "scenario_count_requested": len(scenarios),
            "scenario_count_completed_or_stopped": len(results),
            "results": results,
            "sensitivity": sensitivity,
            "limitations": [
                "Results follow only the declared transition rules and assumptions.",
                "Simulation outputs are not observations, verified facts, forecasts, or action authorization.",
                "Sensitivity ranges are across the supplied scenarios only, not statistical confidence intervals.",
            ],
            "resource_usage": {},
        }
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        outcome["resource_usage"] = {
            "elapsed_ms": elapsed_ms,
            "scenario_count": len(results),
            "transition_count": sum(len(item["trace"]) for item in results),
            "output_bytes": 0,
        }
        output_bytes = 0
        for _ in range(4):
            output_bytes = len(json.dumps(outcome, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            if outcome["resource_usage"]["output_bytes"] == output_bytes:
                break
            outcome["resource_usage"]["output_bytes"] = output_bytes
        if output_bytes > self.max_output_bytes:
            raise SimulationError("simulation output exceeds size limit")
        return outcome
