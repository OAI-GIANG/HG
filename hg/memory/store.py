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
import hashlib
import json
import os
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone

from maep.core import MAEPError, TERMINAL_STATES, _nonempty_string, validate_claim
from hg.memory.index import Index
from hg.memory.locking import outcome_file_lock as _outcome_file_lock
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


class MemoryWriteNotCommitted(MAEPError):
    """Append failed and a fresh durable read proved the record is absent."""


class MemoryWriteOutcomeUnknown(MAEPError):
    """The ledger could not be safely re-read after an ambiguous append failure."""



def _norm(record):
    if record.get("value") is not None:
        return ("value", repr(record["value"]))
    return ("content", " ".join(record["content"].lower().split()))


class MemoryStore:
    def __init__(self, path, *, clock=None, writer_session=None, read_only=False):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._read_only = bool(read_only)
        self._writer_session = None
        if self._read_only:
            self._log = EventLog(path, clock=self._clock, read_only=True)
        else:
            # Establish the sidecar lock before loading the ledger; this also serializes
            # first creation of an absent ledger across independent MemoryStore objects.
            with _outcome_file_lock(path):
                self._log = EventLog(path, clock=self._clock, writer_session=writer_session)
                self._writer_session = self._log._writer_session
        self._write_poisoned = False
        self._records = {}
        self._working = {}
        self._index = Index()
        self.restore_conflicts = []
        for event in self._log.events():
            self._replay(event)
        self.restore_conflicts = self._compute_conflicts()

    def _refresh_from_events(self, events):
        """Rebuild the durable projection from a consistent event snapshot."""
        self._records = {}
        self._index = Index()
        for event in events:
            self._replay(event)
        self.restore_conflicts = self._compute_conflicts()

    def _refresh(self):
        """Refresh all persisted views; transient WORKING rows remain process-local."""
        with self._lock:
            with _outcome_file_lock(self._log.path):
                events = self._log.events()
            self._refresh_from_events(events)

    # ---------- write ----------

    def remember(self, *, layer, kind, subject, content, source, source_ref, evidence_refs=(), limitations=(),
                 value=None, task_id=None, supersedes=None, content_origin=None, authorized_by=None,
                 owner_confirmed=None, authorized_principal_id=None, ask_receipt_id=None,
                 valid_from=None, valid_to=None, expires_at=None,
                 model_output_sha256=None, model_output_start=None, model_output_end=None,
                 save_confirmation_sha256=None):
        if self._read_only:
            raise MAEPError("read-only memory view refuses writes")
        with self._lock:
            if layer == "WORKING":
                return self._remember_unlocked(
                    layer=layer, kind=kind, subject=subject, content=content, source=source, source_ref=source_ref,
                    evidence_refs=evidence_refs, limitations=limitations, value=value, task_id=task_id,
                    supersedes=supersedes, content_origin=content_origin, authorized_by=authorized_by,
                    owner_confirmed=owner_confirmed, authorized_principal_id=authorized_principal_id,
                    ask_receipt_id=ask_receipt_id, valid_from=valid_from, valid_to=valid_to,
                    expires_at=expires_at, model_output_sha256=model_output_sha256,
                    model_output_start=model_output_start, model_output_end=model_output_end,
                    save_confirmation_sha256=save_confirmation_sha256)
            with _outcome_file_lock(self._log.path):
                self._reload_before_write()
                return self._remember_unlocked(
                    layer=layer, kind=kind, subject=subject, content=content, source=source, source_ref=source_ref,
                    evidence_refs=evidence_refs, limitations=limitations, value=value, task_id=task_id,
                    supersedes=supersedes, content_origin=content_origin, authorized_by=authorized_by,
                    owner_confirmed=owner_confirmed, authorized_principal_id=authorized_principal_id,
                    ask_receipt_id=ask_receipt_id, valid_from=valid_from, valid_to=valid_to,
                    expires_at=expires_at, model_output_sha256=model_output_sha256,
                    model_output_start=model_output_start, model_output_end=model_output_end,
                    save_confirmation_sha256=save_confirmation_sha256)

    def _remember_unlocked(self, *, layer, kind, subject, content, source, source_ref, evidence_refs=(),
                           limitations=(), value=None, task_id=None, supersedes=None, content_origin=None,
                           authorized_by=None, owner_confirmed=None, authorized_principal_id=None,
                           ask_receipt_id=None, valid_from=None, valid_to=None, expires_at=None,
                           model_output_sha256=None, model_output_start=None, model_output_end=None,
                           save_confirmation_sha256=None):
        """Build the payload under EventLog's ledger lock; caller holds the file lock for durable writes."""
        if self._write_poisoned:
            raise MemoryWriteOutcomeUnknown("memory ledger remains unsafe after an ambiguous prior write")
        if layer == "WORKING":
            record = {
                "memory_id": f"M-{self._log.next_seq():06d}-{uuid.uuid4().hex[:6]}",
                "layer": layer, "kind": kind, "subject": subject, "content": content,
                "value": copy.deepcopy(value), "source": source, "source_ref": source_ref,
                "evidence_refs": list(evidence_refs), "limitations": list(limitations),
                "task_id": task_id, "supersedes": supersedes, "status": "ACTIVE", "version": 1,
                "created_at": self._log.now().isoformat(),
            }
            optional = {
                "content_origin": content_origin, "authorized_by": authorized_by,
                "owner_confirmed": owner_confirmed, "authorized_principal_id": authorized_principal_id,
                "ask_receipt_id": ask_receipt_id, "valid_from": valid_from, "valid_to": valid_to,
                "expires_at": expires_at, "model_output_sha256": model_output_sha256,
                "model_output_start": model_output_start, "model_output_end": model_output_end,
                "save_confirmation_sha256": save_confirmation_sha256,
            }
            record.update({key: item for key, item in optional.items() if item is not None})
            self._validate(record)
            if not _nonempty_string(task_id):
                raise MAEPError("WORKING memory needs a task_id")
            self._working.setdefault(task_id, []).append(record)
            return copy.deepcopy(record)

        created = {}
        rejected = []

        def build(current):
            self._refresh_from_events(current)
            record = {
                "memory_id": f"M-{len(current) + 1:06d}-{uuid.uuid4().hex[:6]}",
                "layer": layer, "kind": kind, "subject": subject, "content": content,
                "value": copy.deepcopy(value), "source": source, "source_ref": source_ref,
                "evidence_refs": list(evidence_refs), "limitations": list(limitations),
                "task_id": task_id, "supersedes": supersedes, "status": "ACTIVE", "version": 1,
                "created_at": self._log.now().isoformat(),
            }
            optional = {
                "content_origin": content_origin, "authorized_by": authorized_by,
                "owner_confirmed": owner_confirmed, "authorized_principal_id": authorized_principal_id,
                "ask_receipt_id": ask_receipt_id, "valid_from": valid_from, "valid_to": valid_to,
                "expires_at": expires_at, "model_output_sha256": model_output_sha256,
                "model_output_start": model_output_start, "model_output_end": model_output_end,
                "save_confirmation_sha256": save_confirmation_sha256,
            }
            record.update({key: item for key, item in optional.items() if item is not None})
            try:
                self._validate(record)
                previous = self._check_supersession_and_conflict(record)
            except MAEPError as policy_error:
                # Payload-factory policy errors happen before any bytes are appended;
                # preserve the original refusal instead of misclassifying it as I/O.
                rejected.append(policy_error)
                raise
            if previous is not None:
                record["version"] = previous["version"] + 1
            created["record"] = record
            return {"record": record}

        try:
            self._log.append("MEMORY_WRITE", task_id, payload_factory=build)
        except Exception as append_error:
            if rejected:
                raise rejected[0]
            self._reload_after_ambiguous_write("memory write")
            record = created.get("record")
            committed = self._records.get(record["memory_id"]) if record else None
            if record is not None and committed == record:
                return copy.deepcopy(committed)
            raise MemoryWriteNotCommitted(
                "append failed and durable reload confirms record was not committed") from append_error
        record = created["record"]
        self._apply_write(record)
        return copy.deepcopy(record)

    def _reload_before_write(self):
        if self._write_poisoned:
            raise MemoryWriteOutcomeUnknown("memory ledger remains unsafe after an ambiguous prior write")
        try:
            self._reload_from_disk()
        except Exception as exc:
            self._write_poisoned = True
            raise MemoryWriteOutcomeUnknown("cannot establish durable memory ledger state before write") from exc

    def _reload_after_ambiguous_write(self, operation):
        try:
            self._reload_from_disk()
        except Exception as reload_error:
            self._write_poisoned = True
            raise MemoryWriteOutcomeUnknown(
                f"{operation} outcome is unknown; durable ledger could not be reloaded") from reload_error

    def promote(self, memory_id, *, evidence_refs, source_ref):
        """HYPOTHESIS/INFERENCE -> FACT under the same ledger-wide write transaction."""
        if self._read_only:
            raise MAEPError("read-only memory view refuses writes")
        with self._lock:
            with _outcome_file_lock(self._log.path):
                self._reload_before_write()
                old = self._active(memory_id)
                if old["kind"] not in {"HYPOTHESIS", "INFERENCE"}:
                    raise MAEPError("only a HYPOTHESIS or INFERENCE can be promoted")
                if not evidence_refs:
                    raise MAEPError("promotion to FACT requires evidence_refs")
                return self._remember_unlocked(
                    layer=old["layer"], kind="FACT", subject=old["subject"], content=old["content"],
                    value=old["value"], source="EVIDENCE", source_ref=source_ref,
                    evidence_refs=evidence_refs, task_id=old["task_id"], supersedes=memory_id)

    def retract(self, memory_id, *, reason):
        """Append status change under the same ledger-wide lock as every other writer."""
        if self._read_only:
            raise MAEPError("read-only memory view refuses writes")
        with self._lock:
            with _outcome_file_lock(self._log.path):
                self._reload_before_write()
                record = self._active(memory_id)
                if not _nonempty_string(reason):
                    raise MAEPError("retraction needs a reason")
                payload = {"memory_id": memory_id, "status": "RETRACTED", "reason": reason}
                try:
                    self._log.append("MEMORY_STATUS", record["task_id"], payload)
                except Exception as append_error:
                    self._reload_after_ambiguous_write("memory retraction")
                    durable = self._records.get(memory_id)
                    if durable and durable.get("status") == "RETRACTED":
                        return None
                    if durable and durable.get("status") == "ACTIVE":
                        raise MemoryWriteNotCommitted(
                            "retraction append failed and durable reload confirms it was not committed") from append_error
                    raise MemoryWriteOutcomeUnknown("retraction outcome cannot be established") from append_error
                self._apply_status(payload)
                return None

    def clear_working(self, task_id):
        if self._read_only:
            raise MAEPError("read-only memory view refuses writes")
        self._working.pop(task_id, None)

    # ---------- read ----------

    def get(self, memory_id):
        self._refresh()
        if memory_id not in self._records:
            raise MAEPError("unknown memory_id")
        return copy.deepcopy(self._records[memory_id])

    def working(self, task_id):
        return copy.deepcopy(self._working.get(task_id, []))

    def active(self, *, layer=None, kind=None, subject=None):
        self._refresh()
        return [copy.deepcopy(r) for r in self._records.values() if r["status"] == "ACTIVE"
                and (layer is None or r["layer"] == layer) and (kind is None or r["kind"] == kind)
                and (subject is None or r["subject"] == subject)]

    def all_records(self):
        self._refresh()
        """Every record in any status, in ledger order."""
        return [copy.deepcopy(r) for r in self._records.values()]

    def history(self, subject):
        self._refresh()
        return sorted((copy.deepcopy(r) for r in self._records.values() if r["subject"] == subject),
                      key=lambda r: (r["version"], r["created_at"]))

    def search(self, query, *, layers=None, kinds=None, include_inactive=False, limit=8):
        self._refresh()
        allowed = {mid for mid, r in self._records.items()
                   if (include_inactive or r["status"] == "ACTIVE")
                   and (layers is None or r["layer"] in layers) and (kinds is None or r["kind"] in kinds)}
        return [dict(copy.deepcopy(self._records[mid]), score=round(score, 4))
                for mid, score in self._index.search(query, limit=limit, allowed=allowed)]

    def _compute_conflicts(self):
        """Return conflicting active FACT/DECISION subjects from the current projection."""
        by_subject = {}
        for record in self._records.values():
            if (record["status"] == "ACTIVE" and record["layer"] in CONFLICT_LAYERS
                    and record["kind"] in CONFLICT_KINDS):
                by_subject.setdefault(record["subject"], []).append(record)
        return [{"subject": subject, "memory_ids": sorted(item["memory_id"] for item in records)}
                for subject, records in sorted(by_subject.items())
                if len({_norm(item) for item in records}) > 1]

    def conflicts(self):
        """Subjects with more than one differing ACTIVE FACT/DECISION (should only follow tampering)."""
        self._refresh()
        return self._compute_conflicts()

    def stats(self):
        self._refresh()
        counts = {}
        for r in self._records.values():
            key = f"{r['layer']}/{r['status']}"
            counts[key] = counts.get(key, 0) + 1
        return {"records": len(self._records), "by_layer_status": counts, "conflicts": len(self.conflicts())}

    # ---------- task outcomes ----------

    def _reload_from_disk(self):
        """Reload durable state without discarding process-local WORKING records."""
        refreshed = EventLog(
            self._log.path, clock=self._clock,
            writer_session=None if self._read_only else self._writer_session,
            read_only=self._read_only)
        self._log = refreshed
        self._refresh_from_events(refreshed.events())

    @staticmethod
    def _task_outcome_expected(snapshot):
        task = snapshot["task"]
        result = snapshot.get("result") or {}
        evidence = sorted(snapshot.get("evidence", {}))
        source_ref = f"tasks.jsonl:{task['task_id']}@{snapshot['version']}"
        value = {"state": task["state"], "candidate_ref": result.get("candidate_ref")}
        content = (f"Task {task['task_id']} ended {task['state']}: {task['objective']}"
                   + (f" (candidate {result.get('candidate_ref')})" if result.get('candidate_ref') else ""))
        return task, evidence, source_ref, value, content

    def _matching_task_outcome(self, source_ref, *, subject, value, content, evidence):
        matches = [r for r in self._records.values()
                   if r["layer"] == "EPISODIC" and r["kind"] == "EVENT" and r["source_ref"] == source_ref]
        if not matches:
            return None
        if len(matches) != 1:
            raise MAEPError("task outcome source_ref is not unique in memory")
        record = matches[0]
        if (record["subject"] != subject or record["value"] != value or record["content"] != content
                or record["evidence_refs"] != evidence):
            raise MAEPError("task outcome source_ref was reused for a different snapshot")
        return copy.deepcopy(record)

    def record_task_outcome(self, snapshot):
        """Write one terminal-task episode under thread + process locks.

        Refresh first from disk. If append reports an error, rebuild the projection before
        deciding whether the append committed; never reuse a stale sequence cursor.
        """
        if self._read_only:
            raise MAEPError("read-only memory view refuses writes")
        task, evidence, source_ref, expected_value, expected_content = self._task_outcome_expected(snapshot)
        if task["state"] not in TERMINAL_STATES:
            raise MAEPError(f"task outcome requires a terminal state; task is {task['state']}")
        subject = f"task:{task['task_id']}"
        with self._lock:
            if self._write_poisoned:
                raise MemoryWriteOutcomeUnknown("memory ledger remains unsafe after an ambiguous prior write")
            with _outcome_file_lock(self._log.path):
                try:
                    self._reload_from_disk()
                except Exception as exc:
                    self._write_poisoned = True
                    raise MemoryWriteOutcomeUnknown("cannot establish durable memory ledger state") from exc
                existing = self._matching_task_outcome(source_ref, subject=subject, value=expected_value,
                                                        content=expected_content, evidence=evidence)
                if existing is not None:
                    return existing
                try:
                    return self._remember_unlocked(
                        layer="EPISODIC", kind="EVENT", subject=subject, content=expected_content,
                        value=expected_value, source="SYSTEM", source_ref=source_ref,
                        evidence_refs=evidence, task_id=task['task_id'])
                except Exception as append_error:
                    try:
                        self._reload_from_disk()
                    except Exception as reload_error:
                        self._write_poisoned = True
                        raise MemoryWriteOutcomeUnknown(
                            "append outcome is unknown; durable ledger could not be reloaded") from reload_error
                    committed = self._matching_task_outcome(source_ref, subject=subject, value=expected_value,
                                                              content=expected_content, evidence=evidence)
                    if committed is not None:
                        return committed
                    raise MemoryWriteNotCommitted(
                        "append failed and durable reload confirms no episode was committed") from append_error

    # ---------- internals ----------

    def _validate(self, r, *, allow_legacy_model_derived=False):
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
        if r.get("content_origin") is not None:
            if r["content_origin"] not in {"OWNER_AUTHORED", "MODEL_DERIVED"}:
                raise MAEPError("unknown content_origin")
            if r["content_origin"] == "MODEL_DERIVED":
                if not (r.get("authorized_by") == "OWNER" and r.get("owner_confirmed") is True
                        and _nonempty_string(r.get("ask_receipt_id"))):
                    raise MAEPError("MODEL_DERIVED note requires owner confirmation and ASK receipt provenance")
                principal_id = r.get("authorized_principal_id")
                if not allow_legacy_model_derived and not _nonempty_string(principal_id):
                    raise MAEPError("new MODEL_DERIVED writes require an authenticated owner principal")
                if principal_id is not None and (
                        not isinstance(principal_id, str) or len(principal_id) > 160
                        or not re.fullmatch(r"owner:[a-z0-9][a-z0-9:._-]{0,150}", principal_id)):
                    raise MAEPError("MODEL_DERIVED authorized principal id is invalid")
                proof_fields = ("model_output_sha256", "model_output_start", "model_output_end",
                                "save_confirmation_sha256")
                if not all(field in r for field in proof_fields):
                    if not allow_legacy_model_derived:
                        raise MAEPError("new MODEL_DERIVED writes require verifiable model-output span provenance")
                else:
                    self._verify_model_derived_provenance(r)
        for field in ("valid_from", "valid_to", "expires_at"):
            if field in r and not _nonempty_string(r[field]):
                raise MAEPError(f"{field} must be non-empty ISO-8601 text when supplied")

    def _verify_model_derived_provenance(self, record):
        """Verify an immutable excerpt of the exact ANSWERED ASK receipt before a new write."""
        receipt_id = record.get("ask_receipt_id")
        answer_digest = record.get("model_output_sha256")
        start, end = record.get("model_output_start"), record.get("model_output_end")
        content_digest = hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
        principal_id = record.get("authorized_principal_id")
        v2_pattern = re.compile(r"^ask:([0-9a-f]{32}):v2:([0-9a-f]{64})$")
        v2_match = v2_pattern.fullmatch(record["source_ref"])
        if principal_id is not None:
            if not v2_match:
                raise MAEPError("MODEL_DERIVED source_ref is missing its v2 principal-bound identity")
            ref_id, ref_confirmation = v2_match.groups()
            if receipt_id != ref_id:
                raise MAEPError("MODEL_DERIVED receipt id does not match source_ref")
            material = {
                "operation": "MODEL_DERIVED_SAVE_FROM_ASK", "receipt_event_id": receipt_id,
                "subject": record["subject"], "content": record["content"],
                "content_origin": "MODEL_DERIVED", "authorized_by": "OWNER", "owner_confirmed": True,
                "authorized_principal_id": principal_id,
                "answer_sha256": answer_digest, "model_output_start": start, "model_output_end": end,
                "content_sha256": content_digest,
            }
            canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected_confirmation = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if (record.get("save_confirmation_sha256") != ref_confirmation
                    or expected_confirmation != ref_confirmation):
                raise MAEPError("MODEL_DERIVED owner-principal confirmation digest does not match save identity")
        else:
            # Read-only compatibility for pre-R3.1 entries already present in a ledger.
            # New writes cannot take this branch because _validate() requires a principal.
            source_pattern = re.compile(
                r"^ask:([0-9a-f]{32}):a:([0-9a-f]{64}):s:(\d+):(\d+):"
                r"c:([0-9a-f]{64}):o:([0-9a-f]{64})$"
            )
            match = source_pattern.fullmatch(record["source_ref"])
            if not match:
                raise MAEPError("legacy MODEL_DERIVED source_ref is malformed")
            ref_id, ref_answer, ref_start, ref_end, ref_content, ref_confirmation = match.groups()
            if (receipt_id != ref_id or answer_digest != ref_answer or start != int(ref_start)
                    or end != int(ref_end) or content_digest != ref_content
                    or record.get("save_confirmation_sha256") != ref_confirmation):
                raise MAEPError("legacy MODEL_DERIVED provenance fields do not match source_ref")
            material = {
                "operation": "MODEL_DERIVED_SAVE_FROM_ASK", "receipt_event_id": receipt_id,
                "subject": record["subject"], "content": record["content"],
                "content_origin": "MODEL_DERIVED", "authorized_by": "OWNER", "owner_confirmed": True,
                "answer_sha256": answer_digest, "model_output_start": start, "model_output_end": end,
                "content_sha256": content_digest,
            }
            canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected_confirmation = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if expected_confirmation != ref_confirmation:
                raise MAEPError("legacy MODEL_DERIVED confirmation digest does not match save identity")

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
            self._validate(payload["record"], allow_legacy_model_derived=True)
            self._apply_write(payload["record"])
        elif event["kind"] == "MEMORY_STATUS":
            if payload.get("memory_id") not in self._records:
                raise MAEPError("memory ledger references an unknown record")
            self._apply_status(payload)
