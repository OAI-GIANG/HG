"""Oracle: `hg note forget --reason` is input, never a damaged ledger (WS-04).

The documented contract (docs/HG_V1_GUIDE.md §4, §6): exit 2 means the input is unusable;
exit 78 means a ledger cannot be read and the owner should run `hg repair`. Before this oracle
`Notebook.forget` passed `--reason` to the ledger unchecked:

- a blank reason (`--reason ""`, `--reason "   "`) was refused by `MemoryStore.retract`
  with a `MAEPError`, which the CLI reports as "Sổ cái hỏng ... Chạy: hg repair" (exit 78)
  although the ledger was intact;
- a reason whose bytes are not UTF-8 reached the ledger writer, which refused to encode it:
  the same false "damaged ledger, run hg repair" (exit 78);
- control, bidirectional-override and unbounded reasons were written into the owner's
  ledger, unlike note text.

The same holds for note text from callers other than the CLI: `clean_text` let lone
surrogates through (category Cs), so `Notebook.add` failed later at the ledger writer.

Oracle: the exit-code table, `clean_text` rules for owner text, and the ledger bytes
(an unusable reason changes no byte; `hg repair` keeps reporting OK).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.assistant.notes import MAX_REASON_CHARS, NoteError, Notebook, clean_text

ROOT = Path(__file__).resolve().parents[2]
NOTE = "Họp với Lan lúc 9 giờ thứ Hai"

BAD_REASONS = [
    b"",
    b"   ",
    b"\t\n",
    b"l\xffy do",                       # not UTF-8
    b"\xff\xfe",
    "lý do".encode() + b"\xe1\xbb",     # truncated multibyte
    "lý do \x1b[2J".encode(),          # terminal control sequence
    "lý do ‮".encode(),           # bidirectional override
    b"x" * (MAX_REASON_CHARS + 1),
]


class ForgetReasonOracle(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        os.chmod(self.home, 0o700)
        r = self.run_hg(["note", "add", NOTE])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.note_id = Notebook(self.home).active()[0]["memory_id"]

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_hg(self, argv):
        env = dict(os.environ, HG_HOME=os.fsencode(str(self.home)), NO_COLOR="1", PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, input=b"",
                              capture_output=True, timeout=60)

    def ledger(self):
        return (self.home / "notes.jsonl").read_bytes()

    def test_unusable_reason_is_input_error_exit_2(self):
        before = self.ledger()
        for reason in BAD_REASONS:
            with self.subTest(reason=reason[:24]):
                r = self.run_hg(["note", "forget", self.note_id, "--reason", reason])
                self.assertEqual(r.returncode, 2, f"{r.stdout[:300]!r} {r.stderr[-300:]!r}")
                self.assertNotIn(b"Traceback", r.stderr)
                self.assertNotIn(b"hg repair", r.stdout, "an unusable reason is not a damaged ledger")
                self.assertIn("lý do".encode(), r.stdout, "refusal names the reason")
                self.assertEqual(self.ledger(), before, "no ledger byte may change")
        self.assertEqual([n["memory_id"] for n in Notebook(self.home).active()], [self.note_id])
        r = self.run_hg(["repair"])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_api_reason_rules(self):
        nb = Notebook(self.home)
        before = self.ledger()
        for reason in [None, 3, "", "  ", "a\udcffb", "a\x00b", "‮", "x" * (MAX_REASON_CHARS + 1)]:
            with self.subTest(reason=repr(reason)[:24]):
                with self.assertRaises(NoteError):
                    nb.forget(self.note_id, reason=reason)
                self.assertEqual(self.ledger(), before)

    def test_api_note_text_with_lone_surrogate_is_input_error(self):
        nb = Notebook(self.home)
        before = self.ledger()
        for text in ["a\udcffb", "\ud800", "Họp \udce1\udcbb"]:
            with self.subTest(text=repr(text)):
                with self.assertRaises(NoteError):
                    clean_text(text)
                with self.assertRaises(NoteError):
                    nb.add(text, origin="test")
                self.assertEqual(self.ledger(), before)

    # ---------- controls ----------

    def test_control_usable_reasons_retract(self):
        for argv, expected in [([], "owner asked to forget"),
                               (["--reason", "đã xong"], "đã xong"),
                               (["--reason", "  có khoảng trắng  "], "có khoảng trắng"),
                               (["--reason", "x" * MAX_REASON_CHARS], "x" * MAX_REASON_CHARS)]:
            with self.subTest(argv=argv[:1] + [a[:20] for a in argv[1:]]):
                nb = Notebook(self.home)
                note_id = nb.active()[0]["memory_id"] if nb.active() else None
                if note_id is None:
                    note_id = nb.add(f"{NOTE} {len(expected)}", origin="test")[0]["memory_id"]
                r = self.run_hg(["note", "forget", note_id, *argv])
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn(note_id, [n["memory_id"] for n in Notebook(self.home).active()])
                self.assertIn(f'"reason":"{expected}"'.encode(), self.ledger())
        r = self.run_hg(["repair"])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_control_unknown_id_stays_exit_2(self):
        r = self.run_hg(["note", "forget", "M-999999-000000", "--reason", "x"])
        self.assertEqual(r.returncode, 2, r.stdout)


if __name__ == "__main__":
    unittest.main()
