"""Explicit, digest-bound save of MODEL_DERIVED content linked to an ASK receipt.

The owner may save model-originated content, including verbatim content, only through
an explicit preview and digest confirmation. Provenance remains MODEL_DERIVED; owner
confirmation records authorization, not independent verification or authorship.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from maep.core import MAEPError
from hg.assistant.home import ensure_home, locked
from hg.assistant.notes import Notebook, NoteError, clean_text, normalize_subject
from hg.verification.evidence import EventLog


_RECEIPT_ID = re.compile(r"^[0-9a-f]{32}$")


class AskArchiveError(ValueError):
    """The referenced receipt or confirmation is invalid."""


def _normalise_principal_id(principal_id: str | None) -> str:
    """Return an authenticated owner principal; never accept a client-supplied identity."""
    if principal_id is None:
        principal_id = f"owner:termux-uid:{os.getuid()}"
    if (not isinstance(principal_id, str) or len(principal_id) > 160
            or not re.fullmatch(r"owner:[a-z0-9][a-z0-9:._-]{0,150}", principal_id)):
        raise AskArchiveError("authenticated owner principal id is invalid")
    return principal_id


def _load_receipt(home, receipt_id: str) -> dict:
    if not isinstance(receipt_id, str) or not _RECEIPT_ID.fullmatch(receipt_id):
        raise AskArchiveError("receipt_id must be a 32-character ASK event id")
    home = ensure_home(home, create=False)
    found = []
    with locked(home, exclusive=False):
        for path in sorted(home.glob("asks-????-??.jsonl")):
            try:
                events = EventLog(path).events("ASK")
            except (OSError, MAEPError) as exc:
                raise AskArchiveError(f"cannot safely read ASK ledger {path.name}") from exc
            found.extend(e for e in events if e.get("event_id") == receipt_id)
    if len(found) != 1:
        raise AskArchiveError("ASK receipt not found or event id is ambiguous")
    event = found[0]
    payload = event.get("payload") or {}
    if payload.get("outcome") != "ANSWERED" or not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        raise AskArchiveError("only a completed ANSWERED receipt can authorize a model-derived save")
    return event


def preview_model_derived_save(home, receipt_id: str, *, subject: str, text: str,
                               principal_id: str | None = None) -> dict:
    """Build the exact save preview without writing any file."""
    event = _load_receipt(home, receipt_id)
    principal_id = _normalise_principal_id(principal_id)
    subject = normalize_subject(subject)
    text = clean_text(text)
    answer = event["payload"]["answer"]
    canonical_answer = unicodedata.normalize("NFC", answer)
    model_output_start = canonical_answer.find(text)
    if model_output_start < 0:
        raise AskArchiveError(
            "MODEL_DERIVED content must be an exact excerpt of this ASK model answer; "
            "owner-authored or rewritten text cannot use this endpoint")
    model_output_end = model_output_start + len(text)
    answer_digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    content_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    material = {
        "operation": "MODEL_DERIVED_SAVE_FROM_ASK",
        "receipt_event_id": receipt_id,
        "subject": subject,
        "content": text,
        "content_origin": "MODEL_DERIVED",
        "authorized_by": "OWNER",
        "owner_confirmed": True,
        "authorized_principal_id": principal_id,
        "answer_sha256": answer_digest,
        "model_output_start": model_output_start,
        "model_output_end": model_output_end,
        "content_sha256": content_digest,
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "operation": material["operation"],
        "will_write": False,
        "receipt_event_id": receipt_id,
        "receipt_seq": event.get("seq"),
        "receipt_at": event.get("at"),
        "channel": event["payload"].get("channel"),
        "provider": event["payload"].get("provider"),
        "model": event["payload"].get("model"),
        "answer_sha256": answer_digest,
        "model_output_start": model_output_start,
        "model_output_end": model_output_end,
        "content_sha256": content_digest,
        "subject": subject,
        "content": text,
        "confirmation_sha256": digest,
        "content_origin": "MODEL_DERIVED",
        "authorized_by": "OWNER",
        "owner_confirmed": True,
        "authorized_principal_id": principal_id,
        "provenance_policy": "EXACT_ASK_ANSWER_EXCERPT; MODEL_DERIVED; OWNER_AUTHORIZED; NOT_INDEPENDENTLY_VERIFIED",
    }


def save_model_derived_content(home, receipt_id: str, *, subject: str, text: str, confirm_sha256: str,
                           principal_id: str | None = None, clock=None,
                           lock_wait_s: float = 5.0) -> tuple[dict, bool]:
    """Persist only when the exact subject/content/source preview digest is confirmed."""
    preview = preview_model_derived_save(
        home, receipt_id, subject=subject, text=text, principal_id=principal_id)
    supplied = confirm_sha256.removeprefix("sha256:") if isinstance(confirm_sha256, str) else ""
    if not re.fullmatch(r"[0-9a-f]{64}", supplied) or supplied != preview["confirmation_sha256"]:
        raise AskArchiveError("confirmation digest mismatch; no memory was written")
    # Compact v2 reference binds receipt + complete canonical identity digest. The digest
    # includes the authenticated principal, avoiding the old 256-char source_ref ceiling.
    source_ref = f"ask:{receipt_id}:v2:{preview['confirmation_sha256']}"
    notebook = Notebook(home, clock=clock, lock_wait_s=lock_wait_s)
    record, created = notebook.add(
        text, subject=preview["subject"], origin="tty", source_ref=source_ref,
        content_origin="MODEL_DERIVED", authorized_by="OWNER", owner_confirmed=True,
        authorized_principal_id=preview["authorized_principal_id"],
        ask_receipt_id=receipt_id, model_output_sha256=preview["answer_sha256"],
        model_output_start=preview["model_output_start"], model_output_end=preview["model_output_end"],
        save_confirmation_sha256=preview["confirmation_sha256"])
    return record, created
