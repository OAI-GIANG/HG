"""Regression tests for the fail-closed SQLite opener (path-swap / TOCTOU).

Each test models a concrete race or misconfiguration at the boundary between
HG's path checks and SQLite's own name-based opens of the database, -journal,
-wal and -shm files.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from maep import sqlite_nofollow as sn

_LOCK_PROBE = r"""
import sqlite3, sys
c = sqlite3.connect(sys.argv[1], timeout=0, isolation_level=None)
try:
    c.execute("PRAGMA locking_mode=EXCLUSIVE")
    c.execute("BEGIN EXCLUSIVE")
    print("ACQUIRED")
    c.execute("ROLLBACK")
except sqlite3.OperationalError:
    print("BLOCKED")
"""


def _make_db(path: Path, table: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table}(v TEXT)")
    conn.commit()
    conn.close()
    os.chmod(path, 0o600)


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


class SQLiteNoFollowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hg-sqlite-nofollow-")
        self.root = Path(self._tmp.name)
        self.target = self.root / "ledger.sqlite3"

    def tearDown(self):
        self._tmp.cleanup()

    def test_procfs_deleted_alias_cannot_redirect_open(self):
        """SQLite resolves /proc/self/fd/N by readlink; '<path> (deleted)' must not win."""
        _make_db(self.target, "canonical")
        evil = Path(str(self.target) + " (deleted)")
        real_connect = sqlite3.connect
        fired = []

        def racing_connect(database, *args, **kwargs):
            if not fired:
                fired.append(database)
                hidden = self.root / "hidden"
                os.link(self.target, hidden)      # same inode, new dentry
                os.unlink(self.target)            # opener's dentry is now "(deleted)"
                os.rename(hidden, self.target)    # canonical name still names the same inode
                _make_db(evil, "evil")
            return real_connect(database, *args, **kwargs)

        with patch.object(sqlite3, "connect", side_effect=racing_connect):
            try:
                conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
            except OSError:
                conn = None
        self.assertTrue(fired)
        if conn is not None:
            try:
                conn.execute("INSERT INTO canonical VALUES('kept')")
            finally:
                conn.close()
            conn = real_connect(self.target)
            self.assertEqual(conn.execute("SELECT v FROM canonical").fetchall(), [("kept",)])
            conn.close()
        self.assertEqual(_tables(evil), {"evil"})

    def test_open_does_not_release_other_connections_posix_locks(self):
        """Opening/closing a private fd on the DB drops this process's fcntl locks."""
        for journal_mode in ("delete", "wal"):
            with self.subTest(journal_mode=journal_mode):
                if self.target.exists():
                    for suffix in ("", "-wal", "-shm", "-journal"):
                        Path(str(self.target) + suffix).unlink(missing_ok=True)
                writer = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
                try:
                    writer.execute(f"PRAGMA journal_mode={journal_mode}")
                    writer.execute("CREATE TABLE IF NOT EXISTS t(v)")
                    writer.execute("BEGIN IMMEDIATE")
                    writer.execute("INSERT INTO t VALUES(1)")
                    second = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
                    second.close()
                    probe = subprocess.run([sys.executable, "-c", _LOCK_PROBE, str(self.target)],
                                           capture_output=True, text=True, timeout=60)
                    self.assertEqual(probe.stdout.strip(), "BLOCKED", probe.stderr)
                    writer.execute("ROLLBACK")
                finally:
                    writer.close()

    def test_rejects_symlink_in_parent_directory(self):
        real = self.root / "real"
        real.mkdir(mode=0o700)
        (self.root / "link").symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, self.root / "link" / "ledger.sqlite3")
        self.assertEqual(list(real.iterdir()), [])

    def test_rejects_world_writable_database_directory(self):
        shared = self.root / "shared"
        shared.mkdir()
        os.chmod(shared, 0o777)
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, shared / "ledger.sqlite3")
        self.assertEqual(list(shared.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root to chown")
    def test_rejects_directory_owned_by_another_user(self):
        foreign = self.root / "foreign"
        foreign.mkdir(mode=0o700)
        os.chown(foreign, 54321, 54321)
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, foreign / "ledger.sqlite3")
        self.assertEqual(list(foreign.iterdir()), [])

    def test_rejects_symlinked_or_hardlinked_sidecars_without_touching_target(self):
        victim = self.root / "victim.bin"
        for suffix in ("-journal", "-wal", "-shm"):
            for kind in ("symlink", "hardlink"):
                with self.subTest(suffix=suffix, kind=kind):
                    victim.write_bytes(b"VICTIM-DATA" * 64)
                    if not self.target.exists():
                        _make_db(self.target, "t")
                    side = Path(str(self.target) + suffix)
                    if kind == "symlink":
                        side.symlink_to(victim)
                    else:
                        os.link(victim, side)
                    try:
                        with self.assertRaises(OSError):
                            conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
                            try:
                                conn.execute("BEGIN IMMEDIATE")
                                conn.execute("INSERT INTO t VALUES('x')")
                                conn.commit()
                                conn.execute("SELECT count(*) FROM t").fetchone()
                            finally:
                                conn.close()
                        self.assertEqual(victim.read_bytes(), b"VICTIM-DATA" * 64)
                    finally:
                        side.unlink(missing_ok=True)

    def test_rejects_hardlinked_database(self):
        _make_db(self.target, "t")
        os.link(self.target, self.root / "alias.sqlite3")
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, self.target)

    def test_commit_refuses_after_database_replaced(self):
        _make_db(self.target, "t")
        conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
        displaced = self.root / "displaced.sqlite3"
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES('lost?')")
            os.rename(self.target, displaced)
            _make_db(self.target, "t")
            with self.assertRaises(OSError):
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        for path in (self.target, displaced):
            c = sqlite3.connect(path)
            self.assertEqual(c.execute("SELECT count(*) FROM t").fetchone()[0], 0, path)
            c.close()

    def test_commit_never_acknowledges_swap_racing_the_commit(self):
        check = getattr(sn, "_check_binding", None)
        self.assertIsNotNone(check, "opener has no binding verification")
        for journal_mode in ("delete", "wal"):
            with self.subTest(journal_mode=journal_mode):
                for suffix in ("", "-wal", "-shm", "-journal"):
                    Path(str(self.target) + suffix).unlink(missing_ok=True)
                _make_db(self.target, "t")
                conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
                calls = []

                def swap_after_precommit_check(binding):
                    check(binding)
                    calls.append(1)
                    if len(calls) == 1:  # pre-commit check passed; swap before SQLite commits
                        os.replace(self.target, self.root / f"displaced-{journal_mode}.sqlite3")
                        _make_db(self.target, "t")

                try:
                    conn.execute(f"PRAGMA journal_mode={journal_mode}")
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO t VALUES('raced')")
                    with patch.object(sn, "_check_binding", side_effect=swap_after_precommit_check):
                        with self.assertRaises((OSError, sqlite3.Error)):
                            conn.commit()
                    self.assertTrue(calls)
                finally:
                    conn.close()
                if journal_mode == "delete":
                    c = sqlite3.connect(self.target)
                    self.assertEqual(c.execute("SELECT count(*) FROM t").fetchone()[0], 0)
                    c.close()
                # WAL: SQLite skips the close-time checkpoint for a moved database, so the
                # displaced database's frames stay at "<path>-wal" and SQLite will replay
                # them into whatever database is at the path. That same-user residual is
                # documented in maep/sqlite_nofollow.py; this test pins that the commit
                # itself is never acknowledged.

    def test_fails_closed_without_openat_support(self):
        with patch.object(os, "supports_dir_fd", set()):
            with self.assertRaises(OSError):
                sn.connect_nofollow(sqlite3, self.target)
        self.assertFalse(self.target.exists())

    def test_rejects_unnormalized_path(self):
        (self.root / "sub").mkdir(mode=0o700)
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, str(self.root / "sub" / ".." / "ledger.sqlite3"))

    def test_private_mode_creates_0600_and_rejects_group_readable(self):
        conn = sn.connect_nofollow(sqlite3, self.target, private=True)
        conn.close()
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        os.chmod(self.target, 0o640)
        with self.assertRaises(OSError):
            sn.connect_nofollow(sqlite3, self.target, private=True)

    def test_normal_open_round_trip_and_special_characters(self):
        odd = self.root / "dir ?#%"
        odd.mkdir(mode=0o700)
        path = odd / "ledger ?#%.sqlite3"
        conn = sn.connect_nofollow(sqlite3, path, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE t(v)")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES('ok')")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(sorted(p.name for p in odd.iterdir()), ["ledger ?#%.sqlite3"])
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT v FROM t").fetchall(), [("ok",)])
        c.close()


if __name__ == "__main__":
    unittest.main()
