"""MAEP governance primitives for HG; Python standard library only.

This module is not a complete JSON Schema validator and does not itself authenticate
principals. Callers must supply a trusted policy decision and authenticated identity.
"""
from datetime import datetime, timezone

POLICY_VERSION = "MAEP-1.1.0"
STATES = {
    "DRAFT", "READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING",
    "VERIFYING", "ACCEPTED", "CLOSED_VERIFIED", "BLOCKED", "FAILED",
    "CANCELLED", "UNVERIFIED"
}
TRANSITIONS = {
    "DRAFT": {"READY"},
    "READY": {"ASSESSED"},
    "ASSESSED": {"PLANNED"},
    "PLANNED": {"AUTHORIZED"},
    "AUTHORIZED": {"RUNNING"},
    "RUNNING": {"VERIFYING", "BLOCKED", "FAILED"},
    "VERIFYING": {"ACCEPTED", "UNVERIFIED", "BLOCKED", "FAILED"},
    "ACCEPTED": {"CLOSED_VERIFIED"},
    "BLOCKED": {"ASSESSED", "CANCELLED"},
    "UNVERIFIED": {"VERIFYING", "BLOCKED"},
    "FAILED": set(),
    "CANCELLED": set(),
    "CLOSED_VERIFIED": set(),
}
TERMINAL_STATES = {"FAILED", "CANCELLED", "CLOSED_VERIFIED"}
REQUIRED_TASK_FIELDS = {
    "task_id", "objective", "scope", "inputs", "outputs",
    "acceptance_criteria", "evidence_requirements", "risks",
    "stop_conditions", "next_action", "state", "policy_version"
}
REQUIRED_EVIDENCE_FIELDS = {
    "evidence_id", "evidence_type", "source_ref", "candidate_ref",
    "collected_at", "collector", "method", "result", "limitations"
}
REQUIRED_AUTH_FIELDS = {
    "authorization_id", "principal", "action", "resource", "scope",
    "conditions", "task_id", "policy_version", "decision", "issued_at", "expires_at"
}


class MAEPError(ValueError):
    """Raised when a governance invariant is not satisfied."""


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_datetime(value, label):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise MAEPError(f"invalid {label}")
    if parsed.tzinfo is None:
        raise MAEPError(f"{label} must include timezone")
    return parsed


def validate_task(task):
    if not isinstance(task, dict):
        raise MAEPError("task must be an object")
    missing = REQUIRED_TASK_FIELDS - task.keys()
    if missing:
        raise MAEPError("task missing fields: " + ", ".join(sorted(missing)))
    for field in ("task_id", "objective", "next_action", "policy_version"):
        if not _nonempty_string(task[field]):
            raise MAEPError(f"{field} must be a non-empty string")
    if not isinstance(task["state"], str) or task["state"] not in STATES:
        raise MAEPError("unknown task state")
    scope = task["scope"]
    if not isinstance(scope, dict) or not isinstance(scope.get("include"), list) or not scope["include"]:
        raise MAEPError("scope.include must be a non-empty list")
    if not isinstance(scope.get("exclude"), list):
        raise MAEPError("scope.exclude must be a list")
    if not isinstance(task["acceptance_criteria"], list) or not task["acceptance_criteria"]:
        raise MAEPError("acceptance_criteria must be non-empty")
    if not isinstance(task["stop_conditions"], list) or not task["stop_conditions"]:
        raise MAEPError("stop_conditions must be non-empty")
    for field in ("inputs", "outputs", "evidence_requirements", "risks"):
        if not isinstance(task[field], list):
            raise MAEPError(f"{field} must be a list")
    return True


def validate_evidence(evidence, candidate_ref=None):
    if not isinstance(evidence, dict):
        raise MAEPError("evidence must be an object")
    missing = REQUIRED_EVIDENCE_FIELDS - evidence.keys()
    if missing:
        raise MAEPError("evidence missing fields: " + ", ".join(sorted(missing)))
    for field in REQUIRED_EVIDENCE_FIELDS:
        value = evidence[field]
        if field == "limitations":
            if not isinstance(value, list):
                raise MAEPError("limitations must be a list")
        elif not _nonempty_string(value):
            raise MAEPError(f"{field} must be a non-empty string")
    if candidate_ref is not None and evidence["candidate_ref"] != candidate_ref:
        raise MAEPError("evidence candidate mismatch")
    return True


def authorize_action(grant, request, *, trusted_policy_allow, now=None):
    """Fail-closed check. trusted_policy_allow must come from trusted policy evaluation."""
    if trusted_policy_allow is not True:
        raise MAEPError("trusted policy decision did not allow action")
    if not isinstance(grant, dict) or not isinstance(request, dict):
        raise MAEPError("grant and request must be objects")
    missing = REQUIRED_AUTH_FIELDS - grant.keys()
    if missing:
        raise MAEPError("authorization missing fields: " + ", ".join(sorted(missing)))
    if grant.get("decision") != "ALLOW":
        raise MAEPError("authorization record is not ALLOW")
    if grant.get("principal") != request.get("principal"):
        raise MAEPError("principal mismatch")
    for field in ("action", "resource", "task_id", "policy_version"):
        if grant.get(field) != request.get(field):
            raise MAEPError(f"{field} mismatch")
    for field in ("principal", "action", "resource", "task_id", "policy_version"):
        if not _nonempty_string(request.get(field)):
            raise MAEPError(f"request {field} must be non-empty")
    requested_scope = request.get("scope")
    if not isinstance(requested_scope, list) or not requested_scope or not all(_nonempty_string(v) for v in requested_scope):
        raise MAEPError("request scope must be a non-empty list of strings")
    if not isinstance(grant.get("scope"), list) or not set(requested_scope).issubset(set(grant["scope"])):
        raise MAEPError("requested scope exceeds authorization")
    required_conditions = grant.get("conditions")
    satisfied_conditions = request.get("satisfied_conditions", [])
    if not isinstance(required_conditions, list) or not isinstance(satisfied_conditions, list):
        raise MAEPError("authorization conditions must be lists")
    if not set(required_conditions).issubset(set(satisfied_conditions)):
        raise MAEPError("authorization conditions are not satisfied")
    now = now or datetime.now(timezone.utc)
    issued_at = _parse_aware_datetime(grant.get("issued_at"), "authorization issue time")
    if issued_at > now:
        raise MAEPError("authorization is not yet valid")
    expires = grant.get("expires_at")
    if expires is not None:
        if now >= _parse_aware_datetime(expires, "authorization expiry"):
            raise MAEPError("authorization expired")
    return True


def transition(current, target, *, guards=None, blocker_resolved=False):
    """Return target only if transition is allowed and guards are satisfied.

    A terminal task never transitions; continuation is a new task checked by validate_linked_task.
    """
    if current not in STATES or target not in STATES:
        raise MAEPError("unknown state")
    if current in TERMINAL_STATES:
        raise MAEPError("terminal task cannot be reopened; continue with a linked task")
    if target not in TRANSITIONS.get(current, set()):
        raise MAEPError(f"forbidden transition: {current} -> {target}")
    guards = guards or {}
    if not isinstance(guards, dict):
        raise MAEPError("guards must be an object")
    if current == "BLOCKED" and target == "ASSESSED":
        if blocker_resolved is not True:
            raise MAEPError("blocker reopening requires evidence of resolution")
        refs = guards.get("blocker_resolution_evidence_refs")
        if not isinstance(refs, list) or not refs or not all(_nonempty_string(r) for r in refs):
            raise MAEPError("blocker reopening requires resolution evidence references")
        if guards.get("authority_reassessed") is not True or guards.get("risk_reassessed") is not True:
            raise MAEPError("blocker reopening requires fresh authority and risk assessment")
    if target == "VERIFYING":
        if guards.get("result_recorded") is not True or not _nonempty_string(guards.get("candidate_ref")):
            raise MAEPError("verification requires a recorded result and candidate")
    if target in {"AUTHORIZED", "RUNNING"} and guards.get("authorization_valid") is not True:
        raise MAEPError("valid authorization required")
    if target == "READY" and guards.get("task_valid") is not True:
        raise MAEPError("valid task contract required")
    if target == "ACCEPTED" and guards.get("mandatory_gates_pass") is not True:
        raise MAEPError("all mandatory gates must pass")
    if target == "CLOSED_VERIFIED":
        required = ("mandatory_gates_pass", "criteria_pass", "evidence_resolved", "no_mandatory_blocker")
        if any(guards.get(k) is not True for k in required):
            raise MAEPError("closure invariants not satisfied")
    return target


def validate_linked_task(predecessor, successor):
    """Continue a terminal task (MAEP-026) with a new DRAFT task that references it.

    The link is the task contract's existing TASK input reference; the predecessor is never mutated.
    """
    if not isinstance(predecessor, dict) or not isinstance(successor, dict):
        raise MAEPError("predecessor and successor must be objects")
    if predecessor.get("state") not in TERMINAL_STATES:
        raise MAEPError("only a terminal task can be continued by a linked task")
    predecessor_id = predecessor.get("task_id")
    successor_id = successor.get("task_id")
    if not _nonempty_string(predecessor_id) or not _nonempty_string(successor_id):
        raise MAEPError("linked tasks require non-empty task IDs")
    if predecessor_id == successor_id:
        raise MAEPError("linked task must have a new task_id")
    if successor.get("state") != "DRAFT":
        raise MAEPError("linked task must start in DRAFT")
    inputs = successor.get("inputs")
    if not isinstance(inputs, list):
        raise MAEPError("linked task inputs must be a list")
    if not any(isinstance(ref, dict) and ref.get("kind") == "TASK" and ref.get("ref_id") == predecessor_id
               for ref in inputs):
        raise MAEPError("linked task must reference its predecessor as a TASK input")
    return True


def evaluate_gate(gate, evidence_by_id, candidate_ref=None):
    if not isinstance(gate, dict):
        raise MAEPError("gate must be an object")
    required = gate.get("required") is True
    status = gate.get("status")
    if status == "NOT_APPLICABLE" and not _nonempty_string(gate.get("not_applicable_reason")):
        raise MAEPError("NOT_APPLICABLE requires a reason")
    if not required:
        return status in {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
    if status != "PASS":
        return False
    refs = gate.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return False
    for ref in refs:
        if not _nonempty_string(ref) or ref not in evidence_by_id or not isinstance(evidence_by_id[ref], dict):
            return False
        if candidate_ref is not None and evidence_by_id[ref].get("candidate_ref") != candidate_ref:
            return False
    return True


def validate_closure(closure, *, mandatory_gates, evidence_by_id, candidate_ref, policy_version):
    if not isinstance(closure, dict):
        raise MAEPError("closure must be an object")
    if closure.get("final_state") != "CLOSED_VERIFIED":
        return True
    if closure.get("candidate_ref") != candidate_ref:
        raise MAEPError("closure candidate mismatch")
    if closure.get("policy_version") != policy_version:
        raise MAEPError("closure policy version mismatch")
    criteria = closure.get("criteria_results")
    if not isinstance(criteria, list) or not criteria or not all(isinstance(c, dict) for c in criteria):
        raise MAEPError("criteria_results must be a non-empty list of objects")
    if any(not _nonempty_string(c.get("criterion_id")) for c in criteria):
        raise MAEPError("each closure criterion requires a criterion_id")
    if any(c.get("status") != "PASS" for c in criteria):
        raise MAEPError("all closure criteria must pass")
    closure_refs = closure.get("evidence_refs")
    if not isinstance(closure_refs, list) or not closure_refs or not all(_nonempty_string(r) for r in closure_refs):
        raise MAEPError("closure evidence_refs must be a non-empty list of IDs")
    for criterion in criteria:
        criterion_refs = criterion.get("evidence_refs")
        if (not isinstance(criterion_refs, list) or not criterion_refs
                or not all(_nonempty_string(r) for r in criterion_refs)
                or not set(criterion_refs).issubset(closure_refs)):
            raise MAEPError("each passing criterion must link to closure evidence")
    if not isinstance(evidence_by_id, dict) or any(ref not in evidence_by_id for ref in closure_refs):
        raise MAEPError("closure evidence missing or unresolved")
    if any(not isinstance(evidence_by_id[ref], dict) for ref in closure_refs):
        raise MAEPError("closure evidence records must be objects")
    if any(evidence_by_id[ref].get("candidate_ref") != candidate_ref for ref in closure_refs):
        raise MAEPError("closure evidence candidate mismatch")
    if not mandatory_gates or any(not evaluate_gate(g, evidence_by_id, candidate_ref) for g in mandatory_gates):
        raise MAEPError("mandatory acceptance gate not satisfied")
    limitations = closure.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise MAEPError("closure limitations must be a list of strings")
    _parse_aware_datetime(closure.get("closed_at"), "closure timestamp")
    return True


def enforce_execution_mode(mode, action):
    """Deny side effects in READ_ONLY and AUDIT_ONLY modes.

    AUDIT_ONLY additionally requires a read-only adapter registry and the fixed
    HG_AUDIT principal. This is an application guard, not OS isolation.
    """
    read_actions = {"READ", "LIST", "INSPECT"}
    known_actions = read_actions | {"WRITE", "COMMIT", "PUSH", "MERGE", "DEPLOY", "MIGRATE", "DELETE", "EXECUTE", "OTHER"}
    if mode not in {"READ_ONLY", "AUDIT_ONLY", "AUTHORIZED_EXECUTION"}:
        raise MAEPError("unknown execution mode")
    if action not in known_actions:
        raise MAEPError("unknown action")
    if mode in {"READ_ONLY", "AUDIT_ONLY"} and action not in read_actions:
        raise MAEPError(f"side effect denied in {mode} mode")
    return True


def validate_report_status(claimed_status, observed_status):
    """Prevent a report from promoting missing/unrun evidence to success."""
    allowed = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "UNVERIFIED"}
    if claimed_status not in allowed or observed_status not in allowed:
        raise MAEPError("unknown report status")
    if observed_status in {"NOT_RUN", "BLOCKED", "UNVERIFIED"} and claimed_status == "PASS":
        raise MAEPError("report cannot claim PASS without verified evidence")
    if observed_status == "FAIL" and claimed_status == "PASS":
        raise MAEPError("report contradicts failed evidence")
    return True


def retry_decision(attempt_count, *, safety_stop=False, progress_possible=True):
    """Return CONTINUE or STOP under MAEP-014."""
    # bool is a subclass of int, so True/False would otherwise pass as attempt counts.
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 0:
        raise MAEPError("attempt_count must be a non-negative integer")
    if not isinstance(safety_stop, bool) or not isinstance(progress_possible, bool):
        raise MAEPError("safety_stop and progress_possible must be booleans")
    if safety_stop or not progress_possible or attempt_count >= 3:
        return "STOP"
    return "CONTINUE"


def validate_policy_change(current_version, proposed_version, *, authorized, self_approval=False):
    """Policy mutation must be versioned and separately authorized."""
    if not _nonempty_string(current_version) or not _nonempty_string(proposed_version):
        raise MAEPError("policy versions must be non-empty")
    if current_version == proposed_version:
        raise MAEPError("policy change must use a new version")
    if authorized is not True:
        raise MAEPError("policy change requires explicit authorization")
    if self_approval:
        raise MAEPError("agent cannot self-approve policy change")
    return True


def validate_review_label(review_type, independent_evidence=False):
    if review_type == "INDEPENDENT" and independent_evidence is not True:
        raise MAEPError("independent review label requires evidence of an independent reviewer")
    if review_type not in {"INTERNAL_CRITIQUE", "PEER_REVIEW", "INDEPENDENT"}:
        raise MAEPError("unknown review type")
    return True


def validate_blocker(blocker):
    required = {"blocker_id", "known_cause", "unknowns", "missing_prerequisite", "next_action", "reopen_condition"}
    if not isinstance(blocker, dict) or not required.issubset(blocker):
        raise MAEPError("blocker record incomplete")
    for field in ("blocker_id", "known_cause", "missing_prerequisite", "next_action", "reopen_condition"):
        if not _nonempty_string(blocker[field]):
            raise MAEPError(f"blocker {field} must be non-empty")
    if not isinstance(blocker["unknowns"], list):
        raise MAEPError("blocker unknowns must be a list")
    return True


def assess_candidate_change(old_candidate, new_candidate, affected_evidence_refs):
    if not _nonempty_string(old_candidate) or not _nonempty_string(new_candidate):
        raise MAEPError("candidate references must be non-empty")
    if old_candidate == new_candidate:
        return {"impact_assessment_required": False, "invalidate_evidence_refs": []}
    if not isinstance(affected_evidence_refs, list):
        raise MAEPError("affected evidence refs must be a list")
    return {
        "impact_assessment_required": True,
        "invalidate_evidence_refs": list(dict.fromkeys(affected_evidence_refs))
    }


def architecture_proposal_allowed(existing_capability, security_or_isolation_need=False):
    """Reject unnecessary duplication unless a real boundary requirement exists."""
    if not isinstance(existing_capability, bool) or not isinstance(security_or_isolation_need, bool):
        raise MAEPError("architecture flags must be booleans")
    return not existing_capability or security_or_isolation_need


def make_evidence_amendment(original_evidence_id, amendment_id, reason, corrected_fields):
    """Create a linked correction record; never overwrite the original record."""
    if not all(_nonempty_string(v) for v in (original_evidence_id, amendment_id, reason)):
        raise MAEPError("amendment requires original ID, new ID and reason")
    if original_evidence_id == amendment_id:
        raise MAEPError("amendment must have a distinct ID")
    if not isinstance(corrected_fields, dict) or not corrected_fields:
        raise MAEPError("amendment must describe corrected fields")
    return {
        "amendment_id": amendment_id,
        "supersedes_evidence_id": original_evidence_id,
        "reason": reason,
        "corrected_fields": dict(corrected_fields)
    }


def validate_change_plan(change_plan, *, side_effecting=True, destructive=False):
    if not side_effecting:
        return True
    if not isinstance(change_plan, dict):
        raise MAEPError("side-effecting change requires a change plan")
    required = {"scope", "risk_assessment", "acceptance_criteria", "stop_conditions"}
    if not required.issubset(change_plan):
        raise MAEPError("change plan is incomplete")
    if not all(_nonempty_string(change_plan[k]) for k in required):
        raise MAEPError("change plan fields must be non-empty")
    if destructive and not _nonempty_string(change_plan.get("recovery_plan")) and change_plan.get("irreversibility_authorized") is not True:
        raise MAEPError("destructive change requires recovery plan or explicit irreversibility authorization")
    return True


def recovery_decision(outcome_known, action_idempotent, live_state_reconciled):
    """Fail closed when the previous outcome is unknown."""
    if outcome_known is True:
        return "RECONCILE_THEN_CONTINUE" if live_state_reconciled is not True else "CONTINUE"
    if action_idempotent is True and live_state_reconciled is True:
        return "RETRY_ALLOWED"
    return "BLOCKED_RECONCILIATION_REQUIRED"


def untrusted_content_can_authorize(source_trusted, contains_instruction):
    """Content never grants authority merely by containing an instruction."""
    del source_trusted, contains_instruction
    return False


def validate_research_record(record):
    if not isinstance(record, dict):
        raise MAEPError("research record must be an object")
    if not isinstance(record.get("sources"), list) or not record["sources"]:
        raise MAEPError("research requires at least one source")
    if not isinstance(record.get("claims"), list) or not record["claims"]:
        raise MAEPError("research requires claims linked to sources")
    if not isinstance(record.get("limitations"), list):
        raise MAEPError("research limitations must be a list")
    source_ids = {s.get("source_id") for s in record["sources"] if isinstance(s, dict)}
    for claim in record["claims"]:
        if not isinstance(claim, dict) or not claim.get("source_refs"):
            raise MAEPError("each research claim requires source references")
        if not set(claim["source_refs"]).issubset(source_ids):
            raise MAEPError("research claim references unknown source")
    return True


def validate_claim(claim):
    """Keep observation, inference, hypothesis and proposal semantically distinct."""
    required = {"claim_id", "claim_type", "statement", "evidence_refs", "limitations"}
    if not isinstance(claim, dict) or not required.issubset(claim):
        raise MAEPError("claim record incomplete")
    if claim.get("claim_type") not in {"FACT", "INFERENCE", "HYPOTHESIS", "PROPOSAL"}:
        raise MAEPError("unknown claim type")
    if not _nonempty_string(claim.get("claim_id")) or not _nonempty_string(claim.get("statement")):
        raise MAEPError("claim ID and statement must be non-empty")
    if not isinstance(claim.get("evidence_refs"), list) or not isinstance(claim.get("limitations"), list):
        raise MAEPError("claim evidence_refs and limitations must be lists")
    if claim["claim_type"] == "FACT" and not claim["evidence_refs"]:
        raise MAEPError("FACT claim requires evidence references")
    if claim["claim_type"] in {"INFERENCE", "HYPOTHESIS", "PROPOSAL"} and not claim["limitations"]:
        raise MAEPError("inference, hypothesis and proposal must disclose limitations")
    return True
