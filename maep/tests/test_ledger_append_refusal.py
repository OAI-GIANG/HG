"""Batch 1: a ledger append refused before any write is "state unchanged", never IN_DOUBT.

Regression for CI on main 9d82701 (Python 3.14):
hg.tests.test_writer_admission.CrossProcessLedgerTests
.test_taskstore_duplicate_task_event_id_has_single_winner_across_processes saw
['CREATED', 'LedgerOutcomeUnknown']. The loser's append_event refused the duplicate event_id
before writing, but TaskStore._commit could not tell that from a failure after the write and
re-read the ledger; when the winner's event matched the loser's byte for byte (same
recorded_at) the re-read found it and reported IN_DOUBT.

Acceptance criteria:
- append_event raises LedgerAppendRefused (a MAEPError) for every refusal before the write:
  invalid event, duplicate event_id, torn or unreadable ledger, unsafe ledger file;
- an OSError from the write or fsync is NOT LedgerAppendRefused;
- TaskStore reports a refused append as plain MAEPError "state unchanged" without re-reading,
  even when an identical event is on disk;
- an error after the write still yields LedgerOutcomeUnknown.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from maep import ledger as ledger_module
from maep.core import MAEPError
from maep.ledger import append_event, read_events
from maep.policy import PolicyEvaluator
from maep.task_store import LedgerOutcomeUnknown, TaskStore
from maep.tests.test_task_store import Clock, draft_task, grant


def refused_type():
    return getattr(ledger_module, "LedgerAppendRefused", None)


class AppendEventRefusalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.jsonl"

    def assertRefused(self, call, message):
        kind = refused_type()
        self.assertIsNotNone(kind, "maep.ledger must define LedgerAppendRefused")
        with self.assertRaisesRegex(MAEPError, message) as caught:
            call()
        self.assertIsInstance(caught.exception, kind)

    def test_duplicate_event_id_is_refused(self):
        append_event(self.path, {"event_id": "E1"})
        self.assertRefused(lambda: append_event(self.path, {"event_id": "E1"}), "event_id already exists")
        self.assertEqual(len(read_events(self.path)), 1)

    def test_invalid_event_is_refused(self):
        self.assertRefused(lambda: append_event(self.path, {"no": "id"}), "non-empty event_id")
        self.assertFalse(self.path.exists())

    def test_torn_tail_is_refused(self):
        self.path.write_bytes(b'{"event_id":"E1"}')
        self.assertRefused(lambda: append_event(self.path, {"event_id": "E2"}), "torn ledger tail")
        self.assertEqual(self.path.read_bytes(), b'{"event_id":"E1"}')

    def test_ledger_writable_by_others_is_refused(self):
        append_event(self.path, {"event_id": "E1"})
        os.chmod(self.path, 0o666)
        self.addCleanup(os.chmod, self.path, 0o600)
        self.assertRefused(lambda: append_event(self.path, {"event_id": "E2"}), "owner-owned regular file")

    def test_write_error_is_not_a_refusal(self):
        with mock.patch.object(ledger_module, "_append_unlocked", side_effect=OSError("EIO on write")):
            with self.assertRaises(OSError) as caught:
                append_event(self.path, {"event_id": "E1"})
        kind = refused_type()
        if kind is not None:
            self.assertNotIsInstance(caught.exception, kind)


class TaskStoreRefusedAppendTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = Path(directory.name) / "tasks.jsonl"
        self.evaluator = PolicyEvaluator([grant()], lambda condition, req: True)

    def test_losing_an_identical_event_race_is_state_unchanged_not_in_doubt(self):
        # Deterministic form of the CI failure: same fixed clock and same task, so both writers
        # build byte-identical TASK_CREATED events; a barrier makes both reach the append.
        clock = Clock()
        barrier = threading.Barrier(2, timeout=20)

        def append_after_both_built(path, event):
            barrier.wait()
            return append_event(path, event)

        stores = [TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=clock,
                            ledger_append=append_after_both_built) for _ in range(2)]
        outcomes = {}

        def run(index):
            try:
                stores[index].create_task(draft_task())
                outcomes[index] = "CREATED"
            except MAEPError as exc:
                outcomes[index] = exc

        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertFalse(any(t.is_alive() for t in threads))

        losers = [o for o in outcomes.values() if o != "CREATED"]
        self.assertEqual(len(losers), 1, outcomes)
        (loser,) = losers
        self.assertIs(type(loser), MAEPError)
        self.assertNotIsInstance(loser, LedgerOutcomeUnknown)
        self.assertIn("state unchanged", str(loser))
        self.assertEqual(len(read_events(self.ledger)), 1)

    def test_torn_tail_appearing_before_the_append_is_state_unchanged(self):
        # Another writer leaves a torn tail after this store refreshed. append_event refuses before
        # writing; the old readback then failed on the torn ledger and reported IN_DOUBT.
        def tear_then_append(path, event):
            with open(path, "ab") as stream:
                stream.write(b'{"event_id":"FOREIGN@1"}')
            return append_event(path, event)

        store = TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=Clock(),
                          ledger_append=tear_then_append)
        with self.assertRaises(MAEPError) as caught:
            store.create_task(draft_task())
        self.assertIs(type(caught.exception), MAEPError)
        self.assertIn("state unchanged", str(caught.exception))
        self.assertIn("torn ledger tail", str(caught.exception))
        self.assertEqual(self.ledger.read_bytes(), b'{"event_id":"FOREIGN@1"}')

    def test_error_after_the_write_is_still_in_doubt(self):
        def append_then_fail(path, event):
            append_event(path, event)
            raise OSError("fsync failed after the write")

        store = TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=Clock(),
                          ledger_append=append_then_fail)
        with self.assertRaises(LedgerOutcomeUnknown):
            store.create_task(draft_task())
        self.assertEqual(len(read_events(self.ledger)), 1)


if __name__ == "__main__":
    unittest.main()
