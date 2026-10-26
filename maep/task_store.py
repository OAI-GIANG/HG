"""TaskStore: the task-state owner for HG (RUNTIME_ENFORCEMENT_PLAN_V1 RT-01).

The store is the only mutation path for task state (MAEP-007). Callers record facts
(authorization requests, results, evidence, gates, closure, blockers, reassessments);
`apply_transition` derives every guard from those stored facts and calls
`maep.core.transition`. Callers never pass guard values.

Every accepted change is appended to the ledger before memory changes (MAEP-015); if the
append fails, the store is unchanged. Each mutation takes `expected_version` and rejects a
stale one (compare-and-set). Terminal tasks accept no new facts or transitions (MAEP-026).

Restart (RT-05): `TaskStore.restore` rebuilds records by replaying the ledger through the
same appliers that live mutations use, and refuses a history whose versions, event IDs
or transitions are inconsistent. A plain constructor still refuses a non-empty ledger.

Sole coordinator (MAEP-006): `claim_writer()` issues one TaskWriter; once claimed, every
mutation must come through it. The claim is an in-process capability, not OS isolation.

Policy-version history (MAEP-012): by default restore() refuses any event recorded under
another policy version. A caller migrating to a new version may name earlier versions in
`history_versions`; their events are replayed with the same checks, and every task they
touched becomes read-only history (`policy_status: "STALE"`, `recorded_policy_version`):
it can be read, but no fact, transition or effect is accepted for it. Unknown, newer or
non-earlier versions are refused. Nothing in the ledger is rewritten.

Limits: in-process only. Authority comes from an injected PolicyEvaluator, which is not
yet anchored to the trust root (RT-06). One authorization request is held per task.
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


def _version_key(version):
    """("MAEP-1.1.0") -> (1, 1, 0); anything else is not a policy version."""
    if not isinstance(version, str) or not version.startswith("MAEP-"):
        raise MAEPError(f"not a MAEP policy version: {version!r}")
    parts = version[5:].split(".")
    if len(parts) != 3 or not all(part.isdigit() and str(int(part)) == part for part in parts):
        raise MAEPError(f"not a MAEP policy version: {version!r}")
    return tuple(int(part) for part in parts)


def _history_versions(versions):
    """Validate the earlier policy versions a restore may replay as read-only history."""
    if isinstance(versions, str):
        raise MAEPError("history_versions must be a collection of versions, not one string")
    accepted = frozenset(versions)
    current = _version_key(POLICY_VERSION)
    for version in accepted:
        if _version_key(version) >= current:
            raise MAEPError(f"history version {version} is not earlier than the store policy {POLICY_VERSION}")
    return accepted


def _new_record(task):
    return {
        "task": copy.deepcopy(task), "version": 0, "authorization_request": None, "authorization_decision": None,
        "result": None, "evidence": {}, "mandatory_gates": [], "closure": None, "blockers": {},
        "reassessment": None, "blocked_at_version": None, "plan": None,
    }


def _apply_transition(record, data):
    record["task"]["state"] = data["to"]
    if data["to"] == "BLOCKED":
        record["blocked_at_version"] = record["version"]
    if data["from"] == "BLOCKED" and data["to"] == "ASSESSED":
        for blocker in record["blockers"].values():
            blocker["resolved"] = True


# One applier per event type, shared by live mutations and by restore() (RT-05).
_APPLIERS = {
    "AUTHORIZATION_EVALUATED": lambda r, d: r.update(authorization_request=copy.deepcopy(d["request"]),
                                                     authorization_decision=copy.deepcopy(d["decision"])),
    "RESULT_RECORDED": lambda r, d: r.update(result={"result_ref": d["result_ref"], "candidate_ref": d["candidate_ref"]}),
    "EVIDENCE_RECORDED": lambda r, d: r["evidence"].__setitem__(d["evidence"]["evidence_id"], copy.deepcopy(d["evidence"])),
    "GATES_SET": lambda r, d: r.update(mandatory_gates=copy.deepcopy(d["gates"])),
    "CLOSURE_RECORDED": lambda r, d: r.update(closure=copy.deepcopy(d["closure"])),
    "BLOCKER_RECORDED": lambda r, d: r["blockers"].__setitem__(d["blocker"]["blocker_id"], copy.deepcopy(d["blocker"])),
    "REASSESSMENT_RECORDED": lambda r, d: r.update(reassessment=copy.deepcopy(d)),
    "PLAN_RECORDED": lambda r, d: r.update(plan=copy.deepcopy(d["plan"])),
    "TRANSITION": _apply_transition,
}


class TaskWriter:
    """The single mutation handle issued by TaskStore.claim_writer() (MAEP-006)."""

    _METHODS = {"create_task", "record_authorization_request", "record_result", "record_evidence",
                "set_mandatory_gates", "record_closure", "record_blocker", "record_reassessment",
                "record_plan", "apply_transition"}

    def __init__(self, store, key):
        self._store = store
        self._key = key

    def __getattr__(self, name):
        if name not in self._METHODS:
            raise AttributeError(name)
        method = getattr(self._store, name)
        store, key = self._store, self._key

        def call(*args, **kwargs):
            with store._lock:
                store._active_writer = key
                try:
                    return method(*args, **kwargs)
                finally:
                    store._active_writer = None
        return call


def _utc_now():
    return datetime.now(timezone.utc)


class TaskStore:
    """Owns task records; every change is versioned, ledgered first and guard-checked."""

    def __init__(self, ledger_path, *, policy_evaluator=None, clock=None, ledger_append=None, _restoring=False):
        if not _restoring and read_events(ledger_path):
            raise MAEPError("ledger already holds events; use TaskStore.restore to resume from it (RT-05)")
        self._ledger_path = ledger_path
        self._evaluator = policy_evaluator
        self._clock = clock or _utc_now
        self._append = ledger_append or append_event
        self._records = {}
        self._lock = threading.RLock()
        self._writer_key = None
        self._active_writer = None

    @classmethod
    def restore(cls, ledger_path, *, policy_evaluator=None, clock=None, ledger_append=None,
                history_versions=()):
        """Rebuild a store from its ledger (RT-05). Inconsistent history fails closed.

        Stored authorization decisions are history only: every guard that needs authority
        re-evaluates the stored request with the evaluator given here. `history_versions`
        (default none) names earlier policy versions whose events are replayed as
        read-only history; see the module docstring.
        """
        accepted = _history_versions(history_versions)
        store = cls(ledger_path, policy_evaluator=policy_evaluator, clock=clock,
                    ledger_append=ledger_append, _restoring=True)
        for event in read_events(ledger_path):
            store._replay(event, accepted)
        return store

    def _replay(self, event, history_versions=frozenset()):
        kind, task_id, version, data = (event.get("type"), event.get("task_id"), event.get("version"),
                                        event.get("data"))
        if event.get("event_id") != f"{task_id}@{version}" or not isinstance(data, dict):
            raise MAEPError(f"ledger event {event.get('event_id')} is malformed")
        recorded = event.get("policy_version")
        if recorded != POLICY_VERSION and recorded not in history_versions:
            raise MAEPError("ledger event policy version does not match the store policy (MAEP-012)")
        if kind == "TASK_CREATED":
            if task_id in self._records or version != 1:
                raise MAEPError(f"ledger history inconsistent at {event['event_id']}")
            if recorded != POLICY_VERSION and data["task"].get("policy_version") != recorded:
                raise MAEPError(f"historical task does not carry its recorded policy at {event['event_id']}")
            record = _new_record(data["task"])
            record["version"] = 1
            if recorded != POLICY_VERSION:
                record["policy_status"], record["recorded_policy_version"] = "STALE", recorded
            self._records[task_id] = record
            return
        record = self._records.get(task_id)
        if record is None or version != record["version"] + 1 or kind not in _APPLIERS:
            raise MAEPError(f"ledger history inconsistent at {event['event_id']}")
        if (recorded == POLICY_VERSION) != (record.get("policy_status") != "STALE") or (
                recorded != POLICY_VERSION and recorded != record.get("recorded_policy_version")):
            # History is read-only: a task never mixes events of two policy versions.
            raise MAEPError(f"ledger mixes policy versions for one task at {event['event_id']}")
        if kind == "TRANSITION" and data.get("from") != record["task"]["state"]:
            raise MAEPError(f"ledger transition does not start from the recorded state at {event['event_id']}")
        record["version"] = version
        _APPLIERS[kind](record, data)

    def claim_writer(self):
        """Issue the only TaskWriter. After this, mutations without it are refused (MAEP-006)."""
        with self._lock:
            if self._writer_key is not None:
                raise MAEPError("task-state writer already claimed; BrainOrchestrator is the sole coordinator")
            self._writer_key = object()
            return TaskWriter(self, self._writer_key)

    def _require_writer(self):
        if self._writer_key is not None and self._active_writer is not self._writer_key:
            raise MAEPError("task-state writer is claimed; mutate only through it (MAEP-006)")

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
            self._require_writer()
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
            record = _new_record(task)

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

            self._commit(record, "AUTHORIZATION_EVALUATED", {"request": request, "decision": decision})
            return copy.deepcopy(decision)

    def record_result(self, task_id, *, result_ref, candidate_ref, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if record["task"]["state"] not in RESULT_STATES:
                raise MAEPError("results are recorded only while RUNNING or UNVERIFIED")
            if not _nonempty_string(result_ref) or not _nonempty_string(candidate_ref):
                raise MAEPError("result_ref and candidate_ref must be non-empty strings")
            result = {"result_ref": result_ref, "candidate_ref": candidate_ref}

            self._commit(record, "RESULT_RECORDED", result)

    def record_evidence(self, task_id, evidence, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            validate_evidence(evidence)
            evidence = copy.deepcopy(evidence)
            if evidence["evidence_id"] in record["evidence"]:
                raise MAEPError("evidence_id already recorded; append an amendment with a new ID")

            self._commit(record, "EVIDENCE_RECORDED", {"evidence": evidence})

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

            self._commit(record, "GATES_SET", {"gates": gates})

    def record_closure(self, task_id, closure, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if not isinstance(closure, dict):
                raise MAEPError("closure must be an object")
            closure = copy.deepcopy(closure)

            self._commit(record, "CLOSURE_RECORDED", {"closure": closure})

    def record_blocker(self, task_id, blocker, *, expected_version):
        with self._lock:
            record = self._open_record(task_id, expected_version)
            validate_blocker(blocker)
            blocker = dict(copy.deepcopy(blocker), resolved=False)
            if blocker["blocker_id"] in record["blockers"]:
                raise MAEPError("blocker_id already recorded")

            self._commit(record, "BLOCKER_RECORDED", {"blocker": blocker})

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

            self._commit(record, "REASSESSMENT_RECORDED", reassessment)

    def record_plan(self, task_id, plan, *, expected_version):
        """Record the ordered steps the coordinator will dispatch. Only while ASSESSED.

        The store checks shape only; the coordinator validates step semantics. The tool
        boundary reads steps from here, never from its caller.
        """
        with self._lock:
            record = self._open_record(task_id, expected_version)
            if record["task"]["state"] != "ASSESSED":
                raise MAEPError("a plan is recorded only while ASSESSED")
            if not isinstance(plan, list) or not plan or not all(isinstance(s, dict) for s in plan):
                raise MAEPError("plan must be a non-empty list of step objects")
            ids = [s.get("step_id") for s in plan]
            if not all(_nonempty_string(i) for i in ids) or len(set(ids)) != len(ids):
                raise MAEPError("plan steps need unique non-empty step_id values")
            self._commit(record, "PLAN_RECORDED", {"plan": copy.deepcopy(plan)})

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

            self._commit(record, "TRANSITION", {"from": current, "to": target})
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
        self._require_writer()
        record = self._record(task_id)
        if record.get("policy_status") == "STALE":
            raise MAEPError(f"task was recorded under {record.get('recorded_policy_version')}; it is read-only "
                            f"history under {POLICY_VERSION} (MAEP-012)")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise MAEPError("expected_version must be an integer")
        if expected_version != record["version"]:
            raise MAEPError(f"stale expected_version {expected_version}; current is {record['version']}")
        if record["task"]["state"] in TERMINAL_STATES:
            raise MAEPError("terminal task accepts no changes; continue with a linked task")
        return record

    def _commit(self, record, event_type, data, apply=None, new_record=False):
        """Append the event, then apply the change to a copy and swap it in.

        Live mutations use the same applier as restore() unless one is passed explicitly.
        """
        if record.get("policy_status") == "STALE":
            raise MAEPError(f"task was recorded under {record.get('recorded_policy_version')}; it is read-only "
                            f"history under {POLICY_VERSION} (MAEP-012)")
        if apply is None:
            applier = _APPLIERS[event_type]
            apply = lambda r: applier(r, data)  # noqa: E731
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
