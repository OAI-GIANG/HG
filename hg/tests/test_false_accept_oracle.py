"""False-accept oracle for the independent-process verifier (WS-04).

Each case builds a candidate that is known to be bad by construction, so the expected
outcome comes from how the input was made, not from the verifier under test. The oracle
asserts that no such candidate is reported as PASS. Controls show that well-formed
candidates still pass, so the oracle cannot be satisfied by a verifier that rejects
everything.
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.verification.independent import IndependentVerifier


def _valid_db(path):
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
        db.executemany("INSERT INTO t(v) VALUES (?)", [("x" * 200,) for _ in range(200)])
        db.commit()
    finally:
        db.close()


class FalseAcceptOracleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.verifier = IndependentVerifier()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    # -- controls -------------------------------------------------------------------
    def test_control_valid_candidates_pass(self):
        self._write("ok.py", b"x = 1\n")
        _valid_db(self.root / "ok.sqlite3")
        digest = hashlib.sha256(b"x = 1\n").hexdigest()
        py = self.verifier.verify_python_syntax(self.root, "ok.py", candidate_ref="ctl",
                                                expected_sha256=digest)
        db = self.verifier.verify_sqlite_integrity(self.root, "ok.sqlite3", candidate_ref="ctl")
        self.assertEqual(py["status"], "PASS", py)
        self.assertEqual(db["status"], "PASS", db)

    # -- python candidates ------------------------------------------------------------
    def test_bad_python_candidates_are_never_passed(self):
        good = b"x = 1\n"
        self._write("good.py", good)
        self._write("syntax.py", b"def f(:\n")
        self._write("latin1.py", b"x = '\xff'\n")
        self._write("nul.py", b"x = 1\x00\n")
        (self.root / "dir.py").mkdir()
        os.symlink(self.root / "good.py", self.root / "link.py")
        cases = [
            ("syntax error", "syntax.py", None),
            ("not utf-8", "latin1.py", None),
            ("null byte", "nul.py", None),
            ("directory", "dir.py", None),
            ("symlink", "link.py", None),
            ("traversal", "../good.py", None),
            ("absolute path", str(self.root / "good.py"), None),
            ("missing", "missing.py", None),
            ("hash mismatch", "good.py", hashlib.sha256(b"y = 2\n").hexdigest()),
        ]
        for label, rel, expected in cases:
            with self.subTest(label):
                report = self.verifier.verify_python_syntax(
                    self.root, rel, candidate_ref="bad", expected_sha256=expected)
                self.assertNotEqual(report["status"], "PASS", report)

    # -- python source-encoding candidates ----------------------------------------------
    # The interpreter decodes a source file by its BOM and PEP 263 coding declaration.
    # A verifier that decodes the bytes itself and compiles the resulting text ignores
    # the declaration, so it can attest files the interpreter refuses to load. Ground
    # truth for each case is the interpreter itself, run on the same bytes.
    _UNLOADABLE = {
        "unknown_cookie.py": b"# coding: nonexistent-hg-codec\nx = 1\n",
        "utf16_cookie.py": b"# coding: utf-16\nx = 1\n",
        "rot13_cookie.py": b"# coding: rot13\nx = 1\n",
        "bom_latin1_cookie.py": b"\xef\xbb\xbf# coding: latin-1\nx = 1\n",
    }

    def _interpreter_accepts(self, name):
        result = subprocess.run([sys.executable, "-I", "-B", "-c",
                                 "import sys; compile(open(sys.argv[1], 'rb').read(), "
                                 "sys.argv[1], 'exec', dont_inherit=True)",
                                 str(self.root / name)],
                                capture_output=True, timeout=30)
        return result.returncode == 0

    def test_sources_the_interpreter_cannot_load_are_never_passed(self):
        for name, data in self._UNLOADABLE.items():
            self._write(name, data)
            with self.subTest(name):
                self.assertFalse(self._interpreter_accepts(name), "case is not bad by construction")
                report = self.verifier.verify_python_syntax(self.root, name, candidate_ref="enc")
                self.assertNotEqual(report["status"], "PASS", report)

    def test_control_utf8_bom_source_passes(self):
        # A UTF-8 BOM is valid Python source; rejecting it is a false reject.
        data = b"\xef\xbb\xbfx = 1\n"
        self._write("bom.py", data)
        self.assertTrue(self._interpreter_accepts("bom.py"))
        report = self.verifier.verify_python_syntax(
            self.root, "bom.py", candidate_ref="bom",
            expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(report["status"], "PASS", report)

    def test_non_utf8_source_stays_rejected_even_with_a_declaration(self):
        # Policy: verified sources are UTF-8. A latin-1 declaration does not widen it.
        self._write("latin1_declared.py", b"# coding: latin-1\nx = '\xe9'\n")
        report = self.verifier.verify_python_syntax(self.root, "latin1_declared.py",
                                                    candidate_ref="l1")
        self.assertEqual(report["status"], "FAIL", report)
        self.assertEqual(report["reason"], "source is not valid UTF-8")

    # -- sqlite candidates ------------------------------------------------------------
    def test_bad_sqlite_candidates_are_never_passed(self):
        _valid_db(self.root / "good.sqlite3")
        whole = (self.root / "good.sqlite3").read_bytes()
        self.assertGreater(len(whole), 8192)
        self._write("empty.sqlite3", b"")
        self._write("header_only.sqlite3", whole[:100])
        self._write("short_header.sqlite3", whole[:50])
        self._write("half.sqlite3", whole[: len(whole) // 2])
        self._write("garbage.sqlite3", os.urandom(4096))
        wrong_magic = bytearray(whole)
        wrong_magic[0:16] = b"SQLite format 2\x00"
        self._write("wrong_magic.sqlite3", bytes(wrong_magic))
        _valid_db(self.root / "wal.sqlite3")
        self._write("wal.sqlite3-wal", b"pending")
        os.symlink(self.root / "good.sqlite3", self.root / "link.sqlite3")
        cases = [
            "empty.sqlite3", "header_only.sqlite3", "short_header.sqlite3", "half.sqlite3",
            "garbage.sqlite3", "wrong_magic.sqlite3", "wal.sqlite3", "link.sqlite3",
        ]
        for rel in cases:
            with self.subTest(rel):
                report = self.verifier.verify_sqlite_integrity(self.root, rel, candidate_ref="bad")
                self.assertNotEqual(report["status"], "PASS", report)

    def test_altered_sqlite_snapshot_is_not_passed_against_its_expected_digest(self):
        # integrity_check verifies b-tree structure, not row content: a snapshot whose
        # payload bytes were altered, or that gained trailing bytes, is still "ok".
        # Only a binding to the expected content digest can reject it.
        _valid_db(self.root / "good.sqlite3")
        whole = (self.root / "good.sqlite3").read_bytes()
        expected = hashlib.sha256(whole).hexdigest()
        flipped = bytearray(whole)
        at = flipped.rfind(b"x" * 50)
        self.assertGreater(at, 100)
        flipped[at] = ord("y")
        self._write("flipped.sqlite3", bytes(flipped))
        self._write("trailing.sqlite3", whole + b"\x00" * 4096)
        for rel in ("flipped.sqlite3", "trailing.sqlite3"):
            with self.subTest(rel):
                report = self.verifier.verify_sqlite_integrity(
                    self.root, rel, candidate_ref="alt", expected_sha256=expected)
                self.assertNotEqual(report["status"], "PASS", report)
                self.assertNotEqual(report.get("sha256"), expected, report)

    def test_control_sqlite_snapshot_reports_and_matches_its_digest(self):
        _valid_db(self.root / "good.sqlite3")
        expected = hashlib.sha256((self.root / "good.sqlite3").read_bytes()).hexdigest()
        report = self.verifier.verify_sqlite_integrity(
            self.root, "good.sqlite3", candidate_ref="ctl", expected_sha256=expected)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["sha256"], expected, report)

    def test_empty_file_is_not_reported_as_a_database_snapshot(self):
        # SQLite opens a zero-byte file as an empty database whose integrity_check is
        # "ok". A snapshot that lost every byte must not be attested as intact.
        self._write("empty.sqlite3", b"")
        report = self.verifier.verify_sqlite_integrity(self.root, "empty.sqlite3", candidate_ref="e")
        self.assertEqual(report["status"], "BLOCKED", report)
        self.assertIn("not a SQLite database file", report["reason"])
        self.assertEqual((self.root / "empty.sqlite3").read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
