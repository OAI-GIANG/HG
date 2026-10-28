"""Notebook, home directory, lock and repair (AC-N1..AC-N5)."""
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

from hg.assistant.home import Busy, HomeError, ensure_home, locked
from hg.assistant.notes import NoteConflict, NoteError, Notebook
from hg.assistant.repair import inspect, repair
from maep.core import MAEPError

REPO = Path(__file__).resolve().parents[2]


class HomeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-notes-"))
        self.home = self.tmp / "home"
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))
        self.nb = Notebook(self.home)


class HomeTests(HomeBase):
    """AC-N4."""

    def test_home_is_created_private(self):
        self.assertEqual(os.stat(self.home).st_mode & 0o777, 0o700)

    def test_wide_permissions_are_refused(self):
        os.chmod(self.home, 0o755)
        with self.assertRaisesRegex(HomeError, "group/other"):
            ensure_home(self.home)

    def test_symlinked_home_is_refused(self):
        link = self.tmp / "link"
        link.symlink_to(self.home)
        with self.assertRaisesRegex(HomeError, "symlink"):
            ensure_home(link)

    def test_shared_storage_is_refused(self):
        with self.assertRaisesRegex(HomeError, "shared storage"):
            ensure_home(Path("/sdcard/hg"), create=False)

    def test_relative_home_is_refused(self):
        with self.assertRaisesRegex(HomeError, "absolute"):
            ensure_home(Path("relative/home"))


class NotebookTests(HomeBase):
    """AC-N1, AC-N2."""

    def test_notes_survive_a_new_process_and_list_in_order(self):
        for text in ("Họp nhóm thứ Năm lúc 20 giờ.", "Bảo hiểm xe máy hết hạn ngày 2027-03-01.", "Cây lan tưới 2 lần mỗi tuần."):
            self.nb.add(text, origin="test")
        script = ("import sys; from hg.assistant.notes import Notebook; "
                  "print('|'.join(r['content'] for r in Notebook(sys.argv[1]).active()))")
        proc = subprocess.run([sys.executable, "-c", script, str(self.home)], cwd=REPO, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().split("|"),
                         ["Họp nhóm thứ Năm lúc 20 giờ.", "Bảo hiểm xe máy hết hạn ngày 2027-03-01.",
                          "Cây lan tưới 2 lần mỗi tuần."])

    def test_search_without_diacritics_and_in_nfd(self):
        self.nb.add("Họp nhóm thứ Năm lúc 20 giờ.", origin="test")
        insurance, _ = self.nb.add("Bảo hiểm xe máy hết hạn ngày 2027-03-01.", origin="test")
        self.assertEqual(self.nb.search("bao hiem")[0]["memory_id"], insurance["memory_id"])
        nfd = unicodedata.normalize("NFD", "bảo hiểm xe")
        self.assertEqual(self.nb.search(nfd)[0]["memory_id"], insurance["memory_id"])

    def test_query_without_shared_content_word_finds_nothing(self):
        self.nb.add("Họp nhóm thứ Năm lúc 20 giờ.", origin="test")
        self.assertEqual(self.nb.search("thủ đô nước Pháp là gì"), [])
        self.assertEqual(self.nb.search("là của và có"), [])

    def test_same_subject_different_text_is_a_conflict(self):
        first, _ = self.nb.add("Thay dầu xe ngày 2026-09-15.", subject="xe", origin="test")
        with self.assertRaises(NoteConflict) as ctx:
            self.nb.add("Thay dầu xe ngày 2026-10-01.", subject="xe", origin="test")
        self.assertEqual(ctx.exception.existing["memory_id"], first["memory_id"])

    def test_replacement_supersedes_and_keeps_history(self):
        first, _ = self.nb.add("Thay dầu xe ngày 2026-09-15.", subject="xe", origin="test")
        second, created = self.nb.add("Thay dầu xe ngày 2026-10-01.", subject="xe", replaces=first["memory_id"],
                                      origin="test")
        self.assertTrue(created)
        history = self.nb.history(second["memory_id"])
        self.assertEqual([(r["memory_id"], r["status"]) for r in history],
                         [(first["memory_id"], "SUPERSEDED"), (second["memory_id"], "ACTIVE")])

    def test_identical_note_is_not_duplicated(self):
        first, _ = self.nb.add("Thay dầu xe ngày 2026-09-15.", subject="xe", origin="test")
        again, created = self.nb.add("thay dầu  xe ngày 2026-09-15.", subject="xe", origin="test")
        self.assertFalse(created)
        self.assertEqual(again["memory_id"], first["memory_id"])

    def test_forget_retracts_but_history_remains(self):
        note, _ = self.nb.add("Mật mã tủ đồ là 4421.", origin="test")
        self.nb.forget(note["memory_id"])
        self.assertEqual(self.nb.active(), [])
        self.assertEqual(self.nb.history(note["memory_id"])[0]["status"], "RETRACTED")
        self.assertIn("4421", (self.home / "notes.jsonl").read_text(encoding="utf-8"))

    def test_origin_is_recorded_and_bad_input_refused(self):
        note, _ = self.nb.add("Ghi từ pipe.", origin="pipe")
        self.assertEqual(note["source_ref"], "cli:pipe")
        for bad in ("", "   ", "có\x1b]52;c;ZWNobw==\x07điều khiển", "x" * 5000):
            with self.assertRaises(NoteError):
                self.nb.add(bad, origin="test")

    def test_note_kind_requires_user_source(self):
        from hg.memory.store import MemoryStore
        store = MemoryStore(self.tmp / "m.jsonl")
        with self.assertRaisesRegex(MAEPError, "NOTE comes from the USER"):
            store.remember(layer="SEMANTIC", kind="NOTE", subject="s", content="c", source="TOOL", source_ref="x")


class LockTests(HomeBase):
    """AC-N3: a second writer is refused while the first holds the lock; the ledger stays readable."""

    def test_second_process_is_refused_with_exit_75(self):
        self.nb.add("Ghi chú đầu tiên.", origin="test")
        env = dict(os.environ, HG_HOME=str(self.home))
        with locked(self.home, exclusive=True):
            proc = subprocess.run([sys.executable, "-m", "hg", "note", "add", "ghi chú thứ hai"], cwd=REPO, env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 75, proc.stdout + proc.stderr)
        self.assertEqual([r["content"] for r in self.nb.active()], ["Ghi chú đầu tiên."])

    def test_shared_locks_coexist_and_exclusive_waits(self):
        with locked(self.home, exclusive=False):
            with locked(self.home, exclusive=False, wait_s=0.2):
                pass
            with self.assertRaises(Busy):
                with locked(self.home, exclusive=True, wait_s=0.2):
                    pass


class RepairTests(HomeBase):
    """AC-N5."""

    def test_torn_last_line_is_reported_then_repaired_with_backup(self):
        self.nb.add("Ghi chú một.", origin="test")
        self.nb.add("Ghi chú hai.", origin="test")
        path = self.home / "notes.jsonl"
        good = path.read_bytes()
        with path.open("ab") as stream:
            stream.write(b'{"event_id": "torn", "seq": 3, "ki')
        with self.assertRaises(MAEPError):
            self.nb.active()
        self.assertEqual(inspect(path)["status"], "TORN_LAST_LINE")
        results = repair(self.home)
        report = next(r for r in results if r["file"] == "notes.jsonl")
        self.assertEqual(report["status"], "REPAIRED")
        self.assertEqual(path.read_bytes(), good)
        self.assertTrue((self.home / report["backup"]).read_bytes().endswith(b'"ki'))
        self.assertEqual(len(self.nb.active()), 2)

    def test_damage_in_the_middle_is_not_touched(self):
        self.nb.add("Ghi chú một.", origin="test")
        self.nb.add("Ghi chú hai.", origin="test")
        path = self.home / "notes.jsonl"
        lines = path.read_bytes().split(b"\n")
        lines[0] = b"garbage"
        damaged = b"\n".join(lines)
        path.write_bytes(damaged)
        report = next(r for r in repair(self.home) if r["file"] == "notes.jsonl")
        self.assertEqual(report["status"], "DAMAGED")
        self.assertEqual(path.read_bytes(), damaged)


if __name__ == "__main__":
    unittest.main()
