"""BrainOrchestrator: sole task coordinator (RT-04; MAEP-006, 008, 014, 018, 025).

Implements the core of BO-CONTRACT-1.0 on top of the task-state owner
`maep.task_store.TaskStore`: submit, plan, authorize, run (dispatch only through
ActionGateway), verify, accept, close, and reopen/resume after a resolved blocker.
It claims the store's only TaskWriter, so no other component can move task state.
It never passes guard values: the store derives every guard from recorded facts.

What this is not: plans are supplied as structured data. HG Brain reasoning, model
providers and autonomous planning are not built yet (capability matrix C-12, C-13).
Verifiers are trusted in-process code registered at construction; their evidence is
labelled internal, not independent review (MAEP-021).
"""
import hashlib
import json
import uuid

from maep.core import MAEPError, _nonempty_string, retry_decision
from hg.brain.plan import step_request, validate_plan

COLLECTOR = "hg.security_verification"
INTERNAL_LIMITATION = "in-process verifier; internal check, not independent review"

_MISSING_PREREQUISITE = {
    "DENIED": "permission for this exact step: a policy ALLOW, a permitting execution mode and an in-scope effect",
    "UNKNOWN": "reconciliation of the uncertain action against live state",
    "SUCCEEDED_UNVERIFIED": "a passing post-condition check for this step",
    "TOOL_UNAVAILABLE": "the named tool registered in the gateway",
    "INVALID_INPUT": "valid parameters for the planned step",
    "FAILED": "a working approach (retry limit reached)",
    "BLOCKED": "the gateway precondition named in the reason",
}


def _candidate_ref(outcomes):
    material = json.dumps([{k: o.get(k) for k in ("step_id", "status", "observed")} for o in outcomes],
                          sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class BrainOrchestrator:
    def __init__(self, store, gateway, acceptance_gate, *, principal, verifiers=None):
        if not _nonempty_string(principal):
            raise MAEPError("orchestrator principal must be non-empty")
        verifiers = dict(verifiers or {})
        if not all(_nonempty_string(k) and callable(v) for k, v in verifiers.items()):
            raise MAEPError("verifiers must map criterion_id to a callable")
        self._store = store
        self._writer = store.claim_writer()
        self._gateway = gateway
        self._gate = acceptance_gate
        self._principal = principal
        self._verifiers = verifiers

    # ---------- helpers ----------

    def get_task_state(self, task_id):
        return self._store.snapshot(task_id)

    def _version(self, task_id):
        return self._store.snapshot(task_id)["version"]

    def _move(self, task_id, target):
        return self._writer.apply_transition(task_id, target, expected_version=self._version(task_id))

    def _evidence(self, task_id, *, evidence_type, source_ref, candidate_ref, method, result,
                  limitations, criterion_id=None, detail=None):
        record = {
            "evidence_id": f"EV-{uuid.uuid4().hex[:12]}", "evidence_type": evidence_type,
            "source_ref": source_ref, "candidate_ref": candidate_ref,
            "collected_at": self._gateway.now().isoformat(), "collector": COLLECTOR,
            "method": method, "result": result, "limitations": list(limitations),
        }
        if criterion_id is not None:
            record["test_ids"] = [criterion_id]
        if detail is not None:
            record["integrity_metadata"] = {"detail": str(detail)[:500]}
        self._writer.record_evidence(task_id, record, expected_version=self._version(task_id))
        return record["evidence_id"]

    def record_observation(self, task_id, *, source_ref, method, result, limitations=()):
        """Evidence not tied to an acceptance criterion (e.g. a denial or a blocker resolution)."""
        return self._evidence(task_id, evidence_type="OBSERVATION", source_ref=source_ref,
                              candidate_ref=f"task:{task_id}", method=method, result=result,
                              limitations=limitations)

    # ---------- lifecycle ----------

    def submit_task(self, task):
        self._writer.create_task(task)
        self._move(task["task_id"], "READY")
        return task["task_id"]

    def assess(self, task_id):
        self._move(task_id, "ASSESSED")

    def plan(self, task_id, steps):
        validate_plan(steps)
        self._writer.record_plan(task_id, steps, expected_version=self._version(task_id))
        self._move(task_id, "PLANNED")

    def authorize(self, task_id):
        """PLANNED -> AUTHORIZED only if every step is allowed now (no partial plans).

        The store holds one authorization request per task (the first step's); the
        gateway re-checks each step's own request immediately before its effect.
        """
        denied = [p for p in self._gateway.preflight(task_id) if p["decision"]["decision"] != "ALLOW"]
        if denied:
            reasons = "; ".join(f"{p['step_id']}: {p['decision']['reason']}" for p in denied)
            raise MAEPError(f"authorization not granted for every step ({reasons})")
        first = self._store.snapshot(task_id)["plan"][0]
        self._writer.record_authorization_request(task_id, step_request(first, self._principal, task_id),
                                                  expected_version=self._version(task_id))
        self._move(task_id, "AUTHORIZED")

    def run(self, task_id):
        self._move(task_id, "RUNNING")
        outcomes = []
        for step in self._store.snapshot(task_id)["plan"]:
            attempts = 0
            while True:
                attempts += 1
                outcome = self._gateway.execute(task_id, step["step_id"])
                # FAILED means a known failure with no effect, so a retry is not a blind replay.
                if outcome["status"] != "FAILED" or retry_decision(attempts) == "STOP":
                    break
            outcomes.append({"step_id": step["step_id"], "status": outcome["status"],
                             "reason": outcome["reason"], "attempts": attempts,
                             "action_id": outcome.get("action_id"),
                             "observed": {k: v for k, v in (outcome.get("observed") or {}).items()
                                          if k != "content"}})
            if outcome["status"] != "SUCCEEDED":
                self._block(task_id, step["step_id"], outcome)
                return {"state": "BLOCKED", "outcomes": outcomes}
        candidate = _candidate_ref(outcomes)
        result_ref = "actions:" + ",".join(o["action_id"] for o in outcomes)
        self._writer.record_result(task_id, result_ref=result_ref, candidate_ref=candidate,
                                   expected_version=self._version(task_id))
        self._move(task_id, "VERIFYING")
        return {"state": "VERIFYING", "candidate_ref": candidate, "outcomes": outcomes}

    def _block(self, task_id, step_id, outcome):
        status = outcome["status"]
        blocker = {
            "blocker_id": f"BLK-{task_id}-{step_id}-{uuid.uuid4().hex[:8]}",
            "known_cause": f"{status}: {outcome['reason'] or 'no reason given'}",
            "unknowns": ["whether the effect was applied"] if status == "UNKNOWN" else [],
            "missing_prerequisite": _MISSING_PREREQUISITE.get(status, "resolution of the outcome"),
            "next_action": ("reconcile action " + outcome["action_id"]) if status == "UNKNOWN"
                           else "resolve the missing prerequisite, then reopen with evidence",
            "reopen_condition": "evidence that the prerequisite now holds, plus fresh authority and risk assessment",
        }
        self._writer.record_blocker(task_id, blocker, expected_version=self._version(task_id))
        self._move(task_id, "BLOCKED")

    def verify(self, task_id):
        """Run registered verifiers, record their evidence, then let the gate and store decide."""
        snapshot = self._store.snapshot(task_id)
        if snapshot["task"]["state"] != "VERIFYING":
            raise MAEPError("verify requires VERIFYING")
        candidate = snapshot["result"]["candidate_ref"]
        for criterion in snapshot["task"]["acceptance_criteria"]:
            cid = criterion["criterion_id"]
            verifier = self._verifiers.get(cid)
            if verifier is None:
                continue                      # gate stays NOT_RUN; never assumed PASS (MAEP-024)
            try:
                passed, detail = verifier(self._store.snapshot(task_id))
                result = "PASS" if passed is True else "FAIL"
            except Exception as exc:
                result, detail = "FAIL", f"verifier raised {type(exc).__name__}: {exc}"
            self._evidence(task_id, evidence_type="TEST_RESULT", source_ref=f"verifier:{cid}",
                           candidate_ref=candidate, method=getattr(verifier, "__name__", "verifier"),
                           result=result, limitations=[INTERNAL_LIMITATION], criterion_id=cid, detail=detail)
        report = self._gate.evaluate(self._store.snapshot(task_id))
        if not report["passed"]:
            self._move(task_id, "UNVERIFIED")
            return "UNVERIFIED"
        self._writer.set_mandatory_gates(task_id, report["mandatory_gates"], expected_version=self._version(task_id))
        self._move(task_id, "ACCEPTED")       # the store re-evaluates the gates itself
        return "ACCEPTED"

    def close(self, task_id):
        closure = self._gate.build_closure(self._store.snapshot(task_id))
        self._writer.record_closure(task_id, closure, expected_version=self._version(task_id))
        self._move(task_id, "CLOSED_VERIFIED")  # the store re-validates the closure itself
        return self._store.snapshot(task_id)["closure"]

    def execute_task(self, task, steps):
        """Drive one task as far as evidence allows. Returns the final snapshot."""
        task_id = self.submit_task(task)
        self.assess(task_id)
        self.plan(task_id, steps)
        return self._authorize_and_finish(task_id)

    def _authorize_and_finish(self, task_id):
        # The state table allows PLANNED -> AUTHORIZED only, so a task without authority
        # stays PLANNED; the refusal is preserved as evidence (MAEP-005, 015).
        try:
            self.authorize(task_id)
        except MAEPError as exc:
            self.record_observation(task_id, source_ref="policy-evaluator", method="ActionGateway.preflight",
                                    result=f"DENY: {exc}", limitations=["task remains PLANNED until a grant exists"])
            return self._store.snapshot(task_id)
        if self.run(task_id)["state"] == "VERIFYING" and self.verify(task_id) == "ACCEPTED":
            self.close(task_id)
        return self._store.snapshot(task_id)

    # ---------- recovery ----------

    def reconcile_and_reopen(self, task_id, action_id, *, risk_reassessment):
        """Inspect live state for an uncertain action; reopen the task only if the outcome is now known."""
        pending = {p["action_id"]: p for p in self._gateway.pending_actions(task_id)}
        if action_id not in pending:
            raise MAEPError("no pending action with that id on this task")
        finding = self._gateway.reconcile(action_id)
        evidence_id = self.record_observation(
            task_id, source_ref=f"reconcile:{action_id}", method="adapter.reconcile",
            result=finding["finding"], limitations=["live-state inspection by the tool adapter"])
        if finding["finding"] == "UNKNOWN":
            return {"state": self._store.snapshot(task_id)["task"]["state"], "finding": finding}
        self.reopen(task_id, evidence_refs=[evidence_id], risk_reassessment=risk_reassessment)
        return {"state": "ASSESSED", "finding": finding}

    def reopen(self, task_id, *, evidence_refs, risk_reassessment):
        """BLOCKED -> ASSESSED. The store requires a fresh reassessment and re-checks authority."""
        self._writer.record_reassessment(task_id, resolution_evidence_refs=list(evidence_refs),
                                         risk_assessment=risk_reassessment,
                                         expected_version=self._version(task_id))
        self._move(task_id, "ASSESSED")

    def resume(self, task_id):
        """Continue a reopened (ASSESSED) or not-yet-authorized (PLANNED) task with its recorded plan.

        Authority is re-evaluated against the current grant store, never carried over.
        """
        state = self._store.snapshot(task_id)["task"]["state"]
        if state == "ASSESSED":
            self._move(task_id, "PLANNED")
        elif state != "PLANNED":
            raise MAEPError(f"resume requires ASSESSED or PLANNED, task is {state}")
        return self._authorize_and_finish(task_id)
