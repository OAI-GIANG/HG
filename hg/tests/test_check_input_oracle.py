"""Oracle: `hg check` compares only text it can read as written, and never reports a silent OK (WS-04).

The documented contract (docs/HG_V1_GUIDE.md §4, §6): `hg check` holds a message against the
owner's notes; exit 4 means a sentence conflicts with a note, 0 means it was checked, 2 means the
input is unusable, 5 means nothing was found. Before this oracle `hg check` read stdin with no
rules: an empty or blank message exited 0 with no output (a script reads that as "no conflict");
bytes that are not UTF-8 were silently replaced, so a message in another encoding was compared as
mangled text and exited 0; NUL bytes were accepted; the size was unbounded. `hg summarize -`
already refuses all of these (1 MB, no NUL, UTF-8 only).

Oracle: the input rules `summarize.read_input` already enforces, the exit-code table, and
`grounding.summarize` (`claims` = sentences actually compared).
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


class CheckInputOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp())
        os.chmod(cls.home, 0o700)
        r = cls.run_hg(["note", "add", NOTE])
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    @classmethod
    def run_hg(cls, argv, stdin=b""):
        env = dict(os.environ, HG_HOME=str(cls.home), NO_COLOR="1", PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, input=stdin,
                              capture_output=True, timeout=60)

    def assertRefused(self, r, code, case):
        self.assertEqual(r.returncode, code, f"{case!r}: {r.stdout[:200]!r} {r.stderr[-300:]!r}")
        self.assertNotIn(b"Traceback", r.stderr, case)
        self.assertNotIn("[KHỚP]".encode(), r.stdout, case)
        self.assertNotIn("[CHƯA RÕ]".encode(), r.stdout, case)
        self.assertTrue(r.stdout.strip(), f"{case!r}: refusal must say why")

    def test_unreadable_stdin_is_refused_exit_2(self):
        conflict = "Họp với Lan lúc 10 giờ thứ Hai".encode()
        cases = [
            b"\xff\xfe abc",                                   # not UTF-8
            "Họp với Lan lúc 10 giờ".encode("utf-16"),         # other encoding
            "Hop voi Lan luc 10 gio".encode() + b"\xe1\xbb",   # truncated multibyte
            conflict + b"\x00 xyz",                            # NUL byte
            b"\x00",
            b"a" * 1_000_001,                                  # over 1 MB
        ]
        for data in cases:
            with self.subTest(data=data[:40]):
                self.assertRefused(self.run_hg(["check"], data), 2, data[:40])
                self.assertRefused(self.run_hg(["check", "--json"], data), 2, data[:40])

    def test_blank_input_is_refused_exit_2(self):
        for data in [b"", b"   ", b"\n\n", b"\t \r\n", "　".encode()]:
            with self.subTest(data=data):
                self.assertRefused(self.run_hg(["check"], data), 2, data)
        for argv in [["check", ""], ["check", "  ", " "]]:
            with self.subTest(argv=argv):
                self.assertRefused(self.run_hg(argv), 2, argv)

    def test_nothing_compared_is_exit_5_not_ok(self):
        for data in ["...".encode(), "?!".encode()]:
            with self.subTest(data=data):
                r = self.run_hg(["check"], data)
                self.assertEqual(r.returncode, 5, f"{data!r}: {r.stdout[:200]!r}")
                self.assertNotIn(b"Traceback", r.stderr)

    # controls: usable input behaves as before
    def test_controls(self):
        r = self.run_hg(["check"], "Họp với Lan lúc 10 giờ thứ Hai".encode())
        self.assertEqual(r.returncode, 4, r.stdout[:200])
        self.assertIn("[MÂU THUẪN]".encode(), r.stdout)
        r = self.run_hg(["check"], (NOTE + "\n").encode())
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        self.assertIn("[KHỚP]".encode(), r.stdout)
        r = self.run_hg(["check", "Họp", "với", "Lan", "lúc", "10", "giờ"])
        self.assertEqual(r.returncode, 4, r.stdout[:200])
        r = self.run_hg(["check"], "Trời hôm nay đẹp quá.".encode())
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        self.assertIn("[CHƯA RÕ]".encode(), r.stdout)
        r = self.run_hg(["check"], ("Hop voi Lan luc 9 gio thu Hai. " * 33000)[:1_000_000].encode())  # exactly 1 MB
        self.assertIn(r.returncode, (0, 4), r.stderr[-300:])
        self.assertNotIn(b"Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
