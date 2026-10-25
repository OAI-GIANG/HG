"""MAEP governance primitives for HG; Python standard library only.

This module is not a complete JSON Schema validator and does not itself authenticate
principals. Callers must supply a trusted policy decision and authenticated identity.
"""
from datetime import datetime, timezone

POLICY_VERSION = "MAEP-1.2.0"
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
# Same name and value as main's maep/core.py, which maep/task_store.py imports.
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
    """Parse an ISO-8601 timestamp and require an explicit timezone offset."""
    if not isinstance(value, str) or not value.strip():
        raise MAEPError(f"invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MAEPError(f"invalid {label}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
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
        expiry = _parse_aware_datetime(expires, "authorization expiry")
        if now >= expiry:
            raise MAEPError("authorization expired")
    return True


def transition(current, target, *, guards=None, blocker_resolved=False):
    """Return target only if transition is allowed and its required evidence is present."""
    if not isinstance(current, str) or not isinstance(target, str) or current not in STATES or target not in STATES:
        raise MAEPError("unknown state")
    if current in TERMINAL_STATES:
        raise MAEPError("terminal task cannot be reopened")
    if target not in TRANSITIONS.get(current, set()):
        raise MAEPError(f"forbidden transition: {current} -> {target}")
    if guards is None:
        guards = {}
    if not isinstance(guards, dict):
        raise MAEPError("transition guards must be an object")
    if target == "VERIFYING":
        if guards.get("result_recorded") is not True or not _nonempty_string(guards.get("candidate_ref")):
            raise MAEPError("verification requires a recorded result and non-empty candidate reference")
    if current == "BLOCKED" and target == "ASSESSED":
        refs = guards.get("blocker_resolution_evidence_refs")
        if (blocker_resolved is not True or not isinstance(refs, list) or not refs
                or not all(_nonempty_string(ref) for ref in refs)
                or guards.get("authority_reassessed") is not True
                or guards.get("risk_reassessed") is not True):
            raise MAEPError("blocker reassessment requires resolution evidence, fresh authority and risk assessment")
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
    """Permit continuation only as a new DRAFT task explicitly linked to a terminal task."""
    if not isinstance(predecessor, dict) or not isinstance(successor, dict):
        raise MAEPError("predecessor and successor must be objects")
    predecessor_id = predecessor.get("task_id")
    successor_id = successor.get("task_id")
    if not _nonempty_string(predecessor_id) or not _nonempty_string(successor_id):
        raise MAEPError("task identifiers must be non-empty strings")
    if predecessor.get("state") not in TERMINAL_STATES:
        raise MAEPError("predecessor must be terminal")
    if successor.get("state") != "DRAFT":
        raise MAEPError("successor must start in DRAFT")
    if predecessor_id == successor_id:
        raise MAEPError("successor must have a new task identifier")
    inputs = successor.get("inputs")
    if not isinstance(inputs, list):
        raise MAEPError("successor inputs must be a list")
    linked = [item for item in inputs if isinstance(item, dict) and item.get("kind") == "TASK" and item.get("ref_id") == predecessor_id]
    if len(linked) != 1:
        raise MAEPError("successor must reference its predecessor exactly once")
    if any(not isinstance(item, dict) for item in inputs):
        raise MAEPError("successor inputs must contain objects")
    return True


def evaluate_gate(gate, evidence_by_id, candidate_ref=None):
    if not isinstance(gate, dict) or not isinstance(evidence_by_id, dict):
        raise MAEPError("gate and evidence index must be objects")
    required = gate.get("required") is True
    status = gate.get("status")
    if status == "NOT_APPLICABLE" and not _nonempty_string(gate.get("not_applicable_reason")):
        raise MAEPError("NOT_APPLICABLE requires a reason")
    if not required:
        return status in {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
    if status != "PASS":
        return False
    refs = gate.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(_nonempty_string(ref) for ref in refs):
        return False
    for ref in refs:
        if ref not in evidence_by_id:
            return False
        evidence = evidence_by_id[ref]
        if not isinstance(evidence, dict):
            raise MAEPError("gate evidence record must be an object")
        if candidate_ref is not None and evidence.get("candidate_ref") != candidate_ref:
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
    if not isinstance(criteria, list) or not criteria:
        raise MAEPError("closure criteria results must be a non-empty list")
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise MAEPError("closure criterion must be an object")
        if not _nonempty_string(criterion.get("criterion_id")) or criterion.get("status") != "PASS":
            raise MAEPError("each closure criterion must have an id and PASS status")
        refs = criterion.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(_nonempty_string(ref) for ref in refs):
            raise MAEPError("each passing criterion must reference evidence")
    closure_refs = closure.get("evidence_refs")
    if not isinstance(closure_refs, list) or not closure_refs or not all(_nonempty_string(ref) for ref in closure_refs):
        raise MAEPError("closure evidence refs must be a non-empty list of strings")
    closure_ref_set = set(closure_refs)
    for criterion in criteria:
        if not set(criterion["evidence_refs"]).issubset(closure_ref_set):
            raise MAEPError("each passing criterion must link to closure evidence")
    if not isinstance(evidence_by_id, dict):
        raise MAEPError("evidence index must be an object")
    for ref in closure_refs:
        if ref not in evidence_by_id:
            raise MAEPError("closure evidence missing or unresolved")
        evidence = evidence_by_id[ref]
        if not isinstance(evidence, dict):
            raise MAEPError("closure evidence record must be an object")
        if evidence.get("candidate_ref") != candidate_ref:
            raise MAEPError("closure evidence candidate mismatch")
    if not isinstance(mandatory_gates, list) or not mandatory_gates or any(not evaluate_gate(g, evidence_by_id, candidate_ref) for g in mandatory_gates):
        raise MAEPError("mandatory acceptance gate not satisfied")
    limitations = closure.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise MAEPError("closure limitations must be a list of strings")
    _parse_aware_datetime(closure.get("closed_at"), "closure timestamp")
    return True


def enforce_execution_mode(mode, action):
    """Deny side effects and unknown actions in explicit READ_ONLY mode."""
    read_actions = {"READ", "LIST", "INSPECT"}
    known_actions = read_actions | {"WRITE", "COMMIT", "PUSH", "MERGE", "DEPLOY", "MIGRATE", "DELETE", "EXECUTE", "OTHER"}
    if mode not in {"READ_ONLY", "AUTHORIZED_EXECUTION"}:
        raise MAEPError("unknown execution mode")
    if action not in known_actions:
        raise MAEPError("unknown action")
    if mode == "READ_ONLY" and action not in read_actions:
        raise MAEPError("side effect denied in READ_ONLY mode")
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
    if type(attempt_count) is not int or attempt_count < 0:
        raise MAEPError("attempt_count must be a non-negative integer")
    if type(safety_stop) is not bool or type(progress_possible) is not bool:
        raise MAEPError("retry stop flags must be booleans")
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
    """Enforce MAEP-1.2.0: MAEP-029/030 prohibitions remain system-wide."""
    del independent_evidence  # Evidence does not create an exception to MAEP-030.
    if review_type == "INDEPENDENT":
        raise MAEPError("independent-review workflows are prohibited by MAEP-030")
    if review_type != "INTERNAL_CRITIQUE":
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


CAPABILITY_EVOLUTION_DECISIONS = {
    "EXISTING_REUSE", "EXTEND_EXISTING", "CONSOLIDATE_KEEP_SUPERIOR",
    "DEPRECATE_OBSOLETE", "GENUINE_GAP", "UNKNOWN"
}
_CAPABILITY_GATE_REQUIRED_FIELDS = {
    "decision_id", "candidate_ref", "policy_version", "scope", "capability",
    "inventory_status", "inventory_evidence_refs", "overlap_detected",
    "comparison_evidence_refs", "decision", "rationale", "impact_analysis_refs",
    "regression_test_refs", "gate_status"
}
_CAPABILITY_SUPERIORITY_DIMENSIONS = {
    "correctness", "security", "reliability", "functional_coverage",
    "compatibility", "performance_resource_cost", "maintainability_operational_burden"
}


def validate_capability_evolution_decision(record, *, evidence_by_id=None, candidate_ref=None, policy_version=None):
    """Fail-closed MAEP-022/031 gate for capability overlap, retirement and evolution."""
    if not isinstance(record, dict):
        raise MAEPError("capability gate record must be an object")
    if not isinstance(evidence_by_id, dict):
        raise MAEPError("capability gate requires resolved candidate-bound evidence")
    missing = _CAPABILITY_GATE_REQUIRED_FIELDS - record.keys()
    if missing:
        raise MAEPError("capability gate missing fields: " + ", ".join(sorted(missing)))

    for field in ("decision_id", "candidate_ref", "policy_version", "scope", "capability", "rationale"):
        if not _nonempty_string(record[field]):
            raise MAEPError(f"capability gate {field} must be a non-empty string")
    if candidate_ref is not None and record["candidate_ref"] != candidate_ref:
        raise MAEPError("capability gate candidate mismatch")
    if policy_version is not None and record["policy_version"] != policy_version:
        raise MAEPError("capability gate policy version mismatch")
    if record["inventory_status"] != "COMPLETE":
        raise MAEPError("capability inventory incomplete; MAEP-022 fails closed")
    if not isinstance(record["overlap_detected"], bool):
        raise MAEPError("overlap_detected must be a boolean")
    for field in ("inventory_evidence_refs", "comparison_evidence_refs", "impact_analysis_refs", "regression_test_refs"):
        refs = record[field]
        if not isinstance(refs, list) or not all(_nonempty_string(ref) for ref in refs):
            raise MAEPError(f"{field} must be a list of non-empty evidence/test references")
    if not record["inventory_evidence_refs"]:
        raise MAEPError("capability gate requires inventory evidence")
    if not record["impact_analysis_refs"]:
        raise MAEPError("capability gate requires impact/dependency evidence")
    if not record["regression_test_refs"]:
        raise MAEPError("capability gate requires regression/migration test references")

    decision = record["decision"]
    if not isinstance(decision, str) or decision not in CAPABILITY_EVOLUTION_DECISIONS:
        raise MAEPError("unknown capability evolution decision")
    if decision == "UNKNOWN":
        raise MAEPError("UNKNOWN capability decision is blocked by MAEP-022")
    if record["gate_status"] != "PASS":
        raise MAEPError("capability gate status must be PASS before authorization")

    if record["overlap_detected"]:
        if decision == "GENUINE_GAP":
            raise MAEPError("overlap evidence conflicts with GENUINE_GAP decision")
        if not record["comparison_evidence_refs"]:
            raise MAEPError("overlapping capabilities require comparison evidence")
    elif decision == "CONSOLIDATE_KEEP_SUPERIOR":
        raise MAEPError("consolidation requires evidenced capability overlap")

    if decision == "EXISTING_REUSE" and not _nonempty_string(record.get("selected_implementation")):
        raise MAEPError("EXISTING_REUSE requires selected_implementation")
    if decision == "EXTEND_EXISTING" and not _nonempty_string(record.get("selected_implementation")):
        raise MAEPError("EXTEND_EXISTING requires selected_implementation")
    if decision == "GENUINE_GAP":
        for field in ("proposed_owner", "capability_boundary"):
            if not _nonempty_string(record.get(field)):
                raise MAEPError(f"GENUINE_GAP requires {field}")
        if not record["comparison_evidence_refs"]:
            raise MAEPError(
                "GENUINE_GAP requires comparison evidence showing no suitable existing capability"
            )

    if record["overlap_detected"]:
        basis = record.get("superiority_basis")
        if not isinstance(basis, dict) or not _CAPABILITY_SUPERIORITY_DIMENSIONS.issubset(basis):
            raise MAEPError("superiority basis must cover all MAEP-022 quality dimensions")
        if any(not _nonempty_string(basis[dimension]) for dimension in _CAPABILITY_SUPERIORITY_DIMENSIONS):
            raise MAEPError("every superiority dimension requires an evidenced rationale")

    if decision == "CONSOLIDATE_KEEP_SUPERIOR":
        if not _nonempty_string(record.get("selected_implementation")):
            raise MAEPError("consolidation requires selected_implementation")
        if not record["comparison_evidence_refs"]:
            raise MAEPError("consolidation requires comparison evidence")

    if decision == "DEPRECATE_OBSOLETE":
        if not _nonempty_string(record.get("obsolescence_basis")):
            raise MAEPError("DEPRECATE_OBSOLETE requires an evidence-linked obsolescence_basis")
        obsolescence_refs = record.get("obsolescence_evidence_refs")
        if (
            not isinstance(obsolescence_refs, list)
            or not obsolescence_refs
            or not all(_nonempty_string(item) for item in obsolescence_refs)
        ):
            raise MAEPError("DEPRECATE_OBSOLETE requires resolved obsolescence_evidence_refs")

    if decision in {"CONSOLIDATE_KEEP_SUPERIOR", "DEPRECATE_OBSOLETE"}:
        retired = record.get("retire_candidates")
        if not isinstance(retired, list) or not retired or not all(_nonempty_string(item) for item in retired):
            raise MAEPError("retirement requires explicit retire_candidates")
        if record.get("retirement_authorized") is not True or not _nonempty_string(record.get("retirement_authorization_ref")):
            raise MAEPError("retirement/removal requires explicit scoped authorization reference")
        if not _nonempty_string(record.get("recovery_plan_ref")):
            raise MAEPError("retirement/removal requires a recovery plan reference")

    # References are not evidence by themselves: resolve each one and bind it to this candidate.
    required_evidence_refs = set(
        record["inventory_evidence_refs"] + record["comparison_evidence_refs"] +
        record["impact_analysis_refs"] + record["regression_test_refs"]
    )
    if decision in {"CONSOLIDATE_KEEP_SUPERIOR", "DEPRECATE_OBSOLETE"}:
        required_evidence_refs.update({record["retirement_authorization_ref"], record["recovery_plan_ref"]})
    if decision == "DEPRECATE_OBSOLETE":
        required_evidence_refs.update(record["obsolescence_evidence_refs"])
    for evidence_ref in required_evidence_refs:
        evidence = evidence_by_id.get(evidence_ref)
        if not isinstance(evidence, dict) or evidence.get("evidence_id") != evidence_ref:
            raise MAEPError(f"capability gate evidence reference unresolved: {evidence_ref}")
        validate_evidence(evidence, record["candidate_ref"])
        # Results may carry explanatory prose (for example, "NOT_RUN — ...").
        # Only an explicit PASS status is admissible; exact-string deny lists fail open.
        result_text = evidence["result"].strip()
        result_status = result_text.split(maxsplit=1)[0].rstrip(":—-").upper()
        if result_status != "PASS":
            raise MAEPError(f"capability gate evidence is not passing: {evidence_ref}")

    return True


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
    """Validate source-linked research without granting authority or asserting truth.

    The MAEP validator is the canonical structural policy helper. Creativity & Research
    builds a workflow contract on top; this function intentionally performs no network
    access, source retrieval, persistence, orchestration, or external action.
    """
    if not isinstance(record, dict):
        raise MAEPError("research record must be an object")
    # The base MAEP helper also serves legacy records. The dedicated
    # Creativity & Research V1 contract requires research_id/question.
    if "research_id" in record and not _nonempty_string(record.get("research_id")):
        raise MAEPError("research_id must be a non-empty string when provided")
    if "question" in record and not _nonempty_string(record.get("question")):
        raise MAEPError("research question must be a non-empty string when provided")
    if not isinstance(record.get("sources"), list) or not record["sources"]:
        raise MAEPError("research requires at least one source")
    if not isinstance(record.get("claims"), list) or not record["claims"]:
        raise MAEPError("research requires claims linked to sources")
    if not isinstance(record.get("limitations"), list):
        raise MAEPError("research limitations must be a list")
    source_ids = set()
    for source in record["sources"]:
        if not isinstance(source, dict):
            raise MAEPError("each research source must be an object")
        source_id = source.get("source_id")
        if not _nonempty_string(source_id) or source_id in source_ids:
            raise MAEPError("research source IDs must be non-empty and unique")
        if not _nonempty_string(source.get("ref")):
            raise MAEPError("each research source requires a reference")
        if "source_type" in source and not _nonempty_string(source.get("source_type")):
            raise MAEPError("each research source source_type must be non-empty when provided")
        if "collection_method" in source and not _nonempty_string(source.get("collection_method")):
            raise MAEPError("each research source collection_method must be non-empty when provided")
        if "limitations" in source and not isinstance(source.get("limitations"), list):
            raise MAEPError("each research source limitations must be a list when provided")
        source_ids.add(source_id)
    claim_ids = set()
    for claim in record["claims"]:
        if not isinstance(claim, dict) or not claim.get("claim_id"):
            raise MAEPError("each research claim requires a claim_id")
        if claim["claim_id"] in claim_ids:
            raise MAEPError("research claim IDs must be unique")
        claim_ids.add(claim["claim_id"])
        if "statement" in claim and not _nonempty_string(claim.get("statement")):
            raise MAEPError("research claim statement must be non-empty when provided")
        if "claim_type" in claim and claim.get("claim_type") not in {"FACT", "INFERENCE", "HYPOTHESIS", "PROPOSAL"}:
            raise MAEPError("research claim has unknown claim_type")
        refs = claim.get("source_refs")
        if not isinstance(refs, list) or not refs or any(not _nonempty_string(ref) for ref in refs):
            raise MAEPError("each research claim requires source references")
        if len(set(refs)) != len(refs) or not set(refs).issubset(source_ids):
            raise MAEPError("research claim references unknown or duplicate sources")
        limitations = claim.get("limitations", [])
        if not isinstance(limitations, list):
            raise MAEPError("research claim limitations must be a list when provided")
        if claim.get("claim_type") == "FACT" and not claim.get("evidence_refs"):
            raise MAEPError("FACT research claims require evidence_refs")
        if claim.get("claim_type") in {"INFERENCE", "HYPOTHESIS", "PROPOSAL"} and not limitations:
            raise MAEPError("inference, hypothesis and proposal must disclose limitations")
        if "evidence_refs" in claim and (
            not isinstance(claim["evidence_refs"], list)
            or any(not _nonempty_string(ref) for ref in claim["evidence_refs"])
        ):
            raise MAEPError("claim evidence_refs must be a list of non-empty references")
    if "disagreements" in record and not isinstance(record["disagreements"], list):
        raise MAEPError("research disagreements must be a list")
    if "research_scope" in record and not _nonempty_string(record["research_scope"]):
        raise MAEPError("research_scope must be a non-empty string when provided")
    if "policy_version" in record and not _nonempty_string(record["policy_version"]):
        raise MAEPError("policy_version must be a non-empty string when provided")
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
