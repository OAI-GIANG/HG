"""Reproducible offline benchmark for the deterministic HG ScenarioEngine.

Run from the HG checkout:
  PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python3 -m brain.benchmarks.benchmark_scenario_engine --iterations 30

No model, network, external tool, or persistent output is used. VmHWM is the
process high-water mark, not a per-request peak-memory measurement.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from typing import Any

from brain.simulation import SIMULATION_CONTRACT_VERSION, ScenarioEngine


def _high_water_rss_kib() -> int | None:
    """Return Linux/Android VmHWM in KiB when proc status exposes it."""
    try:
        with open("/proc/self/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def make_worst_case_request() -> dict[str, Any]:
    """Construct a bounded 20-scenario x 20-transition deterministic workload."""
    return {
        "contract_version": SIMULATION_CONTRACT_VERSION,
        "scenario_id": "benchmark-20x20",
        "task_ref": "task:scenario-benchmark",
        "candidate_ref": "candidate:scenario-benchmark",
        "policy_version": "MAEP-1.2.0",
        "state_variables": [{
            "name": "score", "value": 10, "unit": "points",
            "min_value": 0, "max_value": 1000,
        }],
        "transition_rules": [{
            "rule_id": "increment", "variable": "score", "operation": "ADD",
            "value": 1, "value_unit": "points",
        }],
        "scenarios": [{
            "scenario_id": f"scenario-{index:02d}",
            "overrides": [{"variable": "score", "value": index}],
            "assumptions": ["fixed deterministic initial override"],
        } for index in range(20)],
        "horizon_steps": 20,
        "assumptions": ["the declared transition repeats once per horizon step"],
    }


def run_benchmark(*, iterations: int = 30) -> dict[str, Any]:
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 1000:
        raise ValueError("iterations must be an integer between 1 and 1000")
    engine = ScenarioEngine()
    request = make_worst_case_request()
    rss_before = _high_water_rss_kib()
    wall_ms: list[float] = []
    cpu_ms: list[float] = []
    sizes: list[int] = []
    transition_counts: list[int] = []
    statuses: list[str] = []
    labels: list[str] = []
    for _ in range(iterations):
        cpu_start = time.process_time()
        wall_start = time.perf_counter()
        result = engine.run(request=request)
        wall_ms.append((time.perf_counter() - wall_start) * 1000)
        cpu_ms.append((time.process_time() - cpu_start) * 1000)
        sizes.append(result["resource_usage"]["output_bytes"])
        transition_counts.append(result["resource_usage"]["transition_count"])
        statuses.append(result["status"])
        labels.append(result["epistemic_label"])
    rss_after = _high_water_rss_kib()
    return {
        "benchmark": "HG ScenarioEngine deterministic local",
        "iterations": iterations,
        "scenarios_per_request": 20,
        "horizon_steps_per_scenario": 20,
        "transition_count_consistent": len(set(transition_counts)) == 1 and transition_counts[0] == 400,
        "status_consistent": all(status == "SIMULATED" for status in statuses),
        "epistemic_label_consistent": all(label == "SIMULATED" for label in labels),
        "wall_ms_median": round(statistics.median(wall_ms), 3),
        "wall_ms_p95": round(_p95(wall_ms), 3),
        "wall_ms_min": round(min(wall_ms), 3),
        "wall_ms_max": round(max(wall_ms), 3),
        "cpu_ms_median": round(statistics.median(cpu_ms), 3),
        "output_bytes_median": int(statistics.median(sizes)),
        "process_vmhwm_before_kib": rss_before,
        "process_vmhwm_after_kib": rss_after,
        "process_vmhwm_delta_kib": (
            None if rss_before is None or rss_after is None
            else max(0, rss_after - rss_before)
        ),
        "limitations": [
            "No LLM provider, HTTP service or external tool is involved.",
            "VmHWM delta is process-wide high-water change, not per-request peak RAM.",
            "This measures deterministic scenario runtime only, not critique quality or production latency.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    try:
        result = run_benchmark(iterations=args.iterations)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
