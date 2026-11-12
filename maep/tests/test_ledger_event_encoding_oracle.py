"""WS-04 oracle: a ledger event that has no one exact JSON/UTF-8 encoding is refused before the write.

Defects reproduced before the fix (maep/ledger.py ``_append_unlocked``):
- a lone surrogate in an event (e.g. a task objective) raised a raw ``UnicodeEncodeError`` from
  inside the ledger lock; ``TaskStore`` callers got neither ``MAEPError`` nor "state unchanged"
  (the "Not covered" item of ledger addendum §22);
- ``NaN``/``Infinity`` were written to the ledger as the non-standard tokens ``NaN``/``Infinity``
  (``json.dumps`` default ``allow_nan=True``), so the ledger stopped being standard JSON Lines.

Acceptance criteria:
- ``append_event`` and ``append_generated`` refuse such an event with ``LedgerAppendRefused``
  (a ``MAEPError``) and write no byte;
- ``TaskStore.create_task`` / ``record_*`` report it as ``MAEPError`` "state unchanged", never
  ``LedgerOutcomeUnknown`` and never a raw exception; the store stays usable afterwards;
- controls: canonical events, non-ASCII text and a paired (valid) astral character still append
  and read back unchanged.
"""
import math
import tempfile
import unittest
from pathlib import Path

from maep.core import MAEPError
from maep.ledger import LedgerAppendRefused, append_event, append_generated, read_events
from maep.policy import PolicyEvaluator
from maep.task_store import LedgerOutcomeUnknown, TaskStore
from maep.tests.test_task_store import Clock, draft_task, grant

BAD_VALUES = {
    "lone_high_surrogate": "a\ud800b",
    "lone_low_surrogate": "\udc00",
    "nan": math.nan,
    "infinity": math.inf,
    "minus_infinity": -math.inf,
}


class AppendEncodingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.jsonl"
        append_event(self.path, {"event_id": "E0", "text": "xin chào \U0001F600"})
        self.before = self.path.read_bytes()

    def test_append_event_refuses_unencodable_values(self):
        for name, value in BAD_VALUES.items():
            for event in ({"event_id": "E1", "v": value}, {"event_id": "E1", "nested": {"k": [value]}}):
                with self.subTest(name=name, event=repr(event)):
                    with self.assertRaises(LedgerAppendRefused):
                        append_event(self.path, event)
                    self.assertEqual(self.path.read_bytes(), self.before)

    def test_append_event_refuses_unencodable_key(self):
        with self.assertRaises(LedgerAppendRefused):
            append_event(self.path, {"event_id": "E1", "\ud800": 1})
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_append_generated_refuses_unencodable_values(self):
        for name, value in BAD_VALUES.items():
            with self.subTest(name=name):
                with self.assertRaises(MAEPError):
                    append_generated(self.path, lambda current: {"event_id": "E1", "v": value})
                self.assertEqual(self.path.read_bytes(), self.before)

    def test_controls_append_and_read_back(self):
        append_event(self.path, {"event_id": "E1", "text": "đ\r\n\U0001F600", "n": 1.5})
        append_generated(self.path, lambda current: {"event_id": f"E{len(current)}", "ok": True})
        events = read_events(self.path)
        self.assertEqual([e["event_id"] for e in events], ["E0", "E1", "E2"])
        self.assertEqual(events[1]["text"], "đ\r\n\U0001F600")
        self.assertNotIn(b"NaN", self.path.read_bytes())


class TaskStoreEncodingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = Path(directory.name) / "ledger.jsonl"
        self.store = TaskStore(self.ledger, policy_evaluator=PolicyEvaluator([grant()], lambda c, r: True),
                               clock=Clock())

    def assertStateUnchanged(self, call):
        before = self.ledger.read_bytes() if self.ledger.exists() else None
        try:
            call()
        except LedgerOutcomeUnknown as exc:  # pragma: no cover - failure path
            self.fail(f"refusal before the write reported IN_DOUBT: {exc}")
        except MAEPError as exc:
            self.assertIn("state unchanged", str(exc))
        else:
            self.fail("unencodable event was accepted")
        after = self.ledger.read_bytes() if self.ledger.exists() else None
        self.assertEqual(after, before)

    def test_create_task_with_unencodable_field_is_refused(self):
        for name, value in BAD_VALUES.items():
            with self.subTest(name=name):
                task = draft_task("T-BAD")
                task["objective"] = value if isinstance(value, str) else "x"
                if not isinstance(value, str):
                    task["risks"] = [{"risk": "r", "score": value}]
                self.assertStateUnchanged(lambda: self.store.create_task(task))
                with self.assertRaises(MAEPError):
                    self.store.snapshot("T-BAD")
        # The store stays usable and the ledger stays standard JSON Lines.
        self.assertEqual(self.store.create_task(draft_task("T-1")), 1)
        self.assertEqual(TaskStore.restore(self.ledger).snapshot("T-1")["version"], 1)

    def test_record_blocker_with_lone_surrogate_is_refused(self):
        self.store.create_task(draft_task("T-1"))
        self.assertStateUnchanged(lambda: self.store.record_blocker(
            "T-1", {"blocker_id": "B-1", "known_cause": "\udfff", "unknowns": [], "missing_prerequisite": "x",
                    "next_action": "y", "reopen_condition": "z"}, expected_version=1))
        self.assertEqual(self.store.snapshot("T-1")["version"], 1)


if __name__ == "__main__":
    unittest.main()
