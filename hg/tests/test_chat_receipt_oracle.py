"""False-accept oracle for chat receipts (WS-04): POST /v1/chat answers only when its evidence is real.

A chat response claims evidence: brain.ledger names the receipts ledger, brain.receipt_event_id and
brain.model_calls[].event_id name events in it. This oracle drives the real ChatService (real
OllamaProvider, ModelRouter, grounding, receipt code) against a fake loopback model and asserts:

  * an unsafe receipts ledger (symlink, FIFO, hard link, group/world-writable, torn tail, duplicate
    JSON key, non-UTF-8) yields a refusal (HTTPBoundaryError 503), returns within 5 s and writes
    nothing outside HG_HOME; it never yields an answer whose receipt is missing or elsewhere;
  * every event id the response names is in the ledger file the response names, exactly once;
  * the ledger the response names is the file the receipt was written to, even when the month
    changes during the call.
"""
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from hg.http_api import HTTPBoundaryError
from hg.tests.test_chat_service import ChatServiceBase, NOW
from hg.chat import ChatService
from hg.verification.evidence import EventLog

QUESTION = "Thủ đô của Pháp là gì?"
LEDGER = f"asks-{NOW:%Y-%m}.jsonl"


class ChatReceiptOracle(ChatServiceBase):
    def call(self, service=None):
        """Run one chat in a thread; a hang (e.g. a FIFO) fails the case instead of the suite."""
        box = {}

        def run():
            try:
                box["result"] = (service or self.service)(QUESTION, general=True)
            except BaseException as exc:   # noqa: BLE001 - recorded and asserted below
                box["error"] = exc

        t = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "chat did not return within 5 s")
        box["seconds"] = time.monotonic() - started
        return box

    def assert_refused(self, box):
        self.assertNotIn("result", box, f"answered despite unsafe receipts ledger: {box.get('result', {}).get('outcome')}")
        self.assertIsInstance(box.get("error"), HTTPBoundaryError, repr(box.get("error")))
        self.assertEqual(box["error"].status, 503)

    # ---------- controls ----------

    def test_control_answer_names_events_that_exist_once_in_the_named_ledger(self):
        box = self.call()
        self.assertIn("result", box, repr(box.get("error")))
        brain = box["result"]["brain"]
        events = EventLog(self.home / brain["ledger"]).events()
        ids = [e["event_id"] for e in events]
        self.assertEqual(ids.count(brain["receipt_event_id"]), 1)
        for call in brain["model_calls"]:
            call_ids = [e["event_id"] for e in EventLog(self.home / call["ledger"]).events()]
            self.assertEqual(call_ids.count(call["event_id"]), 1, call["event_id"])

    # ---------- unsafe ledger file ----------

    def test_symlinked_ledger_is_refused_and_target_untouched(self):
        outside = self.tmp / "outside.jsonl"
        outside.write_bytes(b"")
        outside.chmod(0o600)
        os.symlink(outside, self.home / LEDGER)
        box = self.call()
        self.assert_refused(box)
        self.assertEqual(outside.read_bytes(), b"")

    def test_fifo_ledger_is_refused_without_blocking(self):
        os.mkfifo(self.home / LEDGER, 0o600)
        self.assert_refused(self.call())

    @unittest.skipUnless(hasattr(os, "link"), "Android's Python has no os.link")
    def test_hard_linked_ledger_is_refused_and_other_name_untouched(self):
        outside = self.tmp / "outside.jsonl"
        outside.write_bytes(b"")
        outside.chmod(0o600)
        os.link(outside, self.home / LEDGER)
        box = self.call()
        self.assert_refused(box)
        self.assertEqual(outside.read_bytes(), b"")

    @unittest.skipUnless(hasattr(os, "link"), "Android's Python has no os.link")
    def test_hard_linked_notes_ledger_is_refused(self):
        from hg.assistant.notes import Notebook
        notebook = Notebook(self.home)
        notebook.add("Xe máy thay dầu ngày 2026-09-15.", origin="test")
        notes = notebook.path
        outside = self.tmp / "notes-copy.jsonl"
        os.link(notes, outside)
        before = outside.read_bytes()
        self.assert_refused(self.call())
        self.assertEqual(outside.read_bytes(), before)
        self.assertFalse((self.home / LEDGER).exists())

    def test_group_or_world_writable_ledger_is_refused(self):
        for mode in (0o620, 0o602, 0o640):
            with self.subTest(mode=oct(mode)):
                path = self.home / LEDGER
                path.write_bytes(b"")
                path.chmod(mode)
                self.assert_refused(self.call())
                self.assertEqual(path.read_bytes(), b"")
                path.unlink()

    def test_damaged_ledger_is_refused_and_not_extended(self):
        good = EventLog(self.tmp / "seed.jsonl", clock=lambda: NOW)
        good.append("ASK", None, {"question": "x"})
        seed = (self.tmp / "seed.jsonl").read_bytes()
        cases = {
            "torn_tail": seed.rstrip(b"\n"),
            "duplicate_key": seed.replace(b'{"', b'{"kind":"ASK","', 1),
            "not_utf8": seed + b'\xff\xfe\n',
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                path = self.home / LEDGER
                path.write_bytes(data)
                path.chmod(0o600)
                self.assert_refused(self.call())
                self.assertEqual(path.read_bytes(), data)
                path.unlink()

    # ---------- named ledger matches the written one ----------

    def test_ledger_named_is_the_one_written_across_a_month_change(self):
        october = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
        written = self.home / "asks-2026-10.jsonl"

        def clock():
            # October until the ASK receipt is on disk, November from then on: the response is
            # built after the month changed.
            if written.exists() and b'"kind":"ASK"' in written.read_bytes():
                return october + timedelta(seconds=2)
            return october

        service = ChatService(self.home, release_id="r" * 64, clock=clock)
        box = self.call(service)
        self.assertIn("result", box, repr(box.get("error")))
        brain = box["result"]["brain"]
        named = self.home / brain["ledger"]
        self.assertTrue(named.exists(), f"response names {brain['ledger']}, which was never written")
        ids = [e["event_id"] for e in EventLog(named).events()]
        self.assertIn(brain["receipt_event_id"], ids)


if __name__ == "__main__":
    unittest.main()
