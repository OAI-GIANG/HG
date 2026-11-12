"""Oracle: `hg ask` and `hg note add` act only on text they can read as written (WS-04).

The documented contract (docs/HG_V1_GUIDE.md §4, §6): exit 2 means the input is unusable;
exit 78 means a ledger cannot be read and the owner should run `hg repair`. Before this oracle
`hg ask` and `hg note add` read stdin and argv with no rules (only `hg check` and
`hg summarize` had them):

- `hg ask` with bytes that are not UTF-8 (stdin or argv) printed an answer for the mangled
  question, then failed writing the receipt and told the owner a ledger was damaged
  ("Sổ cái hỏng ... Chạy: hg repair", exit 78) although every ledger was intact.
- `hg ask` with a NUL byte silently dropped it and answered a different question (exit 5).
- `hg note add` with bytes that are not UTF-8 ended in a traceback (exit 1).
- stdin was read without a bound.

Oracle: the input rules `summarize.read_input` already enforces (UTF-8, no NUL, 1 MB), the
exit-code table, and the ledgers themselves (an unusable input changes no byte of them).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTE = "Họp với Lan lúc 9 giờ thứ Hai"
QUESTION = "Họp với Lan lúc mấy giờ?"

UNREADABLE = [
    b"\xff\xfe abc",                                     # not UTF-8
    QUESTION.encode("utf-16"),                           # other encoding
    "Hop voi Lan luc may gio".encode() + b"\xe1\xbb",    # truncated multibyte
    QUESTION.encode() + b"\x00 xyz",                     # NUL byte
    b"\x00",
    b"a" * 1_000_001,                                    # over 1 MB
]
NOT_UTF8_ARGV = [b"Ng\xe0y h\xe1p?", b"\xff\xfe", "Họp lúc".encode() + b"\xe1\xbb"]


class AskNoteInputOracle(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        os.chmod(self.home, 0o700)
        r = self.run_hg(["note", "add", NOTE])
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_hg(["ask", "--notes-only", QUESTION])     # creates the receipts ledger
        self.assertIn(r.returncode, (0, 3), r.stdout + r.stderr)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_hg(self, argv, stdin=b""):
        env = dict(os.environ, HG_HOME=str(self.home), NO_COLOR="1", PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, input=stdin,
                              capture_output=True, timeout=60)

    def ledgers(self):
        return {p.name: p.read_bytes() for p in sorted(self.home.iterdir()) if p.suffix == ".jsonl"}

    def assertRefused(self, r, before, case):
        self.assertEqual(r.returncode, 2, f"{case!r}: {r.stdout[:300]!r} {r.stderr[-300:]!r}")
        self.assertNotIn(b"Traceback", r.stderr, case)
        self.assertNotIn(b"hg repair", r.stdout, f"{case!r}: an unusable input is not a damaged ledger")
        self.assertTrue(r.stdout.strip(), f"{case!r}: refusal must say why")
        self.assertEqual(self.ledgers(), before, f"{case!r}: no ledger may change")

    def test_ask_unreadable_stdin_is_refused_exit_2(self):
        before = self.ledgers()
        for data in UNREADABLE:
            with self.subTest(data=data[:24]):
                r = self.run_hg(["ask", "--notes-only"], stdin=data)
                self.assertRefused(r, before, data[:24])
                self.assertNotIn("Ghi chú".encode(), r.stdout, "no answer to a question HG could not read")

    def test_ask_argv_not_utf8_is_refused_exit_2(self):
        before = self.ledgers()
        for arg in NOT_UTF8_ARGV:
            for extra in ([], ["--general"]):
                with self.subTest(arg=arg, extra=extra):
                    r = self.run_hg(["ask", "--notes-only", *extra, arg])
                    self.assertRefused(r, before, arg)

    def test_note_add_unreadable_stdin_is_refused_exit_2(self):
        before = self.ledgers()
        for data in UNREADABLE:
            for extra in ([], ["--subject", "hop"]):
                with self.subTest(data=data[:24], extra=extra):
                    r = self.run_hg(["note", "add", *extra], stdin=data)
                    self.assertRefused(r, before, data[:24])

    def test_note_add_argv_not_utf8_is_refused_exit_2(self):
        before = self.ledgers()
        for arg in NOT_UTF8_ARGV:
            with self.subTest(arg=arg):
                r = self.run_hg(["note", "add", arg])
                self.assertRefused(r, before, arg)

    def test_blank_input_is_refused_exit_2(self):
        before = self.ledgers()
        for argv, data in ((["ask"], b""), (["ask"], b" \n\t\n"), (["ask", "  "], b""),
                           (["note", "add"], b""), (["note", "add"], b"\n\n"), (["note", "add", " "], b"")):
            with self.subTest(argv=argv, data=data):
                r = self.run_hg(argv, stdin=data)
                self.assertRefused(r, before, (argv, data))

    # Controls: genuine input is still accepted, from stdin and argv.

    def test_controls_genuine_input_is_accepted(self):
        r = self.run_hg(["ask", "--notes-only"], stdin=QUESTION.encode() + b"\r\n")
        self.assertIn(r.returncode, (0, 3), r.stdout + r.stderr)
        self.assertIn(NOTE.encode(), r.stdout)
        r = self.run_hg(["ask", "--notes-only", "--json", QUESTION])
        self.assertIn(r.returncode, (0, 3), r.stdout + r.stderr)
        receipts = [p for p in self.home.iterdir() if p.name.startswith("asks-")]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(len(receipts[0].read_bytes().splitlines()), 3)
        r = self.run_hg(["note", "add"], stdin="Thay dầu xe ngày 2026-09-15\r\nở tiệm cũ\n".encode())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_hg(["note", "add", "Gia hạn bảo hiểm xe tháng 3"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        listed = self.run_hg(["note", "list"]).stdout.decode()
        self.assertIn("Thay dầu xe ngày 2026-09-15", listed)
        self.assertIn("Gia hạn bảo hiểm xe tháng 3", listed)
        # 1 MB exactly passes the input rule; the note's own 4000-character limit still applies (exit 2).
        r = self.run_hg(["note", "add"], stdin=b"a" * 1_000_000)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(b"4000", r.stdout)


if __name__ == "__main__":
    unittest.main()
