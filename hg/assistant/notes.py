"""F2 — the owner's notebook: `hg note add|search|list|show|forget`.

Notes are MemoryStore records of kind NOTE (layer SEMANTIC, source USER). A NOTE records
what the owner told HG. It is not a verified FACT and HG never promotes it to one.

Guarantees, each with a test:
- Nothing is overwritten. `forget` retracts (the text stays in the ledger and in `show`
  history); a replacement supersedes. This is deliberate: HG can show when and how a note
  changed. `forget` is not erasure.
- Same explicit subject, different text -> refused (NoteConflict) unless the owner names
  the note being replaced. Same text again -> the existing note is returned, not duplicated.
- Search is Vietnamese-aware (hg.assistant.textvi): function syllables ignored, adjacent
  syllables indexed as pairs, text typed without diacritics matches accented notes. A note
  is returned only if it contains at least half of the query's content words, so one shared
  common word ("lớp", "xe") is not enough; that is what lets `ask` abstain.
- Every note keeps how it arrived (`origin`: typed in a terminal, piped from another
  program, or entered in the interactive prompt) so a later reader can tell them apart.
"""
import hashlib
import re
import unicodedata
from datetime import datetime, timezone

from maep.core import MAEPError
from hg.assistant import textvi
from hg.assistant.home import ensure_home, locked, private_file
from hg.memory.index import Index
from hg.memory.store import MemoryStore, _outcome_file_lock
from hg.verification.evidence import EventLog

MAX_NOTE_CHARS = 4000
ORIGINS = {"tty", "pipe", "prompt", "test"}
_SUBJECT = re.compile(r"^[\w][\w.\-:]{0,79}$", re.UNICODE)


class NoteError(MAEPError):
    """Bad input (exit 2)."""


class NoteConflict(MAEPError):
    """An active note on the same subject says something else (exit 4)."""

    def __init__(self, subject, existing):
        self.subject, self.existing = subject, existing
        super().__init__(f"chủ đề {subject!r} đã có ghi chú khác ({existing['memory_id']}); "
                         f"dùng --replaces {existing['memory_id']} để thay thế")


class NoteInactive(MAEPError):
    """A source_ref is permanently bound to a retracted or superseded note."""

    def __init__(self, record):
        self.record = record
        super().__init__(f"source_ref belongs to inactive note {record['memory_id']} ({record['status']})")


# Bidirectional overrides/isolates reorder what the terminal shows ("Trojan Source"); refused.
BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c")
# Invisible characters with no meaning in a Vietnamese note; removed. (ZWJ/ZWNJ are kept: emoji.)
INVISIBLE = dict.fromkeys(map(ord, "\u200b\u2060\ufeff\u00ad\u180e"), None)


def clean_text(text, *, limit=MAX_NOTE_CHARS):
    """NFC, no control or bidi characters, invisible characters removed, trimmed, bounded."""
    if not isinstance(text, str):
        raise NoteError("note text must be a string")
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").translate(INVISIBLE)
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in text):
        raise NoteError("note text contains control characters")
    if any(c in BIDI_CONTROLS for c in text):
        raise NoteError("note text contains bidirectional control characters")
    text = text.strip()
    if not text:
        raise NoteError("note text is empty")
    if len(text) > limit:
        raise NoteError(f"note text is longer than {limit} characters")
    return text


def normalize_subject(subject):
    subject = unicodedata.normalize("NFC", subject).strip().lower().replace(" ", "-")
    if not _SUBJECT.match(subject) or subject.startswith("auto:"):
        raise NoteError("subject: 1-80 letters, digits, . - : (no spaces), not starting with 'auto:'")
    return subject


def _same(a, b):
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


class Notebook:
    def __init__(self, home, *, clock=None, lock_wait_s=5.0):
        self.home = ensure_home(home)
        self.path = self.home / "notes.jsonl"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._wait = lock_wait_s

    def _store(self):
        private_file(self.path)
        return MemoryStore(self.path, clock=self._clock)

    # ---------- write (LOCK_EX for the whole load-check-append) ----------

    def add(self, text, *, subject=None, replaces=None, origin="tty", source_ref=None,
            content_origin=None, authorized_by=None, owner_confirmed=None, authorized_principal_id=None,
            ask_receipt_id=None,
            model_output_sha256=None, model_output_start=None, model_output_end=None,
            save_confirmation_sha256=None):
        """Return (record, created). A supplied source_ref makes active retries idempotent.

        A source_ref bound to a RETRACTED/SUPERSEDED NOTE is permanently inactive and raises
        NoteInactive; it is never treated as a successful retry. A new ASK receipt is required.
        source_ref is intended for trusted adapters, not model text or arbitrary request input.
        """
        if origin not in ORIGINS:
            raise NoteError("unknown note origin")
        text = clean_text(text)
        if source_ref is not None and (not isinstance(source_ref, str) or not source_ref.strip()
                                       or len(source_ref) > 256):
            raise NoteError("source_ref must be 1..256 characters")
        normalized = normalize_subject(subject) if subject is not None else None
        if ask_receipt_id is not None:
            if (not isinstance(ask_receipt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", ask_receipt_id)
                    or source_ref is None or subject is None):
                raise NoteError("ASK receipt saves require a valid receipt id, explicit subject and immutable source_ref")
            if not source_ref.startswith(f"ask:{ask_receipt_id}:"):
                raise NoteError("ASK receipt id does not match the immutable source_ref")
        elif source_ref is not None and source_ref.startswith("ask:"):
            raise NoteError("ASK source_ref requires its matching ask_receipt_id")
        with locked(self.home, exclusive=True, wait_s=self._wait):
            store = self._store()
            with store._lock:
                with _outcome_file_lock(self.path):
                    store._reload_before_write()
                    all_notes = [r for r in store.all_records() if r.get("kind") == "NOTE"]
                    active = {r["memory_id"]: r for r in store.active(kind="NOTE")}
                    return self._add_locked(
                        store, text, subject=subject, normalized=normalized, replaces=replaces, origin=origin,
                        source_ref=source_ref, content_origin=content_origin, authorized_by=authorized_by,
                        owner_confirmed=owner_confirmed, authorized_principal_id=authorized_principal_id,
                        ask_receipt_id=ask_receipt_id,
                        model_output_sha256=model_output_sha256, model_output_start=model_output_start,
                        model_output_end=model_output_end, save_confirmation_sha256=save_confirmation_sha256,
                        all_notes=all_notes, active=active)

    def _add_locked(self, store, text, *, subject, normalized, replaces, origin, source_ref, content_origin,
                    authorized_by, owner_confirmed, authorized_principal_id, ask_receipt_id, model_output_sha256,
                    model_output_start, model_output_end, save_confirmation_sha256, all_notes, active):
        if ask_receipt_id is not None:
            receipt_matches = [r for r in all_notes
                               if r.get("ask_receipt_id") == ask_receipt_id
                               or r.get("source_ref", "").startswith(f"ask:{ask_receipt_id}:")]
            if receipt_matches:
                if len(receipt_matches) != 1:
                    raise NoteError("ASK receipt is already linked to multiple notes; refusing ambiguous replay")
                existing = receipt_matches[0]
                requested_identity = (
                    normalized if normalized is not None else existing["subject"], text, content_origin,
                    authorized_by, owner_confirmed, authorized_principal_id, ask_receipt_id, source_ref, model_output_sha256,
                    model_output_start, model_output_end, save_confirmation_sha256)
                existing_identity = (
                    existing["subject"], existing["content"], existing.get("content_origin"),
                    existing.get("authorized_by"), existing.get("owner_confirmed"),
                    existing.get("authorized_principal_id"), existing.get("ask_receipt_id"), existing.get("source_ref"),
                    existing.get("model_output_sha256"), existing.get("model_output_start"),
                    existing.get("model_output_end"), existing.get("save_confirmation_sha256"))
                if requested_identity != existing_identity:
                    raise NoteError("ASK receipt was already consumed by a different immutable save identity")
                if existing["status"] != "ACTIVE":
                    raise NoteInactive(existing)
                return existing, False
        if source_ref is not None:
            matches = [r for r in store.all_records() if r.get("kind") == "NOTE"
                       and r.get("source_ref") == source_ref]
            if matches:
                if len(matches) != 1 or matches[0]["subject"] != (normalized
                                                                    if normalized is not None else matches[0]["subject"]) \
                        or matches[0]["content"] != text:
                    raise NoteError("source_ref was already used for a different save operation")
                if matches[0]["status"] != "ACTIVE":
                    raise NoteInactive(matches[0])
                return matches[0], False
        previous = None
        if replaces is not None:
            previous = active.get(replaces)
            if previous is None:
                raise NoteError(f"no active note {replaces}")
        if subject is not None:
            subject = normalized
            if previous is not None and previous["subject"] != subject:
                raise NoteError("--replaces must name a note with the same subject")
            same_subject = [r for r in active.values() if r["subject"] == subject]
            for r in same_subject:
                if _same(r["content"], text) and previous is None:
                    if source_ref is not None and r.get("source_ref") != source_ref:
                        raise NoteConflict(subject, r)
                    return r, False
            if same_subject and previous is None:
                raise NoteConflict(subject, same_subject[0])
        elif previous is not None:
            subject = previous["subject"]
        else:
            digest = hashlib.sha256(f"{self._clock().isoformat()}|{text}".encode("utf-8")).hexdigest()[:12]
            subject = f"auto:{digest}"
        record = store._remember_unlocked(layer="SEMANTIC", kind="NOTE", subject=subject, content=text,
                                source="USER", source_ref=source_ref or f"cli:{origin}",
                                supersedes=previous["memory_id"] if previous else None,
                                content_origin=content_origin, authorized_by=authorized_by,
                                owner_confirmed=owner_confirmed,
                                authorized_principal_id=authorized_principal_id, ask_receipt_id=ask_receipt_id,
                                model_output_sha256=model_output_sha256,
                                model_output_start=model_output_start, model_output_end=model_output_end,
                                save_confirmation_sha256=save_confirmation_sha256)
        return record, True

    def trust(self, memory_id, *, reason="owner reviewed this note and lifted the AI-directive quarantine"):
        """Owner override for one note flagged by hg.assistant.guard; recorded, never silent."""
        with locked(self.home, exclusive=True, wait_s=self._wait):
            store = self._store()
            with store._lock:
                with _outcome_file_lock(self.path):
                    store._reload_before_write()
                    if not any(r["memory_id"] == memory_id for r in store.active(kind="NOTE")):
                        raise NoteError(f"no active note {memory_id}")
                    return store._log.append("NOTE_TRUST", None,
                                             {"memory_id": memory_id, "reason": reason})

    def trusted_ids(self):
        with locked(self.home, exclusive=False, wait_s=self._wait):
            with _outcome_file_lock(self.path):
                if not self.path.exists():
                    return set()
                return {e["payload"]["memory_id"] for e in EventLog(self.path).events("NOTE_TRUST")}

    def forget(self, memory_id, *, reason="owner asked to forget"):
        with locked(self.home, exclusive=True, wait_s=self._wait):
            store = self._store()
            record = next((r for r in store.active(kind="NOTE") if r["memory_id"] == memory_id), None)
            if record is None:
                raise NoteError(f"no active note {memory_id}")
            store.retract(memory_id, reason=reason)
            return record

    # ---------- read (LOCK_SH) ----------

    def snapshot(self):
        """Every NOTE record (all statuses), oldest first. Missing ledger -> []."""
        with locked(self.home, exclusive=False, wait_s=self._wait):
            if not self.path.exists():
                return []
            store = self._store()
            records = [r for r in store.all_records() if r["kind"] == "NOTE"]
        return records

    def active(self):
        return [r for r in self.snapshot() if r["status"] == "ACTIVE"]

    def history(self, memory_id):
        records = self.snapshot()
        by_id = {r["memory_id"]: r for r in records}
        if memory_id not in by_id:
            raise NoteError(f"no note {memory_id}")
        subject = by_id[memory_id]["subject"]
        return [r for r in records if r["subject"] == subject]

    def search(self, query, *, limit=5, records=None):
        """Active notes ranked by Vietnamese-aware BM25; only notes sharing a content word."""
        records = self.active() if records is None else records
        unigrams = set(textvi.query_keys(query))
        if not unigrams:
            return []
        index = Index(analyzer=textvi.analyze, query_analyzer=textvi.analyze_query)
        by_id = {}
        for r in records:
            index.add(r["memory_id"], f"{r['content']}")
            by_id[r["memory_id"]] = r
        hits = []
        need = max(1, -(-len(unigrams) // 2))      # at least half of the query's content words
        for mid, score in index.search(query, limit=limit * 3):
            matched = unigrams & set(textvi.document_keys(by_id[mid]["content"]))
            if len(matched) >= need:
                hits.append(dict(by_id[mid], score=round(score, 4), matched=sorted(matched)))
        if hits:
            top = hits[0]["score"]
            hits = [h for h in hits if h["score"] >= 0.25 * top]
        return hits[:limit]
