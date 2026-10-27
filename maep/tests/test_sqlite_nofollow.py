"""Regression tests for the fail-closed SQLite opener (path-swap / TOCTOU).

Each test models a concrete race or misconfiguration at the boundary between
HG's path checks and SQLite's own name-based opens of the database, -journal,
-wal and -shm files.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from maep import sqlite_nofollow as sn

# Android (Termux) Python has no os.link: apps cannot create hard links there.
_HAS_LINK = hasattr(os, "link")

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

    @unittest.skipUnless(_HAS_LINK, "platform cannot create hard links")
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
            for kind in ("symlink", "hardlink") if _HAS_LINK else ("symlink",):
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

    @unittest.skipUnless(_HAS_LINK, "platform cannot create hard links")
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


_REPO_ROOT = Path(__file__).resolve().parents[2]

# Child writer with deterministic crash points. os._exit = crash: no rollback, no
# checkpoint, no close. cache_size=1 forces pages into the database file before
# commit, so DELETE mode leaves a synced (hot) journal.
_CHILD = r"""
import os, sqlite3, sys
from maep import sqlite_nofollow as sn
path, mode, action = sys.argv[1:4]
if action == "assign-crash":
    sn._complete_through_descriptor = lambda conn: os._exit(0)   # crash right after the identity commit
    sn.connect_nofollow(sqlite3, path, isolation_level=None)
    sys.exit(3)
c = sn.connect_nofollow(sqlite3, path, isolation_level=None)
c.execute(f"PRAGMA journal_mode={mode}")
c.execute("PRAGMA wal_autocheckpoint=0")
if action == "small-commit":                   # touches one leaf page only: page 1 comes from the stamp
    c.execute("BEGIN IMMEDIATE")
    c.execute("UPDATE t SET v = v || '-child' WHERE rowid = 1")
    c.commit()
    os._exit(0)
c.execute("PRAGMA cache_size=1")
c.execute("BEGIN IMMEDIATE")
c.execute("UPDATE t SET v = v || '-child'")
for i in range(300):
    c.execute("INSERT INTO t VALUES(?)", ("pad-%d-%s" % (i, "x" * 500),))
if action in ("commit", "commit-wait"):
    c.commit()
if action == "commit-wait":
    print("READY", flush=True)
    sys.stdin.readline()
    c.close()
    sys.exit(0)
os._exit(0)
"""

_PLAIN_CRASH = r"""
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1], isolation_level=None)
c.execute("PRAGMA journal_mode=wal")
c.execute("PRAGMA wal_autocheckpoint=0")
c.execute("BEGIN IMMEDIATE")
c.execute("UPDATE t SET v = v || '-legacy'")
c.execute("COMMIT")
os._exit(0)
"""

# Swap the path right after the pre-commit check, let the COMMIT be refused, then
# crash before close(): only the commit-time completion can save the replacement.
_RACE_THEN_CRASH = r"""
import os, sqlite3, sys
from pathlib import Path
from maep import sqlite_nofollow as sn
target, displaced = Path(sys.argv[1]), Path("@DISPLACED@")
c = sn.connect_nofollow(sqlite3, target, isolation_level=None)
c.execute("PRAGMA journal_mode=wal")
c.execute("PRAGMA wal_autocheckpoint=0")
real, calls = sn._check_binding, []
def check(binding):
    calls.append(1)
    real(binding)
    if len(calls) == 1:
        os.replace(target, displaced)
        staging = target.with_name("staging.sqlite3")
        s = sqlite3.connect(staging)
        s.execute("CREATE TABLE t(v TEXT)")
        s.executemany("INSERT INTO t VALUES(?)", [("B-%d" % i,) for i in range(20)])
        s.commit(); s.close(); os.chmod(staging, 0o600)
        os.replace(staging, target)
sn._check_binding = check
c.execute("BEGIN IMMEDIATE")
c.execute("INSERT INTO t VALUES('raced-A')")
try:
    c.commit()
except sn.UnsafeSQLitePath:
    print("REFUSED", flush=True)
os._exit(0)
"""

_JOINER = r"""
import sqlite3, sys
from maep import sqlite_nofollow as sn
c = sn.connect_nofollow(sqlite3, sys.argv[1], isolation_level=None)
c.execute("BEGIN IMMEDIATE")
c.execute("INSERT INTO t VALUES('from-second-process')")
c.commit()
c.close()
"""


def _base(tag: str, rows: int = 20) -> list[str]:
    return [f"{tag}-{i}" for i in range(rows)]


class SQLiteRecoveryBindingTests(unittest.TestCase):
    """A transaction or recovery record must only ever reach the database it belongs to.

    SQLite pairs -wal/-journal with a database by NAME and keeps PRAGMA
    integrity_check "ok" after replaying them into the wrong one, so every check
    reads row contents of each database FILE from a copy taken away from any
    sidecars, using rows tagged by database.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hg-sqlite-binding-")
        self.root = Path(self._tmp.name)
        self.target = self.root / "ledger.sqlite3"
        self.displaced = self.root / "displaced.sqlite3"
        self._copies = 0

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------------
    @staticmethod
    def _make(path: Path, tag: str, rows: int = 20, *, wal: bool = False) -> None:
        conn = sqlite3.connect(path)
        if wal:
            conn.execute("PRAGMA journal_mode=wal")
        conn.execute("CREATE TABLE t(v TEXT)")
        conn.executemany("INSERT INTO t VALUES(?)", [(v,) for v in _base(tag, rows)])
        conn.commit()
        conn.close()
        os.chmod(path, 0o600)

    def _replace_target(self, tag: str) -> None:
        """Displace the database and rename a replacement into place (a restore or swap)."""
        os.replace(self.target, self.displaced)
        staging = self.root / "staging.sqlite3"
        self._make(staging, tag)
        os.replace(staging, self.target)

    def _file_rows(self, path: Path) -> list[str]:
        """Rows of the database FILE alone (copied away from every sidecar)."""
        self._copies += 1
        inspect = self.root / f"inspect-{self._copies}"
        inspect.mkdir(mode=0o700)
        copy = inspect / "copy.sqlite3"
        copy.write_bytes(path.read_bytes())
        conn = sqlite3.connect(copy)
        try:
            return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
        finally:
            conn.close()

    def _bound_rows(self, path: Path) -> list[str]:
        conn = sn.connect_nofollow(sqlite3, path, isolation_level=None)
        try:
            return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
        finally:
            conn.close()

    def _sidecars(self, path: Path | None = None) -> list[str]:
        path = path or self.target
        return sorted(s for s in ("-wal", "-shm", "-journal") if Path(str(path) + s).exists())

    def _committed_wal_frames(self, path: Path | None = None) -> int:
        wal = Path(str(path or self.target) + "-wal")
        if not wal.exists():
            return 0
        fd = os.open(wal, os.O_RDONLY)
        try:
            return sn._wal_committed(fd)[0]
        finally:
            os.close(fd)

    def _child(self, script: str, *args: str, **popen):
        env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT))
        argv = [sys.executable, "-c", script, str(self.target), *args]
        if popen:
            return subprocess.Popen(argv, env=env, text=True, **popen)
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=True)

    def _assert_refused(self) -> None:
        before = {s: Path(str(self.target) + s).read_bytes() for s in self._sidecars()}
        with self.assertRaises(sn.UnsafeSQLitePath):
            sn.connect_nofollow(sqlite3, self.target, isolation_level=None).close()
        after = {s: Path(str(self.target) + s).read_bytes() for s in self._sidecars()}
        self.assertEqual(after.keys(), before.keys(), "refused recovery records must be preserved")
        for suffix in ("-wal", "-journal"):
            if suffix in before:
                self.assertEqual(after[suffix], before[suffix], f"{suffix} must not be modified")

    def _racing_swap(self, tag: str):
        """Patch _check_binding so the path is swapped right after the pre-commit check."""
        real = sn._check_binding
        calls = []

        def check(binding):
            calls.append(1)
            real(binding)
            if len(calls) == 1:
                self._replace_target(tag)

        return patch.object(sn, "_check_binding", side_effect=check), calls

    # -- path replaced before / during / after a transaction ---------------------------
    def test_swap_racing_commit_lands_in_its_own_database_only(self):
        """Baseline finding: the raced COMMIT was replayed into the replacement on reopen."""
        for mode in ("wal", "delete"):
            with self.subTest(mode=mode):
                for p in (self.target, self.displaced):
                    for suffix in ("", "-wal", "-shm", "-journal"):
                        Path(str(p) + suffix).unlink(missing_ok=True)
                self._make(self.target, "A")
                conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
                swap, calls = self._racing_swap("B")
                try:
                    conn.execute(f"PRAGMA journal_mode={mode}")
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("INSERT INTO t VALUES('raced-A')")
                    with swap:
                        with self.assertRaises(sn.UnsafeSQLitePath):
                            conn.commit()
                    self.assertEqual(len(calls), 2)
                finally:
                    conn.close()
                self.assertEqual(self._committed_wal_frames(), 0, "no committed frame may remain at the path")
                self.assertEqual(self._file_rows(self.displaced), _base("A") + ["raced-A"])
                self.assertEqual(self._file_rows(self.target), _base("B"))
                self.assertEqual(self._bound_rows(self.target), _base("B"))

    def test_frames_committed_before_a_swap_are_completed_into_their_database_on_close(self):
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=wal")
            conn.execute("PRAGMA wal_autocheckpoint=0")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES('committed-A')")
            conn.commit()
            self.assertGreater(self._committed_wal_frames(), 0)
            self._replace_target("B")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES('uncommitted-A')")
        finally:
            conn.close()
        self.assertEqual(self._committed_wal_frames(), 0)
        self.assertEqual(self._file_rows(self.displaced), _base("A") + ["committed-A"])
        self.assertEqual(self._bound_rows(self.target), _base("B"))

    def test_refused_commit_then_crash_leaves_nothing_for_the_replacement(self):
        """The raced COMMIT is completed into its database at once, not only at close()."""
        self._make(self.target, "A")
        script = _RACE_THEN_CRASH.replace("@DISPLACED@", str(self.displaced))
        result = self._child(script)
        self.assertEqual(result.stdout.strip(), "REFUSED")
        self.assertEqual(self._committed_wal_frames(), 0)
        self.assertEqual(self._file_rows(self.displaced), _base("A") + ["raced-A"])
        self.assertEqual(self._bound_rows(self.target), _base("B"))

    @unittest.skipUnless(hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE"),
                         "Python < 3.12 cannot suppress SQLite's close-time checkpoint")
    def test_records_planted_between_admission_and_open_are_caught_by_sqlites_view(self):
        """Defence in depth: SQLite's own view of page 1 must name the admitted identity."""
        foreign = self.root / "foreign.sqlite3"
        self._make(foreign, "A")
        conn = sn.connect_nofollow(sqlite3, foreign, isolation_level=None)
        conn.execute("PRAGMA journal_mode=wal")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE t SET v = v || '-foreign'")
        conn.commit()
        foreign_wal = Path(str(foreign) + "-wal").read_bytes()
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
        conn.close()
        self._make(self.target, "B")
        sn.connect_nofollow(sqlite3, self.target).close()  # B gets its own identity
        before = self.target.read_bytes()
        real_connect = sqlite3.connect

        def planting_connect(*args, **kwargs):
            wal = Path(str(self.target) + "-wal")
            wal.write_bytes(foreign_wal)
            os.chmod(wal, 0o600)
            return real_connect(*args, **kwargs)

        with patch.object(sqlite3, "connect", side_effect=planting_connect):
            with self.assertRaises(sn.UnsafeSQLitePath):
                sn.connect_nofollow(sqlite3, self.target).close()
        self.assertEqual(self.target.read_bytes(), before, "foreign frames must not be checkpointed")
        self.assertEqual(Path(str(self.target) + "-wal").read_bytes(), foreign_wal)

    def test_context_manager_commit_is_bound(self):
        """sqlite3's C __exit__ bypassed the bound commit(): a swapped path committed silently."""
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target)
        try:
            conn.execute("PRAGMA journal_mode=wal")
            self._replace_target("B")
            with self.assertRaises(sn.UnsafeSQLitePath):
                with conn:
                    conn.execute("INSERT INTO t VALUES('ctx-A')")
        finally:
            conn.close()
        self.assertEqual(self._file_rows(self.target), _base("B"))

    # -- crash, then the path is replaced or overwritten --------------------------------
    def test_wal_committed_before_crash_is_refused_for_a_replacement_and_recoverable_for_its_owner(self):
        self._make(self.target, "A")
        self._child(_CHILD, "wal", "commit")
        self.assertGreater(self._committed_wal_frames(), 0)
        self._replace_target("B")
        self._assert_refused()
        self.assertEqual(self._file_rows(self.target), _base("B"))
        # The refused records are the displaced database's: beside it, they recover it.
        for suffix in ("-wal", "-shm"):
            os.replace(str(self.target) + suffix, str(self.displaced) + suffix)
        rows = self._bound_rows(self.displaced)
        self.assertEqual(rows[:20], [f"{v}-child" for v in _base("A")])
        self.assertEqual(len(rows), 320)
        self.assertEqual(self._bound_rows(self.target), _base("B"))

    def test_in_place_overwrite_with_another_database_is_refused(self):
        """Same inode, different content: an inode-based binding would accept this."""
        self._make(self.target, "A")
        self._child(_CHILD, "wal", "commit")
        inode = self.target.stat().st_ino
        staging = self.root / "staging.sqlite3"
        self._make(staging, "B")
        with open(self.target, "r+b") as fh:
            fh.write(staging.read_bytes())
            fh.truncate()
        self.assertEqual(self.target.stat().st_ino, inode)
        self._assert_refused()
        self.assertEqual(self._file_rows(self.target), _base("B"))

    def test_hot_journal_of_a_displaced_database_is_not_rolled_back_into_the_replacement(self):
        self._make(self.target, "A")
        self._child(_CHILD, "delete", "crash")
        self.assertEqual(self._sidecars(), ["-journal"])
        self._replace_target("B")
        self._assert_refused()
        self.assertEqual(self._file_rows(self.target), _base("B"))

    def test_orphaned_records_without_a_database_are_refused_before_creating_one(self):
        self._make(self.target, "A")
        self._child(_CHILD, "wal", "commit")
        os.replace(self.target, self.displaced)
        with self.assertRaises(sn.UnsafeSQLitePath):
            sn.connect_nofollow(sqlite3, self.target).close()
        self.assertFalse(self.target.exists())

    # -- live connections ---------------------------------------------------------------
    def test_live_writer_in_another_process_blocks_open_of_a_replacement(self):
        self._make(self.target, "A")
        proc = self._child(_CHILD, "wal", "commit-wait", stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "READY")
            self._replace_target("B")
            self._assert_refused()
            self.assertEqual(self._file_rows(self.target), _base("B"))
        finally:
            proc.communicate(input="\n", timeout=120)
        self.assertEqual(proc.returncode, 0)

    def test_live_connection_in_this_process_blocks_open_of_a_replacement(self):
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=wal")
            self._replace_target("B")
            with self.assertRaises(sn.UnsafeSQLitePath):
                sn.connect_nofollow(sqlite3, self.target).close()
        finally:
            conn.close()

    def test_concurrent_processes_on_the_same_database(self):
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=wal")
            conn.execute("PRAGMA wal_autocheckpoint=0")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES('from-first-process')")
            conn.commit()
            self._child(_JOINER)
            rows = [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
        finally:
            conn.close()
        self.assertEqual(rows, _base("A") + ["from-first-process", "from-second-process"])

    # -- legitimate recovery is preserved -------------------------------------------------
    def test_crash_recovery_of_the_same_database_still_works(self):
        cases = (
            ("wal", "commit", False, [f"{v}-child" for v in _base("A")], 320),
            ("wal", "commit", True, [f"{v}-child" for v in _base("A")], 320),   # -shm lost
            ("wal", "crash", False, _base("A"), 20),
            ("wal", "small-commit", False, ["A-0-child"] + _base("A")[1:], 20),
            ("delete", "crash", False, _base("A"), 20),
        )
        for mode, action, drop_shm, head, count in cases:
            with self.subTest(mode=mode, action=action, drop_shm=drop_shm):
                for suffix in ("", "-wal", "-shm", "-journal"):
                    Path(str(self.target) + suffix).unlink(missing_ok=True)
                self._make(self.target, "A")
                self._child(_CHILD, mode, action)
                self.assertTrue(self._sidecars())
                if drop_shm:
                    Path(str(self.target) + "-shm").unlink()
                rows = self._bound_rows(self.target)
                self.assertEqual(rows[:20], head)
                self.assertEqual(len(rows), count)

    # -- sidecars that are missing, unrelated, foreign or tampered ------------------------
    def test_unrelated_foreign_and_tampered_wal(self):
        self._make(self.target, "A")
        self._child(_CHILD, "wal", "commit")
        wal_a = Path(str(self.target) + "-wal").read_bytes()
        for suffix in ("-wal", "-shm"):
            Path(str(self.target) + suffix).unlink()
        file_a = self._file_rows(self.target)
        wal = Path(str(self.target) + "-wal")
        with self.subTest("random bytes: SQLite and admission both see no frames"):
            wal.write_bytes(os.urandom(len(wal_a)))
            os.chmod(wal, 0o600)
            self.assertEqual(self._bound_rows(self.target), file_a)
        with self.subTest("checksum broken in the first frame: nothing is committed"):
            tampered = bytearray(wal_a)
            tampered[32 + 24 + 200] ^= 0xFF
            wal.write_bytes(bytes(tampered))
            self.assertEqual(self._committed_wal_frames(), 0)
            self.assertEqual(self._bound_rows(self.target), file_a)
        with self.subTest("header checksum broken: SQLite ignores the WAL, so admission must too"):
            other = self.root / "header-b.sqlite3"
            self._make(other, "B")
            broken = bytearray(wal_a)
            broken[24] ^= 0x01  # stored header checksum: SQLite ignores the whole WAL
            Path(str(other) + "-wal").write_bytes(bytes(broken))
            os.chmod(str(other) + "-wal", 0o600)
            self.assertEqual(self._bound_rows(other), _base("B"))
        with self.subTest("another database's committed WAL beside this one is refused"):
            other = self.root / "other.sqlite3"
            self._make(other, "B")
            wal.unlink(missing_ok=True)  # the previous clean close removed it
            Path(str(other) + "-wal").write_bytes(wal_a)
            os.chmod(str(other) + "-wal", 0o600)
            saved = self.target
            self.target = other
            try:
                self._assert_refused()
                self.assertEqual(self._file_rows(other), _base("B"))
            finally:
                self.target = saved

    def test_wal_decoder_matches_sqlite_recovery(self):
        """Admission must see exactly the transactions SQLite recovery applies."""
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target, isolation_level=None)
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        conn.execute("PRAGMA journal_mode=wal")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for i in range(6):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO t VALUES(?)", (f"txn-{i}",))
            conn.commit()
        wal_bytes = Path(str(self.target) + "-wal").read_bytes()
        db_bytes = self.target.read_bytes()  # both snapshots taken before close() checkpoints
        conn.close()
        page_size = struct.unpack(">I", wal_bytes[8:12])[0]
        frame = 24 + page_size
        cuts = sorted({len(wal_bytes), 0, 31, 32} | {32 + k * frame + d for k in range(len(wal_bytes) // frame + 1)
                                                      for d in (0, 1, frame - 1)})
        for cut in cuts:
            if cut > len(wal_bytes):
                continue
            with self.subTest(cut=cut):
                case = self.root / f"cut-{cut}"
                case.mkdir(mode=0o700)
                (case / "db.sqlite3").write_bytes(db_bytes)
                (case / "db.sqlite3-wal").write_bytes(wal_bytes[:cut])
                fd = os.open(case / "db.sqlite3-wal", os.O_RDONLY)
                try:
                    frames, txns, ids = sn._wal_committed(fd)
                finally:
                    os.close(fd)
                plain = sqlite3.connect(case / "db.sqlite3")
                try:
                    applied = plain.execute("SELECT count(*) FROM t WHERE v LIKE 'txn-%'").fetchone()[0]
                finally:
                    plain.close()
                self.assertEqual(txns, applied)
                self.assertEqual(set(ids), {app_id} if txns else set())

    # -- identity assignment and operator recovery --------------------------------------
    def test_crash_during_identity_assignment_fails_closed_and_adopt_recovers(self):
        self._make(self.target, "A", wal=True)
        result = self._child(_CHILD, "wal", "assign-crash")
        self.assertEqual(result.returncode, 0)
        self.assertGreater(self._committed_wal_frames(), 0)
        self._assert_refused()
        originals = {self.target.name + s: hashlib.sha256(Path(str(self.target) + s).read_bytes()).hexdigest()
                     for s in ("",) + tuple(self._sidecars())}
        report = sn.adopt_sidecars(sqlite3, self.target, backup_dir=self.root / "backup")
        self.assertEqual(report["files"], originals)
        self.assertEqual(report["integrity_check"], "ok")
        for name, digest in originals.items():
            self.assertEqual(hashlib.sha256((self.root / "backup" / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(self._bound_rows(self.target), _base("A"))
        conn = sn.connect_nofollow(sqlite3, self.target)
        try:
            self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], report["application_id"])
        finally:
            conn.close()

    def test_legacy_hot_wal_without_identity_requires_explicit_adopt(self):
        self._make(self.target, "A")
        self._child(_PLAIN_CRASH)
        self._assert_refused()
        (self.root / "exists").mkdir()
        with self.assertRaises(FileExistsError):
            sn.adopt_sidecars(sqlite3, self.target, backup_dir=self.root / "exists")
        self.assertEqual(list((self.root / "exists").iterdir()), [])
        report = sn.adopt_sidecars(sqlite3, self.target, backup_dir=self.root / "backup")
        self.assertNotEqual(report["application_id"], 0)
        self.assertEqual(self._bound_rows(self.target), [f"{v}-legacy" for v in _base("A")])

    def test_adopt_refuses_a_database_open_in_this_process(self):
        self._make(self.target, "A")
        conn = sn.connect_nofollow(sqlite3, self.target)
        try:
            with self.assertRaises(sn.UnsafeSQLitePath):
                sn.adopt_sidecars(sqlite3, self.target, backup_dir=self.root / "backup")
            self.assertFalse((self.root / "backup").exists())
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
