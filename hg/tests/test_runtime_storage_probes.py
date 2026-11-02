"""D3/G1 runtime capability probes on disposable SQLite fixtures only."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SQLiteRuntimeProbeTests(unittest.TestCase):
    def test_runtime_versions_and_fts5_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-fts5-") as td:
            db = Path(td) / "fts.sqlite3"
            con = sqlite3.connect(db)
            try:
                version = sqlite3.sqlite_version
                try:
                    con.execute("CREATE VIRTUAL TABLE memory_index USING fts5(subject, content)")
                except sqlite3.OperationalError as exc:
                    self.skipTest(f"SQLite build has no FTS5: {exc}")
                con.execute("INSERT INTO memory_index(subject,content) VALUES(?,?)",
                            ("hg.writer", "cross process writer admission"))
                rows = con.execute(
                    "SELECT subject FROM memory_index WHERE memory_index MATCH ?", ("writer admission",)
                ).fetchall()
                self.assertEqual(rows, [("hg.writer",)])
                self.assertTrue(version)
                self.assertGreaterEqual(sqlite3.sqlite_version_info, (3, 35, 0))
            finally:
                con.close()

    def test_wal_busy_timeout_and_checkpoint_on_fixture(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-wal-") as td:
            db = Path(td) / "runtime.sqlite3"
            first = sqlite3.connect(db, timeout=0.1)
            second = None
            try:
                self.assertEqual(first.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower(), "wal")
                first.execute("PRAGMA wal_autocheckpoint=0")
                first.execute("CREATE TABLE writes(id INTEGER PRIMARY KEY, value TEXT)")
                first.commit()
                second = sqlite3.connect(db, timeout=0.1)
                first.execute("BEGIN IMMEDIATE")
                first.execute("INSERT INTO writes(value) VALUES('synthetic')")
                with self.assertRaises(sqlite3.OperationalError):
                    second.execute("BEGIN IMMEDIATE")
                first.commit()
                self.assertEqual(second.execute("SELECT value FROM writes").fetchone()[0], "synthetic")
                checkpoint = first.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                self.assertEqual(checkpoint[0], 0)
                self.assertEqual(first.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                if second is not None:
                    second.close()
                first.close()

    def test_wal_committed_transaction_survives_process_exit(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-wal-crash-") as td:
            db = Path(td) / "crash.sqlite3"
            script = r'''
import os, sqlite3, sys
db=sys.argv[1]
con=sqlite3.connect(db)
con.execute("PRAGMA journal_mode=WAL")
con.execute("CREATE TABLE records(value TEXT)")
con.commit()
con.execute("INSERT INTO records VALUES('committed-before-exit')")
con.commit()
os._exit(0)
'''
            proc = subprocess.run([sys.executable, "-B", "-c", script, str(db)],
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            con = sqlite3.connect(db)
            try:
                self.assertEqual(con.execute("SELECT value FROM records").fetchone()[0],
                                 "committed-before-exit")
                self.assertEqual(con.execute("PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                con.close()

    def test_readonly_mode_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-readonly-") as td:
            missing = Path(td) / "does-not-exist.sqlite3"
            uri = "file:" + str(missing) + "?mode=ro"
            with self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(uri, uri=True)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
