"""C-19 Regression cases: scenarios with an expected outcome, replayed through the real runtime.

A case names a goal (StructuredGoalPlanner operations), the authority mode, files to set
up, an optional verifier and what must be observed. Cases protect behaviour that matters
for safety and honesty -- a denial stays a denial with no effect, a failed check never
turns into CLOSED_VERIFIED -- and the learning loop proposes new ones from recurring
failures (hg/verification/learning.py).

Authority modes: "fixture" (grants for every planned step, or none), "anchored" (an
in-process manifest document with manifest-issued grants; the live manifest is never
needed, so the suite runs offline and deterministically).
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from maep.authority.canonical_source import CanonicalManifest
from maep.authority.trust_anchor import fingerprint, load_manifest
from maep.core import MAEPError, POLICY_VERSION
from hg.brain.planner import PlanRejected, StructuredGoalPlanner
from hg.runtime import DEFAULT_PRINCIPAL, build_runtime

CASES_PATH = Path(__file__).with_name("regression_cases.json")
REQUIRED = {"case_id", "description", "origin", "mode", "goal", "expect"}


def load_cases(path=CASES_PATH):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = set()
    for case in cases:
        missing = REQUIRED - set(case)
        if missing:
            raise MAEPError(f"regression case missing {sorted(missing)}: {case.get('case_id')}")
        if case["case_id"] in ids:
            raise MAEPError(f"duplicate regression case id {case['case_id']}")
        if case["mode"] not in {"fixture", "anchored"}:
            raise MAEPError(f"unknown mode in {case['case_id']}")
        ids.add(case["case_id"])
    return cases


def _task(case):
    task = {"task_id": case["case_id"], "objective": case["description"],
            "scope": {"include": ["out/"], "exclude": []}, "inputs": [],
            "outputs": [{"name": "result", "description": "case outcome"}],
            "acceptance_criteria": [{"criterion_id": "AC-1", "description": "case verifier", "mandatory": True,
                                     "evidence_types": ["TEST_RESULT"]}],
            "evidence_requirements": ["verifier"], "risks": [], "stop_conditions": ["unexpected effect"],
            "next_action": "run case", "state": "DRAFT", "policy_version": POLICY_VERSION}
    task["scope"].update(case.get("scope", {}))
    return task


def _grants(steps, task_id, now):
    return [{"authorization_id": s["authorization_id"], "principal": DEFAULT_PRINCIPAL, "action": s["action"],
             "resource": s["resource"], "scope": s["scope"], "conditions": [], "task_id": task_id,
             "policy_version": POLICY_VERSION, "decision": "ALLOW", "issued_at": (now - timedelta(minutes=1)).isoformat(),
             "expires_at": (now + timedelta(minutes=30)).isoformat()} for s in steps]


def _verifier(spec, root):
    if not spec:
        return {}

    def case_verifier(snapshot):
        if "file" in spec:
            path = root / spec["file"]
            actual = path.read_text(encoding="utf-8") if path.is_file() else None
            return actual == spec["equals"], f"file {spec['file']} = {actual!r}"
        step, field = spec["outcome"]
        observed = next((o["observed"] for o in snapshot["outcomes"] if o["step_id"] == step), {})
        return observed.get(field) == spec["equals"], f"{step}.{field} = {observed.get(field)!r}"
    return {"AC-1": case_verifier}


def run_case(case, workdir, *, extra_adapters_factory=None):
    workdir = Path(workdir)
    now = datetime.now(timezone.utc)
    task = _task(case)
    started = time.monotonic()
    observed = {"plan_rejected": False, "state": None, "effects": 0, "files": {}}
    planning = build_runtime(workdir / "planning", [], allow_fixture_grants=True)
    try:
        steps = StructuredGoalPlanner().plan(task, case["goal"], planning.gateway)
    except PlanRejected as exc:
        steps = None
        observed["plan_rejected"] = True
        observed["problems"] = exc.problems
    run_dir = workdir / "run"
    root = run_dir / "root"
    for rel, text in case.get("setup_files", {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    kwargs = {"verifiers": _verifier(case.get("verifier"), root),
              "mode": "READ_ONLY" if case.get("read_only") else "AUTHORIZED_EXECUTION"}
    if extra_adapters_factory:
        kwargs["extra_adapters"] = extra_adapters_factory(root)
    if case["mode"] == "anchored":
        doc = load_manifest(lambda _p: (200, json.dumps(case["manifest"])))
        source = CanonicalManifest(lambda: (doc, {"commit": f"case:{case['case_id']}", "fingerprint": fingerprint(doc)}),
                                   max_age_s=0)
        rt = build_runtime(run_dir, [], authority=source, issue_task_grants=True, **kwargs)
    else:
        grants = _grants(steps, task["task_id"], now) if steps and case.get("grants", "plan") == "plan" else []
        rt = build_runtime(run_dir, grants, allow_fixture_grants=True, **kwargs)
    final = rt.orch.execute_goal(task, case["goal"], StructuredGoalPlanner())   # a rejection is recorded too
    observed["state"] = final["task"]["state"]
    observed["effects"] = len(rt.actions.events("ACTION_STARTED"))
    observed["closure_evidence"] = len((final.get("closure") or {}).get("evidence_refs", []))
    for rel in case["expect"].get("files_present", []) + case["expect"].get("files_absent", []):
        observed["files"][rel] = (root / rel).exists()
    mismatches = _compare(case["expect"], observed)
    return {"case_id": case["case_id"], "passed": not mismatches, "mismatches": mismatches, "observed": observed,
            "expect": case["expect"], "duration_ms": int((time.monotonic() - started) * 1000)}


def _compare(expect, observed):
    problems = []
    if "state" in expect and observed["state"] != expect["state"]:
        problems.append(f"state {observed['state']} != {expect['state']}")
    if expect.get("plan_rejected") is not None and observed["plan_rejected"] != expect["plan_rejected"]:
        problems.append(f"plan_rejected {observed['plan_rejected']} != {expect['plan_rejected']}")
    if expect.get("not_closed") and observed["state"] == "CLOSED_VERIFIED":
        problems.append("closed although this case must never close")
    if expect.get("no_effect") and observed["effects"]:
        problems.append(f"{observed['effects']} effect(s) started where none was allowed")
    for rel in expect.get("files_present", []):
        if not observed["files"].get(rel):
            problems.append(f"{rel} missing")
    for rel in expect.get("files_absent", []):
        if observed["files"].get(rel):
            problems.append(f"{rel} exists but must not")
    return problems
