"""CLI surface tests for safe memory curation and explicit save-from-ASK."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hg.assistant.ask import append_receipt
from hg.assistant.notes import Notebook


REPO = Path(__file__).resolve().parents[2]


class MemoryCurationCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-memory-cli-"))
        self.home = self.tmp / "assistant"
        self.home.mkdir(mode=0o700)
        self.env = dict(os.environ, HG_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "hg", *args], cwd=REPO, env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_curate_cli_returns_read_only_report(self):
        Notebook(self.home).add("Lịch họp dự án HG vào thứ Năm lúc 20 giờ.", subject="lich-hop", origin="test")
        proc = self.run_cli("note", "curate", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["mode"], "READ_ONLY_REVIEW_CANDIDATES")
        self.assertFalse(report["policy"]["auto_delete"])
        self.assertFalse(report["policy"]["auto_merge"])
        self.assertEqual(len(Notebook(self.home).active()), 1)

    def test_save_ask_cli_requires_digest_confirmation_and_is_idempotent(self):
        event = append_receipt(
            self.home, "ASK",
            {"outcome": "ANSWERED", "answer": "Nên ghi lại lịch bảo dưỡng và số km sau mỗi lần thay dầu.",
             "question": "Nên theo dõi xe thế nào?", "provider": "ollama", "model": "fixture"},
            clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        args = ("note", "save-ask", event["event_id"], "--subject", "bao-duong-xe",
                "--text", "Nên ghi lại lịch bảo dưỡng và số km sau mỗi lần thay dầu.")
        preview = self.run_cli(*args, "--json")
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        preview_json = json.loads(preview.stdout)
        self.assertFalse(preview_json["will_write"])
        self.assertFalse((self.home / "notes.jsonl").exists())

        confirm = preview_json["confirmation_sha256"]
        saved = self.run_cli(*args, "--confirm", confirm, "--json")
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)
        saved_json = json.loads(saved.stdout)
        self.assertTrue(saved_json["created"])

        retried = self.run_cli(*args, "--confirm", confirm, "--json")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertFalse(json.loads(retried.stdout)["created"])
        notes = Notebook(self.home).active()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["source"], "USER")
        self.assertIn(event["event_id"], notes[0]["source_ref"])

    def test_cli_rejects_modified_text_after_preview(self):
        event = append_receipt(
            self.home, "ASK",
            {"outcome": "ANSWERED", "answer": "Nên theo dõi lịch thay dầu. Ghi lại số kilomet sau mỗi lần thay."},
            clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        base = ("note", "save-ask", event["event_id"], "--subject", "xe",
                "--text", "Nên theo dõi lịch thay dầu.")
        preview = self.run_cli(*base, "--json")
        digest = json.loads(preview.stdout)["confirmation_sha256"]
        changed = self.run_cli("note", "save-ask", event["event_id"], "--subject", "xe",
                               "--text", "Ghi lại số kilomet sau mỗi lần thay.", "--confirm", digest)
        self.assertEqual(changed.returncode, 2)
        self.assertIn("confirmation digest mismatch", changed.stdout)
        self.assertFalse((self.home / "notes.jsonl").exists())


    def test_cli_reports_inactive_ask_receipt_as_owner_action_not_ledger_damage(self):
        event = append_receipt(
            self.home, "ASK", {"outcome": "ANSWERED", "answer": "Ghi lại lịch bảo dưỡng sau mỗi lần thay dầu."},
            clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
        args = ("note", "save-ask", event["event_id"], "--subject", "bao-duong-xe",
                "--text", "Ghi lại lịch bảo dưỡng sau mỗi lần thay dầu.")
        preview = self.run_cli(*args, "--json")
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        digest = json.loads(preview.stdout)["confirmation_sha256"]
        saved = self.run_cli(*args, "--confirm", digest, "--json")
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)
        record = Notebook(self.home).active()[0]
        Notebook(self.home).forget(record["memory_id"], reason="test inactive receipt")

        replay = self.run_cli(*args, "--confirm", digest, "--json")
        self.assertEqual(replay.returncode, 4)
        self.assertIn("biên nhận ASK đã gắn với ghi chú bị thu hồi hoặc thay thế", replay.stdout)
        self.assertNotIn("Sổ cái hỏng", replay.stdout)
        self.assertEqual(Notebook(self.home).active(), [])


    def test_generic_memory_curate_reads_only_the_explicit_ledger(self):
        from hg.memory.store import MemoryStore
        ledger = self.tmp / "brain-memory.jsonl"
        store = MemoryStore(ledger)
        store.remember(layer="SEMANTIC", kind="NOTE", subject="lich-hop",
                       content="Họp dự án HG thứ Năm lúc 20 giờ.", source="USER", source_ref="fixture:1")
        store.remember(layer="SEMANTIC", kind="NOTE", subject="lich-hop",
                       content="Họp dự án HG thứ Năm lúc 20 giờ.", source="USER", source_ref="fixture:2")
        proc = self.run_cli("memory", "curate", "--ledger", str(ledger), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["records_seen"], 2)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        self.assertEqual(len(MemoryStore(ledger).all_records()), 2)

    def test_generic_memory_curate_refuses_symlink_ledger(self):
        target = self.tmp / "real-memory.jsonl"
        from hg.memory.store import MemoryStore
        MemoryStore(target)
        link = self.tmp / "memory-link.jsonl"
        link.symlink_to(target)
        proc = self.run_cli("memory", "curate", "--ledger", str(link), "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a symlink", proc.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
