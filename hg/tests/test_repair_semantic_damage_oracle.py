"""Oracle: `hg repair` reports a notes ledger OK only if HG can actually load it (WS-04).

Every command that cannot read a ledger tells the owner "run hg repair" (CLI exit 78, chat
503 notes_ledger_damaged). Since #174 a notes.jsonl whose lines are each well-formed can still
be refused, because MemoryStore replay refuses histories its own API could not have written
(reused memory_id, forgotten note reactivated, ...). `repair` checked only the line format
(EventLog), so on such a ledger it printed status OK and exited 0 while `hg note list` kept
exiting 78: the diagnosis contradicted the failure it was sent to diagnose.

Oracle (the reader itself): for notes.jsonl, `inspect` says OK exactly when
`Notebook.active()` loads; a ledger HG refuses is DAMAGED with the refusal as reason and is
never rewritten; a torn last line is repaired only if what remains is a history HG loads
(otherwise rewriting would report REPAIRED for a ledger that is still refused).
Controls: genuine notes, a genuine torn tail, receipts ledgers.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.assistant.notes import Notebook
from hg.assistant.repair import inspect, repair
from hg.tests.test_memory_replay_history_oracle import FORGED, _append_raw, _seed

REPO = Path(__file__).resolve().parents[2]


def _loads(home):
    try:
        Notebook(home).active()
        return True
    except MAEPError:
        return False


class RepairAgreesWithReader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _home(self, name, forged=None, torn=False):
        home = self.root / name
        Notebook(home)                              # creates the private home
        notes = home / "notes.jsonl"
        kept, gone = _seed(notes)
        os.chmod(notes, 0o600)
        if forged is not None:
            kind, build = FORGED[forged]
            _append_raw(notes, kind, build(kept, gone))
        if torn:
            with notes.open("ab") as stream:
                stream.write(b'{"event_id": "torn", "seq": 99, "ki')
        return home, notes

    def test_inspect_ok_exactly_when_notes_load(self):
        for name in FORGED:
            with self.subTest(case=name):
                home, notes = self._home(f"h-{name}", forged=name)
                self.assertFalse(_loads(home))
                report = inspect(notes)
                self.assertEqual(report["status"], "DAMAGED", report)
                self.assertTrue(report.get("reason"), report)

    def test_repair_leaves_refused_history_untouched(self):
        for name in FORGED:
            with self.subTest(case=name):
                home, notes = self._home(f"r-{name}", forged=name)
                before = notes.read_bytes()
                report = next(r for r in repair(home) if r["file"] == "notes.jsonl")
                self.assertEqual(report["status"], "DAMAGED", report)
                self.assertEqual(notes.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in home.glob("notes.jsonl.bak-*")), [])

    def test_torn_tail_over_refused_history_is_not_repaired(self):
        for name in ("same_memory_id_new_text", "status_reactivates_forgotten", "unknown_event_kind"):
            with self.subTest(case=name):
                home, notes = self._home(f"t-{name}", forged=name, torn=True)
                before = notes.read_bytes()
                report = next(r for r in repair(home) if r["file"] == "notes.jsonl")
                self.assertEqual(report["status"], "DAMAGED", report)
                self.assertEqual(notes.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in home.glob("notes.jsonl.bak-*")), [])

    def test_cli_repair_exit_code_matches_note_list(self):
        for name in ("same_memory_id_new_text", "status_reactivates_forgotten"):
            with self.subTest(case=name):
                home, _ = self._home(f"c-{name}", forged=name)
                env = dict(os.environ, HG_HOME=str(home), PYTHONPATH=str(REPO))
                env.pop("HG_MODEL_PROVIDER", None)
                codes = {}
                for argv in (["note", "list", "--json"], ["repair"]):
                    run = subprocess.run([sys.executable, "-m", "hg", *argv], cwd=str(REPO), env=env,
                                         capture_output=True, text=True, timeout=60)
                    self.assertNotIn("Traceback", run.stderr)
                    codes[argv[0]] = run.returncode
                self.assertEqual(codes, {"note": 78, "repair": 78})

    # ---------- controls ----------

    def test_genuine_notes_are_ok(self):
        home, notes = self._home("ok")
        self.assertTrue(_loads(home))
        self.assertEqual(inspect(notes)["status"], "OK")
        self.assertEqual({r["status"] for r in repair(home)}, {"OK"})

    def test_genuine_torn_tail_is_repaired_and_loads(self):
        home, notes = self._home("torn", torn=True)
        self.assertFalse(_loads(home))
        report = next(r for r in repair(home) if r["file"] == "notes.jsonl")
        self.assertEqual(report["status"], "REPAIRED", report)
        self.assertTrue(_loads(home))
        self.assertEqual(len(Notebook(home).active()), 1)

    def test_receipts_ledger_is_checked_by_format_only(self):
        home, _ = self._home("asks")
        from hg.verification.evidence import EventLog
        asks = home / "asks-2026-11.jsonl"
        EventLog(asks).append("ASK", None, {"question": "x"})
        os.chmod(asks, 0o600)
        report = next(r for r in repair(home) if r["file"] == asks.name)
        self.assertEqual(report["status"], "OK", report)


if __name__ == "__main__":
    unittest.main()
