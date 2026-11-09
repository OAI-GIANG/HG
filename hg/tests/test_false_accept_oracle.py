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
