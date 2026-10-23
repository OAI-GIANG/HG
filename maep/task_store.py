"""TaskStore: the task-state owner for HG (RUNTIME_ENFORCEMENT_PLAN_V1 RT-01).

The store is the only mutation path for task state (MAEP-007). Callers record facts
(authorization requests, results, evidence, gates, closure, blockers, reassessments);
`apply_transition` derives every guard from those stored facts and calls
`maep.core.transition`. Callers never pass guard values.

Every accepted change is appended to the ledger before memory changes (MAEP-015); if the
append fails, the store is unchanged. Each mutation takes `expected_version` and rejects a
stale one (compare-and-set). Terminal tasks accept no new facts or transitions (MAEP-026).

Limits: in-process only. Restart recovery from the ledger is RT-05, so a store refuses a
ledger that already holds events. Authority comes from an injected PolicyEvaluator,
which is not yet anchored to the trust root (RT-06).
"""
import copy
import threading
from datetime import datetime, timezone

from .core import (
    MAEPError, POLICY_VERSION, TERMINAL_STATES, _nonempty_string, evaluate_gate, transition,
    validate_blocker, validate_closure, validate_evidence, validate_linked_task, validate_task,
)
from .ledger import append_event, read_events

RESULT_STATES = {"RUNNING", "UNVERIFIED"}


def _utc_now():
    return datetime.now(timezone.utc)


class TaskStore:
    """Owns task records; every change is versioned, ledgered first and guard-checked."""

    def __init__(self, ledger_path, *, policy_evaluator=None, clock=None, ledger_append=None):
        if read_events(ledger_path):
            raise MAEPError("ledger already holds events; restart recovery (RT-05) is not implemented")
        self._ledger_path = ledger_path
        self._evaluator = policy_evaluator
        self._clock = clock or _utc_now
        self._append = ledger_append or append_event
        self._records = {}
        self._lock = threading.RLock()

    # ----- reads -------------------------------------------------------------------

    def snapshot(self, task_id):
        """Return a deep copy of one task record; changing it never changes the store."""
        with self._lock:
            record = self._record(task_id)
            view = copy.deepcopy(record)
            view["open_blockers"] = [b for b in view.pop("blockers").values() if not b["resolved"]]
            return view

    # ----- creation ----------------------------------------------------------------

    def create_task(self, task):
        """Register a new DRAFT task. Returns its version (1)."""
        with self._lock:
            validate_task(task)
            task = copy.deepcopy(task)
            if task["state"] != "DRAFT":
                raise MAEPError("a new task must start in DRAFT")
            if task["policy_version"] != POLICY_VERSION:
                raise MAEPError("task policy version does not match the store policy")
            if task["task_id"] in self._records:
                raise MAEPError("task_id already exists; continue with a linked task")
            for ref in task["inputs"]:
                if isinstance(ref, dict) and ref.get("kind") == "TASK":
                    predecessor = self._records.get(ref.get("ref_id"))
                    if predecessor is None:
                        raise MAEPError("TASK input references an unknown task")
                    if predecessor["task"]["state"] in TERMINAL_STATES:
                        validate_linked_task(predecessor["task"], task)
            record = {
                "task": task, "version": 0, "authorization_request": None, "authorization_decision": None,
                "result": None, "evidence": {}, "mandatory_gates": [], "closure": None, "blockers": {},
                "reassessment": None, "blocked_at_version": None,
            }

            def apply(r):
                self._records[task["task_id"]] = r

            self._commit(record, "TASK_CREATED", {"task": task}, apply, new_record=True)
            return 1

    # ----- facts -------------------------------------------------------------------

    def record_authorization_request(self, task_id, request, *, expected_version):
        """Evaluate and store the request this task will use for AUTHORIZED and RUNNING."""
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if self._evaluator is None:
                raise MAEPError("no authority provider configured (BLOCKED_FOR_TRUST_INTEGRATION, RT-06)")
            if not isinstance(request, dict) or request.get("task_id") != task_id:
                raise MAEPError("authorization request must be for this task")
            request = copy.deepcopy(request)
            decision = self._evaluator.evaluate(request, now=self._clock())

            def apply(r):
                r["authorization_request"] = request
                r["authorization_decision"] = decision

            self._commit(record, "AUTHORIZATION_EVALUATED", {"request": request, "decision": decision}, apply)
            return copy.deepcopy(decision)

    def record_result(self, task_id, *, result_ref, candidate_ref, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if record["task"]["state"] not in RESULT_STATES:
                raise MAEPError("results are recorded only while RUNNING or UNVERIFIED")
            if not _nonempty_string(result_ref) or not _nonempty_string(candidate_ref):
                raise MAEPError("result_ref and candidate_ref must be non-empty strings")
            result = {"result_ref": result_ref, "candidate_ref": candidate_ref}

            def apply(r):
                r["result"] = result

            self._commit(record, "RESULT_RECORDED", result, apply)

    def record_evidence(self, task_id, evidence, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            validate_evidence(evidence)
            evidence = copy.deepcopy(evidence)
            if evidence["evidence_id"] in record["evidence"]:
                raise MAEPError("evidence_id already recorded; append an amendment with a new ID")

            def apply(r):
                r["evidence"][evidence["evidence_id"]] = evidence

            self._commit(record, "EVIDENCE_RECORDED", {"evidence": evidence}, apply)

    def set_mandatory_gates(self, task_id, gates, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if not isinstance(gates, list) or not gates:
                raise MAEPError("mandatory gates must be a non-empty list")
            for gate in gates:
                if not isinstance(gate, dict) or gate.get("required") is not True:
                    raise MAEPError("every mandatory gate must be an object with required: true")
                refs = gate.get("evidence_refs")
                if not isinstance(refs, list) or not refs or any(ref not in record["evidence"] for ref in refs):
                    raise MAEPError("gate evidence_refs must name evidence recorded for this task")
            gates = copy.deepcopy(gates)

            def apply(r):
                r["mandatory_gates"] = gates

            self._commit(record, "GATES_SET", {"gates": gates}, apply)

    def record_closure(self, task_id, closure, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if not isinstance(closure, dict):
                raise MAEPError("closure must be an object")
            closure = copy.deepcopy(closure)

            def apply(r):
                r["closure"] = closure

            self._commit(record, "CLOSURE_RECORDED", {"closure": closure}, apply)

    def record_blocker(self, task_id, blocker, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            validate_blocker(blocker)
            blocker = dict(copy.deepcopy(blocker), resolved=False)
            if blocker["blocker_id"] in record["blockers"]:
                raise MAEPError("blocker_id already recorded")

            def apply(r):
                r["blockers"][blocker["blocker_id"]] = blocker

            self._commit(record, "BLOCKER_RECORDED", {"blocker": blocker}, apply)

    def record_reassessment(self, task_id, *, resolution_evidence_refs, risk_assessment, expected_version):
        """Record why a BLOCKED task may reopen; authority is re-checked at the transition."""
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if record["task"]["state"] != "BLOCKED":
                raise MAEPError("reassessment is recorded only while BLOCKED")
            refs = resolution_evidence_refs
            if (not isinstance(refs, list) or not refs or not all(_nonempty_string(r) for r in refs)
                    or any(r not in record["evidence"] for r in refs)):
                raise MAEPError("resolution evidence must name evidence recorded for this task")
            if not _nonempty_string(risk_assessment):
                raise MAEPError("risk assessment must be a non-empty string")
            reassessment = {"resolution_evidence_refs": list(refs), "risk_assessment": risk_assessment,
                            "version": record["version"] + 1}

            def apply(r):
                r["reassessment"] = reassessment

            self._commit(record, "REASSESSMENT_RECORDED", reassessment, apply)

    # ----- transitions -------------------------------------------------------------

    def apply_transition(self, task_id, target, *, expected_version):
        """Move a task to `target` if guards derived from stored facts allow it."""
        with self._lock:
            record = self._open_record(task_id, expected_version)
            current = record["task"]["state"]
            guards, blocker_resolved = self._derive_guards(record, current, target)
            transition(current, target, guards=guards, blocker_resolved=blocker_resolved)
            if target == "BLOCKED" and not any(not b["resolved"] for b in record["blockers"].values()):
                raise MAEPError("entering BLOCKED requires a recorded blocker (MAEP-025)")

            def apply(r):
                r["task"]["state"] = target
                if target == "BLOCKED":
                    r["blocked_at_version"] = r["version"]
                if current == "BLOCKED" and target == "ASSESSED":
                    for blocker in r["blockers"].values():
                        blocker["resolved"] = True

            self._commit(record, "TRANSITION", {"from": current, "to": target}, apply)
            return self._records[task_id]["version"]

    def _derive_guards(self, record, current, target):
        guards, blocker_resolved = {}, False
        if target == "READY":
            guards["task_valid"] = self._passes(validate_task, record["task"])
        if target in {"AUTHORIZED", "RUNNING"}:
            guards["authorization_valid"] = self._authority_allows(record)
        if target == "VERIFYING" and record["result"] is not None:
            guards["result_recorded"] = True
            guards["candidate_ref"] = record["result"]["candidate_ref"]
        if target in {"ACCEPTED", "CLOSED_VERIFIED"}:
            guards["mandatory_gates_pass"] = self._gates_pass(record)
        if target == "CLOSED_VERIFIED":
            closure_ok = self._closure_valid(record)
            guards["criteria_pass"] = closure_ok
            guards["evidence_resolved"] = closure_ok
            guards["no_mandatory_blocker"] = not any(not b["resolved"] for b in record["blockers"].values())
        if current == "BLOCKED" and target == "ASSESSED":
            reassessment = record["reassessment"]
            fresh = (reassessment is not None and record["blocked_at_version"] is not None
                     and reassessment["version"] > record["blocked_at_version"])
            if fresh:
                blocker_resolved = True
                guards["blocker_resolution_evidence_refs"] = list(reassessment["resolution_evidence_refs"])
                guards["risk_reassessed"] = True
                guards["authority_reassessed"] = self._authority_allows(record)
        return guards, blocker_resolved

    def _authority_allows(self, record):
        if self._evaluator is None or record["authorization_request"] is None:
            return False
        decision = self._evaluator.evaluate(copy.deepcopy(record["authorization_request"]), now=self._clock())
        return decision.get("decision") == "ALLOW"

    def _gates_pass(self, record):
        gates, result = record["mandatory_gates"], record["result"]
        if not gates or result is None:
            return False
        return all(evaluate_gate(g, record["evidence"], result["candidate_ref"]) is True for g in gates)

    def _closure_valid(self, record):
        closure, result = record["closure"], record["result"]
        if closure is None or result is None or closure.get("final_state") != "CLOSED_VERIFIED":
            return False
        return self._passes(validate_closure, closure, mandatory_gates=record["mandatory_gates"],
                            evidence_by_id=record["evidence"], candidate_ref=result["candidate_ref"],
                            policy_version=POLICY_VERSION)

    @staticmethod
    def _passes(check, *args, **kwargs):
        try:
            return check(*args, **kwargs) is True
        except MAEPError:
            return False

    # ----- internals ---------------------------------------------------------------

    def _record(self, task_id):
        if task_id not in self._records:
            raise MAEPError("unknown task_id")
        return self._records[task_id]

    def _open_record(self, task_id, expected_version):
        record = self._record(task_id)
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise MAEPError("expected_version must be an integer")
        if expected_version != record["version"]:
            raise MAEPError(f"stale expected_version {expected_version}; current is {record['version']}")
        if record["task"]["state"] in TERMINAL_STATES:
            raise MAEPError("terminal task accepts no changes; continue with a linked task")
        return record

    def _commit(self, record, event_type, data, apply, new_record=False):
        """Append the event, then apply the change to a copy and swap it in."""
        version = record["version"] + 1
        task_id = record["task"]["task_id"]
        event = {
            "event_id": f"{task_id}@{version}", "type": event_type, "task_id": task_id, "version": version,
            "policy_version": POLICY_VERSION, "recorded_at": self._clock().isoformat(), "data": copy.deepcopy(data),
        }
        try:
            self._append(self._ledger_path, event)
        except (OSError, MAEPError) as exc:
            raise MAEPError(f"ledger append failed; state unchanged ({exc})") from exc
        updated = copy.deepcopy(record)
        updated["version"] = version
        apply(updated)
        if not new_record:
            self._records[task_id] = updated
