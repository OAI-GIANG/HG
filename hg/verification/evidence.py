"""Action event log and acceptance gate (Security & Verification; RT-03, MAEP-008, 011, 013).

Task evidence, gates and closure live in the task-state owner (`maep.task_store.TaskStore`),
which re-validates them at ACCEPTED and CLOSED_VERIFIED. AcceptanceGate only computes the
gate and closure records from a store snapshot; it cannot make a transition happen.

HG convention: an evidence record's `test_ids` lists the acceptance-criterion IDs it checks.

EventLog is the single writer for the tool-action ledger (separate from the task ledger).
It inherits maep/ledger.py's limits: append-only through this API, not tamper-proof.
"""
import copy
import threading
import uuid
from datetime import datetime, timezone

from maep import ledger
from maep.core import MAEPError, POLICY_VERSION, _nonempty_string, evaluate_gate, validate_closure
from maep.admission import require_writer_session
from hg.assistant.home import home_for_path, locked


def utcnow():
    return datetime.now(timezone.utc)


class EventLog:
    """Single writer over one ledger file. A corrupt or non-contiguous ledger fails at construction."""

    def __init__(self, path, *, clock=utcnow, writer_session=None, read_only=False):
        # A read-only view needs no writer admission because it can never append (operator
        # status/health tools and the switch precheck read state the service may own).
        self._read_only = bool(read_only)
        self._writer_session = None if self._read_only else require_writer_session(path, writer_session)
        self._path = path
        self._home = home_for_path(path)
        self._clock = clock
        self._lock = threading.RLock()
        if self._home is None:
            self._events = ledger.read_events(path)
        else:
            with locked(self._home, exclusive=False):
                self._events = ledger.read_events(path)
        for event in self._events:
            if not isinstance(event.get("kind"), str) or not isinstance(event.get("seq"), int):
                raise MAEPError(f"ledger event {event['event_id']} lacks kind/seq")
        if [e["seq"] for e in self._events] != list(range(1, len(self._events) + 1)):
            raise MAEPError("ledger sequence numbers are not contiguous")

    @property
    def path(self):
        return self._path

    def now(self):
        return self._clock()

    def next_seq(self):
        return len(self.events()) + 1

    def events(self, kind=None):
        with self._lock:
            if self._home is None:
                current = ledger.read_events(self._path)
            else:
                with locked(self._home, exclusive=False):
                    current = ledger.read_events(self._path)
            self._events = current
            selected = self._events if kind is None else [e for e in self._events if e["kind"] == kind]
            return copy.deepcopy(selected)

    def append(self, kind, task_id, payload=None, *, payload_factory=None, task_id_factory=None):
        """Write one event to disk before it becomes visible in memory.

        Two writers that assign the same sequence number would leave a ledger that no longer
        loads (the constructor refuses a non-contiguous sequence), so the number and the
        append happen under one lock.
        """
        if self._read_only:
            raise MAEPError("read-only ledger view refuses appends")
        if not _nonempty_string(kind):
            raise MAEPError("event kind must be non-empty")
        if payload_factory is not None and not callable(payload_factory):
            raise MAEPError("payload_factory must be callable")
        with self._lock:
            latest = []

            def build(current):
                if [e.get("seq") for e in current] != list(range(1, len(current) + 1)):
                    raise MAEPError("ledger sequence numbers are not contiguous")
                current_payload = payload_factory(current) if payload_factory is not None else payload
                current_task_id = task_id_factory(current) if task_id_factory is not None else task_id
                event = {"event_id": uuid.uuid4().hex, "seq": len(current) + 1, "kind": kind,
                         "task_id": current_task_id, "at": self._clock().isoformat(),
                         "payload": copy.deepcopy(current_payload)}
                latest[:] = current
                latest.append(event)
                return event

            if self._home is None:
                event = ledger.append_generated(self._path, build)
            else:
                with locked(self._home, exclusive=True):
                    event = ledger.append_generated(self._path, build)
            self._events = latest
            return copy.deepcopy(event)


class AcceptanceGate:
    """One gate per acceptance criterion, computed from evidence held by the task store."""

    def __init__(self, *, clock=utcnow, policy_version=POLICY_VERSION):
        self._clock = clock
        self._policy_version = policy_version

    @staticmethod
    def _candidate(snapshot):
        return (snapshot.get("result") or {}).get("candidate_ref")

    def gates(self, snapshot):
        """A failing record for this candidate fails its gate; recovery needs a new candidate."""
        task, candidate = snapshot["task"], self._candidate(snapshot)
        records = list(snapshot["evidence"].values())
        gates = []
        for criterion in task["acceptance_criteria"]:
            cid = criterion["criterion_id"]
            matching = [ev for ev in records
                        if cid in (ev.get("test_ids") or []) and candidate is not None
                        and ev["candidate_ref"] == candidate
                        and ev["evidence_type"] in criterion.get("evidence_types", [])]
            if not matching:
                status = "NOT_RUN"
            elif any(ev["result"] != "PASS" for ev in matching):
                status = "FAIL"
            else:
                status = "PASS"
            gates.append({"gate_id": f"GATE-{cid}", "task_id": task["task_id"], "candidate_ref": candidate,
                          "required": criterion.get("mandatory") is True, "status": status,
                          "criteria_refs": [cid], "evidence_refs": [ev["evidence_id"] for ev in matching]})
        return gates

    def evaluate(self, snapshot):
        gates = self.gates(snapshot)
        required = [g for g in gates if g["required"]]
        candidate = self._candidate(snapshot)
        passed = bool(required) and all(evaluate_gate(g, snapshot["evidence"], candidate) for g in required)
        return {"passed": passed, "candidate_ref": candidate, "gates": gates, "mandatory_gates": required}

    def build_closure(self, snapshot, *, limitations=()):
        """Return a CLOSED_VERIFIED closure record, or raise MAEPError if it cannot be justified."""
        task, candidate = snapshot["task"], self._candidate(snapshot)
        required = [g for g in self.gates(snapshot) if g["required"]]
        refs = list(dict.fromkeys(r for g in required for r in g["evidence_refs"]))
        closure = {
            "closure_id": f"CLOSURE-{task['task_id']}", "task_id": task["task_id"],
            "final_state": "CLOSED_VERIFIED", "candidate_ref": candidate,
            "policy_version": self._policy_version,
            "criteria_results": [{"criterion_id": g["criteria_refs"][0], "status": g["status"],
                                  "evidence_refs": list(g["evidence_refs"])} for g in required],
            "gate_refs": [g["gate_id"] for g in required], "evidence_refs": refs,
            "limitations": list(limitations), "closed_at": self._clock().isoformat(),
        }
        validate_closure(closure, mandatory_gates=required, evidence_by_id=snapshot["evidence"],
                         candidate_ref=candidate, policy_version=self._policy_version)
        return closure
