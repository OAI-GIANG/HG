"""C-18 Self-evaluation and learning loop (MIID §12).

Reads a runtime's ledgers (tasks.jsonl, actions.jsonl), classifies every failure, groups
them by signature (class, tool, normalised reason) and turns signatures that recur at
least `threshold` times into lessons:
- a lesson names the class, the count, the tasks, a proposed corrective action, and --
  when the failing task's plan is in the ledger -- a regression case that pins the
  current safe outcome (no effect where none happened, no closure where none happened);
- record_lessons() stores lessons in PROJECT memory as HYPOTHESIS with evidence refs to
  the ledger events (a lesson is a hypothesis until someone acts on it and the benchmark
  confirms the improvement);
- proposed regression cases are returned as data for review; adding them to
  regression_cases.json is a normal reviewed change.
The loop never edits code, policy, grants or the trust root (MIID §12).
"""
import hashlib
import json
import re
from pathlib import Path

from maep.ledger import read_events

PROPOSED_ACTION = {
    "AUTHORIZATION_DENIED": "ask the owner for a manifest grant, or plan within existing authority",
    "PRECONDITION_BLOCKED": "fix the precondition named in the reason before retrying",
    "TOOL_UNAVAILABLE": "register the tool or plan with an available one",
    "INVALID_INPUT": "tighten planning so parameters are valid before dispatch",
    "KNOWN_FAILURE": "change approach; the same call already failed (MAEP-014)",
    "UNKNOWN_OUTCOME": "make the step idempotent or reconcilable",
    "UNVERIFIED_EFFECT": "add a post-condition check to the adapter",
    "PLAN_REJECTED": "give the planner the scope and tool constraints it violated",
    "VERIFICATION_FAILED": "fix the output or the plan; the check reported a mismatch",
}
REFUSAL_CLASS = {"DENIED": "AUTHORIZATION_DENIED", "BLOCKED": "PRECONDITION_BLOCKED",
                 "TOOL_UNAVAILABLE": "TOOL_UNAVAILABLE", "INVALID_INPUT": "INVALID_INPUT"}
COMPLETION_CLASS = {"FAILED": "KNOWN_FAILURE", "UNKNOWN": "UNKNOWN_OUTCOME", "SUCCEEDED_UNVERIFIED": "UNVERIFIED_EFFECT"}


def normalise(reason):
    text = str(reason or "").lower()
    text = re.sub(r"[0-9a-f]{12,}", "<id>", text)
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120]


def _ledger(path):
    path = Path(path)
    return read_events(path) if path.exists() else []


def collect_failures(workdir):
    workdir = Path(workdir)
    tasks = _ledger(workdir / "tasks.jsonl")
    actions = _ledger(workdir / "actions.jsonl")
    plans, task_records = {}, {}
    failures = []
    for event in tasks:
        tid, data = event["task_id"], event["data"]
        if event["type"] == "TASK_CREATED":
            task_records[tid] = data["task"]
        elif event["type"] == "PLAN_RECORDED":
            plans[tid] = data["plan"]
        elif event["type"] == "EVIDENCE_RECORDED":
            ev = data["evidence"]
            result = str(ev.get("result", ""))
            if ev.get("evidence_type") == "TEST_RESULT" and result == "FAIL":
                failures.append({"class": "VERIFICATION_FAILED", "tool": "-", "task_id": tid, "event": event["event_id"],
                                 "reason": (ev.get("integrity_metadata") or {}).get("detail", ev.get("source_ref"))})
            elif result.startswith("PLAN_REJECTED"):
                failures.append({"class": "PLAN_REJECTED", "tool": "-", "task_id": tid, "event": event["event_id"],
                                 "reason": result[len("PLAN_REJECTED: "):]})
            elif result.startswith("DENY"):
                failures.append({"class": "AUTHORIZATION_DENIED", "tool": "-", "task_id": tid,
                                 "event": event["event_id"], "reason": result})
    for event in actions:
        payload = event["payload"]
        status = payload.get("status")
        if event["kind"] == "ACTION_REFUSED" and status in REFUSAL_CLASS:
            failures.append({"class": REFUSAL_CLASS[status], "tool": _tool(plans, event["task_id"], payload),
                             "task_id": event["task_id"], "event": event["event_id"], "reason": payload.get("reason")})
        elif event["kind"] == "ACTION_COMPLETED" and status in COMPLETION_CLASS:
            failures.append({"class": COMPLETION_CLASS[status], "tool": _tool(plans, event["task_id"], payload),
                             "task_id": event["task_id"], "event": event["event_id"], "reason": payload.get("reason")})
    return failures, plans, task_records


def _tool(plans, task_id, payload):
    step = next((s for s in plans.get(task_id, []) if s["step_id"] == payload.get("step_id")), None)
    return step["tool"] if step else "-"


def analyze(workdirs, *, threshold=2):
    failures, plans, tasks = [], {}, {}
    for workdir in ([workdirs] if isinstance(workdirs, (str, Path)) else workdirs):
        f, p, t = collect_failures(workdir)
        failures += f
        plans.update(p)
        tasks.update(t)
    groups = {}
    for failure in failures:
        signature = (failure["class"], failure["tool"], normalise(failure["reason"]))
        group = groups.setdefault(signature, {"count": 0, "tasks": [], "events": []})
        group["count"] += 1
        if failure["task_id"] not in group["tasks"]:
            group["tasks"].append(failure["task_id"])
        group["events"].append(failure["event"])
    lessons = []
    for (klass, tool, reason), group in sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        if group["count"] < threshold:
            continue
        sig = f"{klass}|{tool}|{reason}"
        lesson = {"lesson_id": "L-" + hashlib.sha256(sig.encode()).hexdigest()[:10], "class": klass, "tool": tool,
                  "reason": reason, "count": group["count"], "tasks": group["tasks"], "events": group["events"][:20],
                  "proposed_action": PROPOSED_ACTION[klass]}
        case = _regression_case(lesson, plans.get(group["tasks"][0]), tasks.get(group["tasks"][0]))
        if case:
            lesson["regression_case"] = case
        lessons.append(lesson)
    by_class = {}
    for failure in failures:
        by_class[failure["class"]] = by_class.get(failure["class"], 0) + 1
    return {"failures": len(failures), "by_class": by_class, "signatures": len(groups), "lessons": lessons}


def _regression_case(lesson, plan, task):
    if not plan or not task:
        return None
    goal = {"operations": [{"tool": s["tool"], "params": s["params"]} for s in plan]}
    expect = {"no_effect": True} if lesson["class"] in {"AUTHORIZATION_DENIED", "PRECONDITION_BLOCKED",
                                                         "TOOL_UNAVAILABLE", "INVALID_INPUT"} else {}
    if lesson["class"] in {"VERIFICATION_FAILED", "UNVERIFIED_EFFECT", "UNKNOWN_OUTCOME", "KNOWN_FAILURE"}:
        expect["not_closed"] = True
    return {"case_id": f"R-{lesson['lesson_id']}", "description": f"guard: {lesson['class']} on {lesson['tool']}",
            "origin": f"learning loop, {lesson['count']} occurrences", "mode": "fixture",
            "scope": {"include": task["scope"]["include"], "exclude": task["scope"]["exclude"]},
            "goal": goal, "grants": "none" if expect.get("no_effect") else "plan", "expect": expect}


def record_lessons(report, memory):
    """Store lessons as PROJECT HYPOTHESIS records; an unchanged lesson is not stored twice."""
    stored = []
    for lesson in report["lessons"]:
        subject = f"lesson:{lesson['lesson_id']}"
        current = memory.active(subject=subject)
        if current and current[-1].get("value", {}).get("count") == lesson["count"]:
            continue
        stored.append(memory.remember(
            layer="PROJECT", kind="HYPOTHESIS", subject=subject,
            content=f"{lesson['class']} on {lesson['tool']} recurred {lesson['count']}x: {lesson['reason']}. "
                    f"Proposed: {lesson['proposed_action']}",
            value={"count": lesson["count"], "class": lesson["class"]}, source="TOOL",
            source_ref="hg.verification.learning", evidence_refs=lesson["events"][:10],
            limitations=[f"derived from {lesson['count']} ledger occurrences; not yet acted on or re-measured"],
            supersedes=current[-1]["memory_id"] if current else None))
    return stored


def proposed_cases_json(report):
    return json.dumps([l["regression_case"] for l in report["lessons"] if "regression_case" in l],
                      indent=2, ensure_ascii=False)
