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


if __name__ == "__main__":
    unittest.main()
