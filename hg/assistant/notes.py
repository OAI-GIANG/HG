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
from hg.memory.store import MemoryStore

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


def clean_text(text, *, limit=MAX_NOTE_CHARS):
    """NFC, no control characters except newline/tab, trimmed, bounded."""
    if not isinstance(text, str):
        raise NoteError("note text must be a string")
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in text):
        raise NoteError("note text contains control characters")
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

    def add(self, text, *, subject=None, replaces=None, origin="tty"):
        """Return (record, created). created=False when the identical note already exists."""
        if origin not in ORIGINS:
            raise NoteError("unknown note origin")
        text = clean_text(text)
        with locked(self.home, exclusive=True, wait_s=self._wait):
            store = self._store()
            active = {r["memory_id"]: r for r in store.active(kind="NOTE")}
            previous = None
            if replaces is not None:
                previous = active.get(replaces)
                if previous is None:
                    raise NoteError(f"no active note {replaces}")
            if subject is not None:
                subject = normalize_subject(subject)
                if previous is not None and previous["subject"] != subject:
                    raise NoteError("--replaces must name a note with the same subject")
                same_subject = [r for r in active.values() if r["subject"] == subject]
                for r in same_subject:
                    if _same(r["content"], text) and previous is None:
                        return r, False
                if same_subject and previous is None:
                    raise NoteConflict(subject, same_subject[0])
            elif previous is not None:
                subject = previous["subject"]
            else:
                digest = hashlib.sha256(f"{self._clock().isoformat()}|{text}".encode("utf-8")).hexdigest()[:12]
                subject = f"auto:{digest}"
            record = store.remember(layer="SEMANTIC", kind="NOTE", subject=subject, content=text,
                                    source="USER", source_ref=f"cli:{origin}",
                                    supersedes=previous["memory_id"] if previous else None)
            return record, True

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
