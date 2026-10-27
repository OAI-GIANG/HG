"""Security integration tests for the HTTP idempotency SQLite binding."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hg.http_api import IdempotencyStore


class IdempotencySQLiteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-http-idem-security-")
        self.root = Path(self.tmp.name)
        self.db = self.root / "idempotency.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_uses_bound_connection_and_wal(self):
        store = IdempotencyStore(self.db)
        try:
            self.assertTrue(hasattr(store._db, "verify_binding"))
            self.assertEqual(store._db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            state, response = store.begin("key-1", "digest-1")
            self.assertEqual((state, response), ("NEW", None))
            store.finish("key-1", {"ok": True})
            self.assertEqual(store.begin("key-1", "digest-1"), ("REPLAY", {"ok": True}))
            store._db.verify_binding()
        finally:
            store.close()

    def test_store_rejects_symlink_database_path(self):
        real = self.root / "real.sqlite3"
        sqlite3.connect(real).close()
        link = self.root / "linked.sqlite3"
        link.symlink_to(real)
        with self.assertRaises(OSError):
            IdempotencyStore(link)

    def test_commit_fails_if_database_inode_is_replaced(self):
        store = IdempotencyStore(self.db)
        try:
            store._db.execute("BEGIN IMMEDIATE")
            store._db.execute("INSERT INTO requests(idem_key,digest,state) VALUES('x','d','STARTED')")
            displaced = self.root / "displaced.sqlite3"
            os.replace(self.db, displaced)
            sqlite3.connect(self.db).close()
            with self.assertRaises(OSError):
                store._db.commit()
        finally:
            store.close()

    def test_reopen_after_replacement_keeps_each_receipt_in_its_own_database(self):
        """The displaced store's WAL frames must never be replayed into the database now at the path."""
        displaced = self.root / "displaced.sqlite3"
        store = IdempotencyStore(self.db)
        try:
            store.begin("key-A", "digest-A")  # committed frames now live in "<db>-wal"
            os.replace(self.db, displaced)
            staging = self.root / "staging.sqlite3"
            replacement = sqlite3.connect(staging)
            replacement.execute("CREATE TABLE marker(v TEXT)")
            replacement.execute("INSERT INTO marker VALUES('B')")
            replacement.commit()
            replacement.close()
            os.chmod(staging, 0o600)
            os.replace(staging, self.db)
        finally:
            store.close()

        def file_tables(path):
            inspect = self.root / f"inspect-{path.name}"
            inspect.mkdir(mode=0o700)
            copy = inspect / "copy.sqlite3"
            copy.write_bytes(path.read_bytes())
            conn = sqlite3.connect(copy)
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                keys = [r[0] for r in conn.execute("SELECT idem_key FROM requests")] if "requests" in tables else None
                return tables, keys
            finally:
                conn.close()

        self.assertEqual(file_tables(displaced), ({"requests"}, ["key-A"]))
        self.assertEqual(file_tables(self.db), ({"marker"}, None))
        reopened = IdempotencyStore(self.db)
        try:
            self.assertEqual(reopened.begin("key-A", "digest-A"), ("NEW", None))
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
