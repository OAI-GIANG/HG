import tempfile
import unittest
from pathlib import Path
from maep.core import MAEPError
from maep.ledger import append_event, read_events


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


if __name__ == "__main__":
    unittest.main()
