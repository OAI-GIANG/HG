"""C-14 Layered memory with provenance (MIID layer 7, MAEP-009, 010, 015).

Layers
    WORKING    per-task scratch, in memory only, cleared with the task
    EPISODIC   what happened (task outcomes, executions); append-only
    SEMANTIC   knowledge about the world: facts, inferences, hypotheses
    PROJECT    decisions, contracts, preferences that steer future work
Evidence itself stays in the task store; memory records point to it (evidence_refs).

Invariants
- Every record names its source (USER, TOOL, EVIDENCE, INFERENCE, SYSTEM) and a source_ref.
- Kinds keep their meaning (MAEP-009): a FACT needs evidence_refs; INFERENCE, HYPOTHESIS
  and PROPOSAL must disclose limitations; nothing is promoted to FACT without evidence.
  A NOTE is what the owner told HG (source USER, layer SEMANTIC or PROJECT): recorded as
  said, never a verified claim, never promoted.
- In SEMANTIC and PROJECT, a FACT or DECISION that contradicts the ACTIVE record on the
  same subject is refused (MemoryConflict) unless it explicitly supersedes that record.
- Nothing is overwritten: supersede and retract append status events (MAEP-015);
  history() returns every version.
- Memory never grants authority: HG's authorization path does not read it (tested).

Persistence: append-only JSONL through EventLog; restore() replays it and reports any
subject left with competing ACTIVE records.
"""
import copy
import uuid
from datetime import datetime, timezone

from maep.core import MAEPError, _nonempty_string, validate_claim
from hg.memory.index import Index
from hg.verification.evidence import EventLog

LAYERS = {"WORKING", "EPISODIC", "SEMANTIC", "PROJECT"}
KINDS = {"FACT", "INFERENCE", "HYPOTHESIS", "PROPOSAL", "DECISION", "PREFERENCE", "EVENT", "NOTE"}
SOURCES = {"USER", "TOOL", "EVIDENCE", "INFERENCE", "SYSTEM"}
CLAIM_KINDS = {"FACT", "INFERENCE", "HYPOTHESIS", "PROPOSAL"}
CONFLICT_LAYERS = {"SEMANTIC", "PROJECT"}
CONFLICT_KINDS = {"FACT", "DECISION"}


class MemoryConflict(MAEPError):
    def __init__(self, subject, existing_ids):
        self.subject, self.existing_ids = subject, list(existing_ids)
        super().__init__(f"memory conflict on {subject!r}: contradicts active {', '.join(existing_ids)}; "
                         "supersede it explicitly or record a HYPOTHESIS")


def _norm(record):
    if record.get("value") is not None:
        return ("value", repr(record["value"]))
    return ("content", " ".join(record["content"].lower().split()))


class MemoryStore:
    def __init__(self, path, *, clock=None):
        self._log = EventLog(path, clock=clock or (lambda: datetime.now(timezone.utc)))
        self._records = {}
        self._working = {}
        self._index = Index()
        self.restore_conflicts = []
        for event in self._log.events():
            self._replay(event)
        self.restore_conflicts = self.conflicts()

    # ---------- write ----------

    def remember(self, *, layer, kind, subject, content, source, source_ref, evidence_refs=(), limitations=(),
                 value=None, task_id=None, supersedes=None):
        record = {
            "memory_id": f"M-{self._log.next_seq():06d}-{uuid.uuid4().hex[:6]}", "layer": layer, "kind": kind,
            "subject": subject, "content": content, "value": copy.deepcopy(value), "source": source,
            "source_ref": source_ref, "evidence_refs": list(evidence_refs), "limitations": list(limitations),
            "task_id": task_id, "supersedes": supersedes, "status": "ACTIVE", "version": 1,
            "created_at": self._log.now().isoformat(),
        }
        self._validate(record)
        if layer == "WORKING":
            if not _nonempty_string(task_id):
                raise MAEPError("WORKING memory needs a task_id")
            self._working.setdefault(task_id, []).append(record)
            return copy.deepcopy(record)
        previous = self._check_supersession_and_conflict(record)
        if previous is not None:
            record["version"] = previous["version"] + 1
        self._log.append("MEMORY_WRITE", task_id, {"record": record})
        self._apply_write(record)
        return copy.deepcopy(record)

    def promote(self, memory_id, *, evidence_refs, source_ref):
        """HYPOTHESIS/INFERENCE -> FACT, only with evidence; the old record is superseded, not edited."""
        old = self._active(memory_id)
        if old["kind"] not in {"HYPOTHESIS", "INFERENCE"}:
            raise MAEPError("only a HYPOTHESIS or INFERENCE can be promoted")
        if not evidence_refs:
            raise MAEPError("promotion to FACT requires evidence_refs")
        return self.remember(layer=old["layer"], kind="FACT", subject=old["subject"], content=old["content"],
                             value=old["value"], source="EVIDENCE", source_ref=source_ref,
                             evidence_refs=evidence_refs, task_id=old["task_id"], supersedes=memory_id)

    def retract(self, memory_id, *, reason):
        self._active(memory_id)
        if not _nonempty_string(reason):
            raise MAEPError("retraction needs a reason")
        payload = {"memory_id": memory_id, "status": "RETRACTED", "reason": reason}
        self._log.append("MEMORY_STATUS", self._records[memory_id]["task_id"], payload)
        self._apply_status(payload)

    def clear_working(self, task_id):
        self._working.pop(task_id, None)

    # ---------- read ----------

    def get(self, memory_id):
        if memory_id not in self._records:
            raise MAEPError("unknown memory_id")
        return copy.deepcopy(self._records[memory_id])

    def working(self, task_id):
        return copy.deepcopy(self._working.get(task_id, []))

    def active(self, *, layer=None, kind=None, subject=None):
        return [copy.deepcopy(r) for r in self._records.values() if r["status"] == "ACTIVE"
                and (layer is None or r["layer"] == layer) and (kind is None or r["kind"] == kind)
                and (subject is None or r["subject"] == subject)]

    def all_records(self):
        """Every record in any status, in ledger order."""
        return [copy.deepcopy(r) for r in self._records.values()]

    def history(self, subject):
        return sorted((copy.deepcopy(r) for r in self._records.values() if r["subject"] == subject),
                      key=lambda r: (r["version"], r["created_at"]))

    def search(self, query, *, layers=None, kinds=None, include_inactive=False, limit=8):
        allowed = {mid for mid, r in self._records.items()
                   if (include_inactive or r["status"] == "ACTIVE")
                   and (layers is None or r["layer"] in layers) and (kinds is None or r["kind"] in kinds)}
        return [dict(copy.deepcopy(self._records[mid]), score=round(score, 4))
                for mid, score in self._index.search(query, limit=limit, allowed=allowed)]

    def conflicts(self):
        """Subjects with more than one differing ACTIVE FACT/DECISION (should only follow tampering)."""
        by_subject = {}
        for r in self._records.values():
            if r["status"] == "ACTIVE" and r["layer"] in CONFLICT_LAYERS and r["kind"] in CONFLICT_KINDS:
                by_subject.setdefault(r["subject"], []).append(r)
        return [{"subject": s, "memory_ids": sorted(x["memory_id"] for x in rs)}
                for s, rs in sorted(by_subject.items()) if len({_norm(x) for x in rs}) > 1]

    def stats(self):
        counts = {}
        for r in self._records.values():
            key = f"{r['layer']}/{r['status']}"
            counts[key] = counts.get(key, 0) + 1
        return {"records": len(self._records), "by_layer_status": counts, "conflicts": len(self.conflicts())}

    # ---------- task outcomes ----------

    def record_task_outcome(self, snapshot):
        task = snapshot["task"]
        result = snapshot.get("result") or {}
        evidence = sorted(snapshot.get("evidence", {}))
        return self.remember(
            layer="EPISODIC", kind="EVENT", subject=f"task:{task['task_id']}",
            content=f"Task {task['task_id']} ended {task['state']}: {task['objective']}"
                    + (f" (candidate {result.get('candidate_ref')})" if result.get("candidate_ref") else ""),
            value={"state": task["state"], "candidate_ref": result.get("candidate_ref")},
            source="SYSTEM", source_ref=f"tasks.jsonl:{task['task_id']}@{snapshot['version']}",
            evidence_refs=evidence, task_id=task["task_id"])

    # ---------- internals ----------

    def _validate(self, r):
        if r["layer"] not in LAYERS or r["kind"] not in KINDS or r["source"] not in SOURCES:
            raise MAEPError("unknown memory layer, kind or source")
        for field in ("subject", "content", "source_ref"):
            if not _nonempty_string(r[field]):
                raise MAEPError(f"memory {field} must be a non-empty string")
        if not all(_nonempty_string(x) for x in r["evidence_refs"]) or not all(isinstance(x, str) for x in r["limitations"]):
            raise MAEPError("evidence_refs and limitations must be lists of strings")
        if r["kind"] in CLAIM_KINDS:
            validate_claim({"claim_id": r["memory_id"], "claim_type": r["kind"], "statement": r["content"],
                            "evidence_refs": r["evidence_refs"], "limitations": r["limitations"]})
        if r["kind"] == "EVENT" and r["layer"] != "EPISODIC":
            raise MAEPError("EVENT records belong to EPISODIC memory")
        if r["kind"] == "NOTE" and (r["source"] != "USER" or r["layer"] not in {"SEMANTIC", "PROJECT"}):
            raise MAEPError("a NOTE comes from the USER and lives in SEMANTIC or PROJECT memory")

    def _active(self, memory_id):
        record = self._records.get(memory_id)
        if record is None or record["status"] != "ACTIVE":
            raise MAEPError("memory record is unknown or not active")
        return record

    def _check_supersession_and_conflict(self, record):
        previous = None
        if record["supersedes"] is not None:
            previous = self._active(record["supersedes"])
            if previous["subject"] != record["subject"]:
                raise MAEPError("a record can only supersede one about the same subject")
        if record["layer"] in CONFLICT_LAYERS and record["kind"] in CONFLICT_KINDS:
            rivals = [r for r in self._records.values()
                      if r["status"] == "ACTIVE" and r["subject"] == record["subject"]
                      and r["layer"] in CONFLICT_LAYERS and r["kind"] in CONFLICT_KINDS
                      and r["memory_id"] != record["supersedes"] and _norm(r) != _norm(record)]
            if rivals:
                raise MemoryConflict(record["subject"], [r["memory_id"] for r in rivals])
        return previous

    def _apply_write(self, record):
        if record["supersedes"] is not None and record["supersedes"] in self._records:
            self._records[record["supersedes"]]["status"] = "SUPERSEDED"
        self._records[record["memory_id"]] = copy.deepcopy(record)
        self._index.add(record["memory_id"], f"{record['subject']} {record['content']}")

    def _apply_status(self, payload):
        self._records[payload["memory_id"]]["status"] = payload["status"]

    def _replay(self, event):
        payload = event["payload"]
        if event["kind"] == "MEMORY_WRITE":
            self._validate(payload["record"])
            self._apply_write(payload["record"])
        elif event["kind"] == "MEMORY_STATUS":
            if payload.get("memory_id") not in self._records:
                raise MAEPError("memory ledger references an unknown record")
            self._apply_status(payload)
