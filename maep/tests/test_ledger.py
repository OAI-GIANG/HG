import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from maep.core import MAEPError
from maep.ledger import append_event, append_generated, read_events


class LedgerTests(unittest.TestCase):
    def test_append_and_read_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            append_event(path, {"event_id": "EV-1", "type": "TEST", "result": "PASS"})
            append_event(path, {"event_id": "EV-2", "type": "AMENDMENT", "supersedes": "EV-1"})
            self.assertEqual([e["event_id"] for e in read_events(path)], ["EV-1", "EV-2"])

    def test_duplicate_event_id_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            append_event(path, {"event_id": "EV-1", "type": "TEST"})
            with self.assertRaises(MAEPError):
                append_event(path, {"event_id": "EV-1", "type": "OVERWRITE"})

    def test_corrupt_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.jsonl"
            path.write_text("{bad json}\n", encoding="utf-8")
            with self.assertRaises(MAEPError):
                append_event(path, {"event_id": "EV-1", "type": "TEST"})

    def test_event_id_required(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MAEPError):
                append_event(Path(directory) / "evidence.jsonl", {"type": "TEST"})


class LedgerTornTailTests(unittest.TestCase):
    """C1: a final ledger line without its record terminator is torn, never committed."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "evidence.jsonl"

    def write(self, data):
        self.path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_valid_json_final_line_without_terminator_is_refused(self):  # (a)
        self.write(b'{"event_id":"EV-1"}\n{"event_id":"EV-2"}')
        with self.assertRaisesRegex(MAEPError, "torn ledger tail at line 2"):
            read_events(self.path)

    def test_malformed_final_line_without_terminator_keeps_json_error(self):  # (b)
        self.write(b'{"event_id":"EV-1"}\n{"event_id":"EV-')
        with self.assertRaisesRegex(MAEPError, "invalid ledger JSON at line 2"):
            read_events(self.path)

    def test_malformed_terminated_line_message_unchanged(self):  # (c)
        self.write(b'{"event_id":"EV-1"}\n{bad}\n')
        with self.assertRaisesRegex(MAEPError, "invalid ledger JSON at line 2"):
            read_events(self.path)

    def test_append_onto_torn_tail_is_refused_and_bytes_unchanged(self):  # (d)
        before = self.write(b'{"event_id":"EV-1"}\n{"event_id":"EV-2"}')
        with self.assertRaisesRegex(MAEPError, "torn ledger tail"):
            append_event(self.path, {"event_id": "EV-3"})
        with self.assertRaisesRegex(MAEPError, "torn ledger tail"):
            append_generated(self.path, lambda current: {"event_id": "EV-3"})
        self.assertEqual(self.digest(), before)

    def test_task_store_restore_refuses_torn_ledger(self):  # (e)
        from maep.task_store import TaskStore
        before = self.write(b'{"event_id":"EV-1"}')
        with self.assertRaisesRegex(MAEPError, "torn ledger tail at line 1"):
            TaskStore.restore(self.path)
        self.assertEqual(self.digest(), before)

    def test_operator_removing_torn_tail_restores_committed_records(self):  # (f)
        append_event(self.path, {"event_id": "EV-1", "type": "TEST"})
        committed = self.path.read_bytes()
        self.path.write_bytes(committed + b'{"event_id":"EV-2","type":"TEST"}')
        with self.assertRaises(MAEPError):
            read_events(self.path)
        self.path.write_bytes(committed)  # operator recovery: drop the torn tail
        self.assertEqual([e["event_id"] for e in read_events(self.path)], ["EV-1"])
        append_event(self.path, {"event_id": "EV-2", "type": "TEST"})
        self.assertEqual([e["event_id"] for e in read_events(self.path)], ["EV-1", "EV-2"])

    def test_empty_and_single_complete_line_load(self):  # (g)
        self.write(b"")
        self.assertEqual(read_events(self.path), [])
        self.write(b'{"event_id":"EV-1"}\n')
        self.assertEqual([e["event_id"] for e in read_events(self.path)], ["EV-1"])

    def test_crlf_terminated_line_is_accepted(self):  # (h)
        self.write(b'{"event_id":"EV-1"}\r\n{"event_id":"EV-2"}\r\n')
        self.assertEqual([e["event_id"] for e in read_events(self.path)], ["EV-1", "EV-2"])

    def test_pre_append_tail_check_refuses_even_if_reader_misses_it(self):
        # Defence in depth: the append path checks the last byte itself.
        before = self.write(b'{"event_id":"EV-1"}')
        with patch("maep.ledger._read_events_unlocked", return_value=[{"event_id": "EV-1"}]):
            with self.assertRaisesRegex(MAEPError, "torn ledger tail"):
                append_event(self.path, {"event_id": "EV-2"})
            with self.assertRaisesRegex(MAEPError, "torn ledger tail"):
                append_generated(self.path, lambda current: {"event_id": "EV-2"})
        self.assertEqual(self.digest(), before)


if __name__ == "__main__":
    unittest.main()
