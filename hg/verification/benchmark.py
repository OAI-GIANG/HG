"""C-19 Internal benchmark (MIID §15): the same fixed suite before and after a change.

Runs every regression case plus a crash-and-recover scenario through the real runtime in
fresh directories, offline, and reports:
    pass_rate                 cases whose observed outcome equals the expected one
    completion_rate           of cases expected to close, how many reached CLOSED_VERIFIED
    correct_denial_rate       of cases expected to have no effect, how many had none
    recovery_rate             recovery scenarios that reconciled and then closed
    evidence_backed_closures  closures that link at least one evidence record
    unauthorized_effects      effects started where none was allowed      (must be 0)
    false_closures            CLOSED_VERIFIED where it was not expected   (must be 0)
    duration_ms_total / mean
These measure this suite only. They are not measures of general intelligence.
"""
import tempfile
from pathlib import Path

from maep.core import POLICY_VERSION
from hg.brain.planner import StructuredGoalPlanner
from hg.runtime import build_runtime
from hg.tools.gateway import LocalFileWriteAdapter
from hg.verification.regressions import _grants, _task, load_cases, run_case

INVARIANTS = ("unauthorized_effects", "false_closures")
HIGHER_IS_BETTER = ("pass_rate", "completion_rate", "correct_denial_rate", "recovery_rate", "evidence_backed_closures")


class _CrashOnceWrite(LocalFileWriteAdapter):
    """Benchmark fixture: writes, then dies once before reporting (the outcome is UNKNOWN)."""
    name = "bench.crashonce"

    def __init__(self, root):
        super().__init__(root)
        self.crashed = False

    def _perform(self, params):
        observed = super()._perform(params)
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("simulated crash after the write")
        return observed


def recovery_scenario(workdir):
    from datetime import datetime, timezone
    workdir = Path(workdir)
    root = workdir / "root"
    task = _task({"case_id": "B-REC", "description": "crash after write, reconcile, resume"})
    goal = {"operations": [{"tool": "bench.crashonce", "params": {"path": "out/rec.txt", "content": "rec"}}]}
    planning = build_runtime(workdir / "planning", [], allow_fixture_grants=True,
                             extra_adapters=[_CrashOnceWrite(workdir / "planning" / "root")])
    steps = StructuredGoalPlanner().plan(task, goal, planning.gateway)
    adapter = _CrashOnceWrite(root)

    def check(_snapshot):
        path = root / "out/rec.txt"
        return path.is_file() and path.read_text(encoding="utf-8") == "rec", "file content"
    rt = build_runtime(workdir / "run", _grants(steps, task["task_id"], datetime.now(timezone.utc)),
                       allow_fixture_grants=True, extra_adapters=[adapter], verifiers={"AC-1": check})
    first = rt.orch.execute_goal(task, goal, StructuredGoalPlanner())
    if first["task"]["state"] != "BLOCKED":
        return {"recovered": False, "reason": f"expected BLOCKED after crash, got {first['task']['state']}"}
    pending = rt.gateway.pending_actions(task["task_id"])
    rt.orch.reconcile_and_reopen(task["task_id"], pending[0]["action_id"], risk_reassessment="idempotent write")
    final = rt.orch.resume(task["task_id"])
    return {"recovered": final["task"]["state"] == "CLOSED_VERIFIED", "reason": final["task"]["state"]}


def run_benchmark(cases=None, *, workdir=None):
    cases = cases if cases is not None else load_cases()
    own_tmp = None
    if workdir is None:
        own_tmp = tempfile.TemporaryDirectory(prefix="hg-bench-")
        workdir = own_tmp.name
    workdir = Path(workdir)
    try:
        results = [run_case(case, workdir / case["case_id"]) for case in cases]
        recovery = recovery_scenario(workdir / "B-REC")
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()
    closes = [r for r in results if r["expect"].get("state") == "CLOSED_VERIFIED"]
    denies = [r for r in results if r["expect"].get("no_effect")]
    closed = [r for r in results if r["observed"]["state"] == "CLOSED_VERIFIED"]

    def rate(hits, total):
        return round(hits / total, 4) if total else None
    metrics = {
        "policy_version": POLICY_VERSION, "cases": len(results), "passed": sum(r["passed"] for r in results),
        "pass_rate": rate(sum(r["passed"] for r in results), len(results)),
        "completion_rate": rate(sum(r["observed"]["state"] == "CLOSED_VERIFIED" for r in closes), len(closes)),
        "correct_denial_rate": rate(sum(r["observed"]["effects"] == 0 for r in denies), len(denies)),
        "recovery_rate": 1.0 if recovery["recovered"] else 0.0,
        "evidence_backed_closures": rate(sum(r["observed"]["closure_evidence"] > 0 for r in closed), len(closed)),
        "unauthorized_effects": sum(1 for r in denies if r["observed"]["effects"] > 0),
        "false_closures": sum(1 for r in closed if r["expect"].get("state") != "CLOSED_VERIFIED"),
        "duration_ms_total": sum(r["duration_ms"] for r in results),
    }
    metrics["duration_ms_mean"] = round(metrics["duration_ms_total"] / len(results), 1) if results else None
    failed = [{"case_id": r["case_id"], "mismatches": r["mismatches"]} for r in results if not r["passed"]]
    return {"metrics": metrics, "failed_cases": failed, "recovery": recovery,
            "results": [{"case_id": r["case_id"], "passed": r["passed"], "state": r["observed"]["state"],
                         "effects": r["observed"]["effects"], "duration_ms": r["duration_ms"]} for r in results]}


def verdict(report, baseline=None):
    """Problems that should fail a run: invariant violations, failed cases, regressions vs baseline."""
    problems = [f"{name} = {report['metrics'][name]} (must be 0)" for name in INVARIANTS if report["metrics"][name]]
    problems += [f"case {f['case_id']} failed: {'; '.join(f['mismatches'])}" for f in report["failed_cases"]]
    if not report["recovery"]["recovered"]:
        problems.append(f"recovery scenario failed: {report['recovery']['reason']}")
    if baseline is not None:
        for name in HIGHER_IS_BETTER:
            old, new = baseline["metrics"].get(name), report["metrics"].get(name)
            if old is not None and new is not None and new < old:
                problems.append(f"regression: {name} {old} -> {new}")
    return problems
