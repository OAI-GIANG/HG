"""Oracle: assistant counts and search queries mean what they say (WS-04).

Before this oracle, on main 6035359 with one active note "Mật khẩu wifi nhà là 1234":

- `hg note list --limit 0` and `--limit -1` printed "Chưa có ghi chú nào" (no notes yet, exit 0);
  with N notes `--limit -1` silently dropped the oldest one (Python slice `[:-1]`).
- `hg note search wifi --limit 0` / `--limit -3` printed "Không tìm thấy ghi chú nào" (exit 5,
  NO_DATA) although the note matches; `--json` printed `[]`.
- `hg summarize FILE --max-sentences 0` said the text was too short (exit 5);
  `--max-sentences -1` silently dropped the last sentence.
- `hg note search` with a blank query reported "not found" (exit 5) instead of bad input, and a
  query whose bytes are not UTF-8 was searched mangled (exit 0 with a hit).

Oracle: the exit-code table (2 = bad input, 5 = nothing found), the notebook itself (what
`note list --all` and an unlimited search return), and the `_read_text` input rules that
`hg ask` / `hg check` / `hg note add` already apply.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTES = ["Mật khẩu wifi nhà là 1234", "Họp với Lan lúc 9 giờ thứ Hai", "Mua sữa cho mẹ chiều thứ Bảy"]
TEXT = "Hôm nay trời mưa rất to ở Hà Nội.\nNgày mai dự báo nắng nhẹ và ấm áp.\nCuối tuần gió mùa đông bắc tràn về.\n"
BAD_COUNTS = ["0", "-1", "-3", "1.5", "abc", "", "True"]


class CountQueryOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp())
        os.chmod(cls.home, 0o700)
        for note in NOTES:
            r = cls.run_hg(["note", "add", note])
            assert r.returncode == 0, r.stdout + r.stderr
        cls.text = cls.home / "in.txt"
        cls.text.write_text(TEXT, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    @classmethod
    def run_hg(cls, argv):
        env = dict(os.environ, HG_HOME=str(cls.home / "h"), NO_COLOR="1", PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, input=b"",
                              capture_output=True, timeout=60)

    def ledgers(self):
        h = self.home / "h"
        return {p.name: p.read_bytes() for p in sorted(h.iterdir()) if p.suffix == ".jsonl"}

    def assert_refused(self, argv, before):
        r = self.run_hg(argv)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        self.assertEqual(r.returncode, 2, f"{argv}: {out}")
        self.assertNotIn("Traceback", out)
        self.assertNotIn("Chưa có ghi chú nào", out)
        self.assertNotIn("Không tìm thấy", out)
        self.assertNotIn("quá ngắn", out)
        self.assertEqual(self.ledgers(), before)

    def test_unusable_counts_refused(self):
        before = self.ledgers()
        for value in BAD_COUNTS:
            with self.subTest(value=value):
                self.assert_refused(["note", "list", "--limit", value], before)
                self.assert_refused(["note", "list", "--all", "--limit", value], before)
                self.assert_refused(["note", "search", "wifi", "--limit", value], before)
                self.assert_refused(["note", "search", "wifi", "--json", "--limit", value], before)
                self.assert_refused(["summarize", str(self.text), "--max-sentences", value], before)

    def test_unusable_queries_refused(self):
        before = self.ledgers()
        for query in ["", "   ", "\t"]:
            with self.subTest(query=query):
                self.assert_refused(["note", "search", query], before)
        for raw in [b"wifi\xff", b"\xff\xfe", "Mật khẩu".encode() + b"\xe1\xbb"]:
            with self.subTest(raw=raw):
                self.assert_refused(["note", "search", os.fsdecode(raw)], before)

    def test_controls(self):
        r = self.run_hg(["note", "list"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(sum(1 for line in r.stdout.decode().splitlines() if line.startswith("M-")), 3)
        for n, expect in [("1", 1), ("2", 2), ("3", 3), ("50", 3)]:
            with self.subTest(limit=n):
                r = self.run_hg(["note", "list", "--limit", n])
                self.assertEqual(r.returncode, 0)
                lines = [l for l in r.stdout.decode().splitlines() if l.startswith("M-")]
                self.assertEqual(len(lines), expect)
        r = self.run_hg(["note", "list", "--limit", "1"])
        self.assertIn(NOTES[-1], r.stdout.decode())          # newest first
        for n in ["1", "5"]:
            r = self.run_hg(["note", "search", "wifi", "--limit", n])
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("wifi", r.stdout.decode())
        r = self.run_hg(["note", "search", "khong", "co", "dau", "xyzzy"])
        self.assertEqual(r.returncode, 5)                      # a usable query that matches nothing
        for n, expect in [("1", 1), ("2", 2), ("3", 3)]:
            r = self.run_hg(["summarize", str(self.text), "--max-sentences", n])
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(sum(1 for l in r.stdout.decode().splitlines() if l.startswith("•")), expect)


class LibraryCounts(unittest.TestCase):
    def test_library_refuses_unusable_counts(self):
        from hg.assistant import summarize as sm
        from hg.assistant.notes import NoteError, Notebook
        home = Path(tempfile.mkdtemp())
        try:
            os.chmod(home, 0o700)
            nb = Notebook(home / "h")
            nb.add(NOTES[0])
            self.assertEqual(len(nb.search("wifi", limit=1)), 1)
            for bad in [0, -1, 1.5, True, "2", None]:
                with self.subTest(bad=bad):
                    with self.assertRaises(NoteError):
                        nb.search("wifi", limit=bad)
                    with self.assertRaises(ValueError):
                        sm.extractive(TEXT, max_sentences=bad)
            self.assertEqual(len(sm.extractive(TEXT, max_sentences=2)), 2)
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
