"""POST /v1/chat on hg serve: one message from the owner's web UI -> HG Brain model layer -> labelled answer.

Contract: docs/architecture/HG_SERVICE_V1.md §5 (revision 2026-10-29, requested by the owner so the
Chat screen of the web UI works end to end on the phone).

Path of one message (no step is skipped, none is simulated):
  1. hg.http_api checks Host, loopback client, bearer token, body {"message": str, "general": bool}
     and that the running release is VERIFIED, then calls ChatService.
  2. ChatService checks the assistant home (private 0700, owned, not shared storage; never created
     here), loads its settings, attests the supervised local model process and the pinned model
     digest exactly as `hg ask` does.
  3. hg.assistant.ask.ask(): Vietnamese-aware note search, AI-directive quarantine, then
     hg.brain.providers.ModelRouter with exactly ONE provider: the local Ollama model (owner
     decision Q5 - no paid provider is reachable from this route, there is no parameter for one).
     Every sentence of the answer is labelled by HG (NOTE / MODEL / CONFLICT / BADCITE / ABSTAIN).
  4. Evidence in the owner's ledger $HG_HOME/asks-YYYY-MM.jsonl: one MODEL_CALL event per model
     attempt (provider, model, status, duration, request hash - never the prompt) and one ASK
     receipt with channel "http:/v1/chat". The response names both event ids.

What this route is not: it does not run through BrainOrchestrator, TaskStore or ActionGateway and
is NOT ENFORCED by the HG runtime path. It has no effect outside HG_HOME and model output never
triggers an action. A chat answer is not a MAEP task; the MAEP path would need an owner grant for a
model resource that maep/authority/owner-grants.json does not contain (owner-only change, Q4).
Same-UID attackers are out of scope (Q3), as for the CLI.

Only one chat is answered at a time (the phone runs one model, OLLAMA_NUM_PARALLEL=1); a second
request while one is running gets 503 chat_busy instead of queueing behind a long model call.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

from maep.core import MAEPError
from hg.assistant import config as cfg
from hg.assistant.ask import append_receipt, ask, safe
from hg.assistant.home import Busy, HomeError, ensure_home
from hg.assistant.notes import Notebook
from hg.http_api import HTTPBoundaryError

CHANNEL = "http:/v1/chat"
MAX_MESSAGE_CHARS = 2000
ROUTER = "hg.brain.providers.ModelRouter"
PROVIDER_POLICY = "local model only (owner decision Q5); no paid provider on this route"


class _ModelCallLog:
    """EventLog stand-in for ModelRouter: each MODEL_CALL goes to the owner's ledger under LOCK_EX."""

    def __init__(self, home, *, clock, lock_wait_s):
        self._home, self._clock, self._wait = home, clock, lock_wait_s
        self.events, self.errors = [], []

    def append(self, kind, task_id, payload):
        try:
            event = append_receipt(self._home, kind, dict(payload, channel=CHANNEL), clock=self._clock,
                                   lock_wait_s=self._wait)
        except Exception as exc:          # the router keeps the answer; the response reports the gap
            self.errors.append(type(exc).__name__)
            raise
        self.events.append(event)
        return event


class ChatService:
    """Callable used by HGHTTPServer(chat=...): service(message, general=bool) -> response dict."""

    def __init__(self, home, *, release_id="dev", clock=None, lock_wait_s=5.0):
        self.home = Path(home)
        self.release_id = release_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._wait = lock_wait_s
        self._busy = threading.Lock()

    def __call__(self, message, *, general):
        if not isinstance(message, str) or not isinstance(general, bool):
            raise HTTPBoundaryError(400, "invalid_request", "message must be text and general a boolean")
        if not self._busy.acquire(blocking=False):
            raise HTTPBoundaryError(503, "chat_busy", "HG is answering another message; send again when it finishes")
        try:
            return self._answer(message, general)
        finally:
            self._busy.release()

    # ---------- steps ----------

    def _model_parts(self):
        try:
            home = ensure_home(self.home, create=False)
            conf = cfg.load(home)
        except (HomeError, cfg.ConfigError, OSError) as exc:
            raise HTTPBoundaryError(503, "assistant_unavailable", f"assistant home is not usable: {exc}") from exc
        try:
            listener = cfg.attest_listener(conf)
            check = cfg.check_model(conf, cfg.ollama(conf))
        except cfg.ConfigError as exc:
            raise HTTPBoundaryError(503, "model_untrusted", f"local model refused: {exc}") from exc
        return home, conf, listener, check

    def _answer(self, message, general):
        home, conf, listener, check = self._model_parts()
        notes_only = check.get("status") != "READY"
        reason = (f"model {check.get('status')}: {check.get('reason', '')} (xem: hg model status)"
                  if notes_only else None)
        calls = _ModelCallLog(home, clock=self._clock, lock_wait_s=self._wait)
        receipts, display = [], []
        try:
            notebook = Notebook(home, clock=self._clock, lock_wait_s=self._wait)
            _code, receipt = ask(
                message, notebook=notebook,
                router_factory=lambda: cfg.router(conf, provider_choice="local", event_log=calls),
                listener=listener, model_check=check, out=display.append, color=False,
                notes_only=notes_only, unavailable_reason=reason, max_tokens=conf["max_tokens"],
                clock=self._clock, release=self.release_id, general=general, channel=CHANNEL,
                on_receipt=receipts.append)
            notes = self._notes(notebook, receipt)
        except Busy as exc:
            raise HTTPBoundaryError(503, "assistant_busy", "another HG command is using the notes; try again") from exc
        except HomeError as exc:
            raise HTTPBoundaryError(503, "assistant_unavailable", f"assistant home is not usable: {exc}") from exc
        except MAEPError as exc:
            raise HTTPBoundaryError(503, "notes_ledger_damaged",
                                    "a notes or receipts ledger cannot be read; run in Termux: hg repair") from exc
        except ValueError as exc:
            raise HTTPBoundaryError(400, "invalid_message", "message is empty") from exc
        return self._response(receipt, notes, display, calls, receipts, check, listener)

    @staticmethod
    def _notes(notebook, receipt):
        """The notes the answer used, re-read and matched to the receipt's hashes (None if changed since)."""
        if not receipt.get("notes"):
            return []
        records = {r["memory_id"]: r for r in notebook.active()}
        out = []
        for note in receipt["notes"]:
            record = records.get(note["memory_id"])
            same = record is not None and hashlib.sha256(record["content"].encode("utf-8")).hexdigest() == note["sha256"]
            out.append({"ref": note["ref"], "memory_id": note["memory_id"],
                        "created_at": record["created_at"] if same else None,
                        "content": safe(record["content"]) if same else None})
        return out

    def _response(self, receipt, notes, display, calls, receipts, check, listener):
        outcome = receipt["outcome"]
        answer = receipt.get("answer")
        sentences = [{"sentence": safe(s.get("sentence")), "label": s.get("label"), "note": s.get("note"),
                      "reasons": [safe(r) for r in s.get("reasons") or []]}
                     for s in receipt.get("sentences") or []]
        brain = {
            "router": ROUTER, "provider_policy": PROVIDER_POLICY,
            "ledger": f"asks-{self._clock():%Y-%m}.jsonl",
            "model_calls": [{"event_id": e["event_id"], "seq": e["seq"], "status": e["payload"].get("status"),
                             "provider": e["payload"].get("provider"), "model": e["payload"].get("model"),
                             "duration_ms": e["payload"].get("duration_ms"), "error": e["payload"].get("error"),
                             "usage": e["payload"].get("usage"),
                             "request_digest": e["payload"].get("request_digest")} for e in calls.events],
            "receipt_event_id": receipts[0]["event_id"] if receipts else None,
        }
        if calls.errors:
            brain["model_call_log_errors"] = calls.errors
        return {
            "outcome": outcome,
            "answer": safe(answer) if answer and outcome in ("ANSWERED", "NO_DATA") else None,
            "sentences": sentences,
            "counts": receipt.get("counts"),
            "grounded_ratio": receipt.get("grounded_ratio"),
            "abstained": bool(receipt.get("abstained")),
            "gate": receipt.get("gate"),
            "notes": notes,
            "quarantined": receipt.get("quarantined", []),
            "note_conflicts": receipt.get("note_conflicts", []),
            "error": safe(receipt["error"])[:400] if receipt.get("error") else None,
            "provider": receipt.get("provider"),
            "model": receipt.get("model"),
            "usage": receipt.get("usage"),
            "request_digest": receipt.get("request_digest"),
            "model_check": check,
            "listener": listener,
            "seconds": receipt.get("seconds"),
            "timings": receipt.get("timings"),
            "release": self.release_id,
            "channel": CHANNEL,
            "display": [safe(line) for line in display],
            "brain": brain,
        }
