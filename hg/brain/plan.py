"""Plan contract for HG Brain: ordered, individually authorizable steps.

A plan is data the coordinator validates before recording it in the task-state owner
(`maep.task_store.TaskStore.record_plan`). Each step names one tool, the exact action
and resource it will touch, its scope and the grant that should authorize it, so the
policy request for a step is fully determined by the step itself.
"""
from maep.core import MAEPError, POLICY_VERSION, _nonempty_string
from maep.policy import GRANT_ACTIONS

STEP_FIELDS = {"step_id", "tool", "action", "resource", "scope", "authorization_id", "params"}


def validate_plan(plan):
    if not isinstance(plan, list) or not plan:
        raise MAEPError("plan must be a non-empty list of steps")
    seen = set()
    for step in plan:
        if not isinstance(step, dict) or set(step) != STEP_FIELDS:
            raise MAEPError("plan step must have exactly: " + ", ".join(sorted(STEP_FIELDS)))
        for field in ("step_id", "tool", "resource", "authorization_id"):
            if not _nonempty_string(step[field]):
                raise MAEPError(f"plan step {field} must be a non-empty string")
        if step["action"] not in GRANT_ACTIONS:
            raise MAEPError("plan step action is unknown")
        if (not isinstance(step["scope"], list) or not step["scope"]
                or not all(_nonempty_string(s) for s in step["scope"])):
            raise MAEPError("plan step scope must be a non-empty list of strings")
        if not isinstance(step["params"], dict):
            raise MAEPError("plan step params must be an object")
        if step["step_id"] in seen:
            raise MAEPError("duplicate step_id in plan")
        seen.add(step["step_id"])
    return True


def step_request(step, principal, task_id, policy_version=POLICY_VERSION):
    """The exact PolicyEvaluator request for one plan step."""
    return {
        "authorization_id": step["authorization_id"], "principal": principal,
        "action": step["action"], "resource": step["resource"], "scope": list(step["scope"]),
        "task_id": task_id, "policy_version": policy_version,
    }
