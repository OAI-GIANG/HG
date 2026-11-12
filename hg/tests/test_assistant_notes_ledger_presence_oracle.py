"""Presence oracle for the owner's notes ledger (WS-04, follow-up to #162).

``Notebook.snapshot()`` and ``Notebook.trusted_ids()`` decided "no notes yet" with
``Path.exists()``, which follows symlinks and swallows ENOENT/ENOTDIR/ELOOP. A
``notes.jsonl`` that is a dangling symlink or a symlink loop therefore read as an empty
notebook: ``hg note list`` printed "no notes" and ``hg ask`` answered "no note" (exit 5, as for a real empty notebook), and
``hg serve`` chat uses the same reader.

Expected outcome, from how each case is built: only a ledger that is truly absent (nothing
at the path, ENOENT) is an empty notebook. Anything else at the path that is not the
private regular file the Notebook writes is refused (``HomeError`` / ``MAEPError``, a
non-zero CLI exit), never read as zero notes. Controls: a fresh home with no ledger reads
``[]`` / exit 0, and a normal ledger still lists its notes.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.assistant.ask import ledger_hash, select_notes
from hg.assistant.home import HomeError
from hg.assistant.notes import Notebook

REPO = Path(__file__).resolve().parents[2]
REFUSED = (HomeError, MAEPError)


def _cli(home, *argv):
    env = dict(os.environ, HG_HOME=str(home), PYTHONPATH=str(REPO))
    env.pop("HG_MODEL_PROVIDER", None)
    return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=60)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        Notebook(self.home)                      # creates the private home, no ledger yet
        self.notes = self.home / "notes.jsonl"

    def _damage(self, kind):
        if kind == "dangling":
            os.symlink(self.root / "missing.jsonl", self.notes)
        elif kind == "loop":
            os.symlink(self.notes, self.notes)
        elif kind == "under_file":
            blocker = self.root / "blocker"
            blocker.write_text("x")
            os.symlink(blocker / "notes.jsonl", self.notes)
        else:
            raise AssertionError(kind)


DAMAGE = ("dangling", "loop", "under_file")


class NotebookPresenceTests(_Base):
    def test_damaged_ledger_is_refused_not_empty(self):
        for kind in DAMAGE:
            with self.subTest(kind=kind):
                if os.path.lexists(self.notes):
                    os.unlink(self.notes)
                self._damage(kind)
                nb = Notebook(self.home)
                for name, call in (("snapshot", nb.snapshot), ("active", nb.active),
                                   ("trusted_ids", nb.trusted_ids),
                                   ("select_notes", lambda: select_notes("thuốc", nb))):
                    with self.subTest(call=name):
                        with self.assertRaises(REFUSED, msg=f"{name} read a {kind} notes ledger as empty"):
                            call()
                with self.subTest(call="ledger_hash"):
                    with self.assertRaises(REFUSED, msg=f"ledger_hash reported a {kind} ledger as absent"):
                        ledger_hash(nb.path)

    def test_control_absent_ledger_is_empty(self):
        nb = Notebook(self.home)
        self.assertFalse(os.path.lexists(self.notes))
        self.assertEqual(nb.snapshot(), [])
        self.assertEqual(nb.trusted_ids(), set())
        self.assertIsNone(ledger_hash(nb.path))

    def test_control_normal_ledger_reads(self):
        nb = Notebook(self.home)
        record, _ = nb.add("Uống thuốc lúc 8 giờ.", origin="test")
        nb.trust(record["memory_id"])
        self.assertEqual([r["memory_id"] for r in nb.active()], [record["memory_id"]])
        self.assertEqual(nb.trusted_ids(), {record["memory_id"]})
        self.assertTrue(ledger_hash(nb.path).startswith("sha256:"))


class CliPresenceTests(_Base):
    def test_note_list_and_ask_refuse_damaged_ledger(self):
        for kind in DAMAGE:
            with self.subTest(kind=kind):
                if os.path.lexists(self.notes):
                    os.unlink(self.notes)
                self._damage(kind)
                for argv in (("note", "list"), ("note", "list", "--json"),
                             ("ask", "--notes-only", "Mấy giờ uống thuốc?")):
                    with self.subTest(argv=argv):
                        res = _cli(self.home, *argv)
                        # 0 = listed/answered, 5 = "no note on this" (EXIT_NO_DATA): both read the
                        # damaged ledger as an empty notebook.
                        self.assertNotIn(res.returncode, (0, 5),
                                         f"{argv} exit {res.returncode} on a {kind} notes ledger: {res.stdout!r}")
                        self.assertNotIn("Chưa có ghi chú nào", res.stdout)
                        self.assertNotIn("Ghi chú chưa có thông tin này", res.stdout)

    def test_control_cli_absent_and_normal(self):
        res = _cli(self.home, "note", "list", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(json.loads(res.stdout), [])
        Notebook(self.home).add("Uống thuốc lúc 8 giờ.", origin="test")
        res = _cli(self.home, "note", "list", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(len(json.loads(res.stdout)), 1)


if __name__ == "__main__":
    unittest.main()
