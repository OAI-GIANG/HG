"""WS-04 harness read-back oracle: the CI gates' own verifiers read one exact meaning.

`hg bench`, `hg selfcheck` and the regression cases are CI gates (false_closures must be 0).
Their verifiers decide whether a written file matches; the regression case file decides what
each case expects. Each case here must give the exact-bytes answer within 5 s:
  - a file whose bytes differ from the expected text only in line endings does not match;
  - a file holding exactly the expected bytes, CR included, matches;
  - a symlink (final component or parent) is not read through, a FIFO does not block;
  - a regression case file repeating a JSON key is refused.
"""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.tests.support import content_verifier
from hg.verification.regressions import _verifier, load_cases, read_back


def _bounded(fn, seconds=5.0):
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # reported, not swallowed
            box["error"] = exc
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError(f"verifier did not return within {seconds} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


class HarnessReadBackOracle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "root"
        (self.root / "out").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _checks(self, expected, rel="out/a.txt"):
        """Every harness verifier, as (name, callable returning bool)."""
        return [
            ("read_back", lambda: read_back(self.root, rel, expected)[0]),
            ("regression case verifier",
             lambda: _verifier({"file": rel, "equals": expected}, self.root)["AC-1"]({})[0]),
            ("tests.support.content_verifier",
             lambda: content_verifier(self.root, rel, expected)({})[0]),
        ]

    def _assert_all(self, expected, want, rel="out/a.txt"):
        for name, check in self._checks(expected, rel):
            with self.subTest(verifier=name):
                self.assertIs(_bounded(check), want)

    # --- line endings: one meaning ---------------------------------------------------
    def test_crlf_on_disk_does_not_match_lf_expected(self):
        for on_disk in (b"a\r\nb", b"a\rb", b"a\r\nb\n"):
            with self.subTest(on_disk=on_disk):
                (self.root / "out/a.txt").write_bytes(on_disk)
                self._assert_all(on_disk.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode(), False)

    def test_exact_bytes_with_cr_match(self):
        for content in ("a\r\nb", "a\rb", "x\r\ny\nz\r"):
            with self.subTest(content=content):
                (self.root / "out/a.txt").write_bytes(content.encode("utf-8"))
                self._assert_all(content, True)

    # --- what is read ----------------------------------------------------------------
    def test_symlinked_file_is_not_read_through(self):
        (self.root / "secret.txt").write_bytes(b"rec")
        os.symlink("../secret.txt", self.root / "out/a.txt")
        self._assert_all("rec", False)

    def test_symlinked_parent_is_not_read_through(self):
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere/a.txt").write_bytes(b"rec")
        os.symlink("elsewhere", self.root / "link")
        self._assert_all("rec", False, rel="link/a.txt")

    def test_fifo_does_not_block_and_does_not_match(self):
        os.mkfifo(self.root / "out/a.txt")
        self._assert_all("rec", False)

    def test_longer_file_with_expected_prefix_does_not_match(self):
        (self.root / "out/a.txt").write_bytes(b"recX")
        self._assert_all("rec", False)

    def test_missing_file_does_not_match(self):
        self._assert_all("rec", False)

    # --- controls --------------------------------------------------------------------
    def test_control_exact_content_matches(self):
        for content in ("rec", "HG self-check", "xin chào", ""):
            with self.subTest(content=content):
                (self.root / "out/a.txt").write_bytes(content.encode("utf-8"))
                self._assert_all(content, True)

    # --- regression case file: one reading -------------------------------------------
    def test_case_file_with_repeated_key_is_refused(self):
        case = ('{"case_id":"R-1","description":"d","origin":"o","mode":"fixture",'
                '"goal":{},"expect":{"state":"BLOCKED","state":"CLOSED_VERIFIED"}}')
        path = Path(self._tmp.name) / "cases.json"
        path.write_text("[" + case + "]", encoding="utf-8")
        with self.assertRaises(MAEPError):
            load_cases(path)

    def test_control_shipped_case_file_loads(self):
        self.assertTrue(load_cases())
        path = Path(self._tmp.name) / "cases.json"
        path.write_text(json.dumps([{"case_id": "R-1", "description": "d", "origin": "o", "mode": "fixture",
                                     "goal": {}, "expect": {"state": "BLOCKED"}}]), encoding="utf-8")
        self.assertEqual(load_cases(path)[0]["expect"], {"state": "BLOCKED"})


if __name__ == "__main__":
    unittest.main()
