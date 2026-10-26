"""AuthorityEvidenceReader: read-only, same records and integrity checks as MemoryStore."""
import json
import os
import sqlite3
import unittest

from maep.core import MAEPError
from memory import AuthorityEvidenceReader
from memory.tests import test_store as store_fixtures


class AuthorityEvidenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = store_fixtures.MemoryStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.store.record_evidence("T-MK-1", self.fixture.evidence("EV-1"))
        self.reader = AuthorityEvidenceReader(self.fixture.db)

    def test_returns_the_same_records_as_the_authorized_api(self):
        self.assertEqual(self.reader.get_task("T-MK-1"), self.store.get_task("T-MK-1"))
        self.assertEqual(self.reader.get_evidence("T-MK-1", "EV-1"),
                         self.store.get_evidence("T-MK-1", "EV-1"))
        self.assertIsNone(self.reader.get_evidence("T-MK-1", "EV-MISSING"))
        self.assertEqual(self.reader.get_events("T-MK-1", limit=50),
                         self.store.get_events("T-MK-1", limit=50))
        self.assertEqual(self.reader.check_integrity(task_id="T-MK-1"),
                         self.store.check_integrity(task_id="T-MK-1"))
        self.assertEqual(self.reader.list_tasks(index_scope_task_id="T-MK-1", limit=10),
                         self.store.list_tasks(index_scope_task_id="T-MK-1", limit=10))

    def test_argument_validation_matches_the_authorized_api(self):
        for call in (lambda r: r.get_events("T-MK-1", limit=0),
                     lambda r: r.get_evidence("", "EV-1"),
                     lambda r: r.list_tasks(index_scope_task_id="T-MK-1", limit=501),
                     lambda r: r.check_integrity(task_id="")):
            with self.assertRaises(MAEPError):
                call(self.reader)
        with self.assertRaisesRegex(MAEPError, "task not found"):
            self.reader.get_task("T-UNKNOWN")

    def test_has_no_write_surface_and_its_connection_is_read_only(self):
        for name in ("create_task", "record_evidence", "transition_task", "put_knowledge",
                     "save_checkpoint", "initialize", "backup_to", "restore_to"):
            self.assertFalse(hasattr(self.reader, name), name)
        # The private store has no principal/policy providers: its public API fails closed.
        with self.assertRaisesRegex(MAEPError, "policy evaluator unavailable"):
            self.reader._store.get_task("T-MK-1")
        connection = self.reader._store._connect(readonly=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM evidence")
        finally:
            connection.close()
        self.assertIsNotNone(self.store.get_evidence("T-MK-1", "EV-1"))

    def test_tampered_event_chain_blocks_reads(self):
        raw = sqlite3.connect(self.fixture.db)
        try:
            # Simulates a privileged file edit that bypasses the append-only trigger.
            raw.execute("DROP TRIGGER maep_events_no_update")
            row = raw.execute("SELECT sequence, payload_json FROM maep_events ORDER BY sequence DESC LIMIT 1").fetchone()
            payload = json.loads(row[1])
            payload["tampered"] = True
            raw.execute("UPDATE maep_events SET payload_json=? WHERE sequence=?",
                        (json.dumps(payload), row[0]))
            raw.commit()
        finally:
            raw.close()
        with self.assertRaisesRegex(MAEPError, "digest mismatch"):
            self.reader.get_task("T-MK-1")
        with self.assertRaisesRegex(MAEPError, "digest mismatch"):
            self.reader.get_evidence("T-MK-1", "EV-1")
        self.assertEqual(self.reader.check_integrity(task_id="T-MK-1")["status"], "FAIL")

    def test_broad_permissions_and_missing_database_fail_closed(self):
        os.chmod(self.fixture.db, 0o644)
        with self.assertRaisesRegex(MAEPError, "broader than 0600"):
            self.reader.get_task("T-MK-1")
        os.chmod(self.fixture.db, 0o600)
        missing = self.fixture.root / "absent.sqlite3"
        with self.assertRaisesRegex(MAEPError, "does not exist"):
            AuthorityEvidenceReader(missing).get_task("T-MK-1")
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()


class AuthorityReaderTaskIdSourceTests(unittest.TestCase):
    """The reader is the canonical task-ID source for CanonicalMemoryTaskSelectors."""

    def setUp(self):
        self.fixture = store_fixtures.MemoryStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.store.create_task(store_fixtures.MemoryStoreTests.task("T-MK-2"), candidate_ref="candidate-1")
        self.reader = AuthorityEvidenceReader(self.fixture.db)

    def test_lists_every_canonical_task_id_in_order(self):
        self.assertEqual(self.reader.list_canonical_task_ids(), ["T-MK-1", "T-MK-2"])

    def test_satisfies_the_selector_task_id_source_contract(self):
        from maep.memory_evidence_providers import CanonicalMemoryTaskSelectors
        from maep.trust_source_contracts import CanonicalTaskIdSource
        self.assertIsInstance(self.reader, CanonicalTaskIdSource)
        selectors = CanonicalMemoryTaskSelectors(memory_store=self.reader, canonical_task_id_source=self.reader)
        self.fixture.store.record_evidence("T-MK-2", self.fixture.evidence("EV-ONLY-2"))
        self.assertIsNone(selectors.resolve_evidence_task("EV-ONLY-2"))  # not referenced by inputs

    def test_tampered_task_row_blocks_listing(self):
        raw = sqlite3.connect(self.fixture.db)
        try:
            triggers = [r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='tasks'")]
            for name in triggers:
                raw.execute(f"DROP TRIGGER {name}")
            raw.execute("UPDATE tasks SET state='RUNNING' WHERE task_id='T-MK-2'")
            raw.commit()
        finally:
            raw.close()
        with self.assertRaisesRegex(MAEPError, "disagree"):
            self.reader.list_canonical_task_ids()


class AuthorityReaderTaskExistsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = store_fixtures.MemoryStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.reader = AuthorityEvidenceReader(self.fixture.db)

    def test_reports_present_and_absent_tasks(self):
        self.assertIs(self.reader.has_task("T-MK-1"), True)
        self.assertIs(self.reader.has_task("T-NOT-THERE"), False)
        with self.assertRaises(MAEPError):
            self.reader.has_task("")

    def test_tampered_store_raises_instead_of_reporting_absent(self):
        raw = sqlite3.connect(self.fixture.db)
        try:
            raw.execute("DROP TRIGGER maep_events_no_update")
            row = raw.execute("SELECT sequence, payload_json FROM maep_events ORDER BY sequence DESC LIMIT 1").fetchone()
            payload = json.loads(row[1])
            payload["tampered"] = True
            raw.execute("UPDATE maep_events SET payload_json=? WHERE sequence=?", (json.dumps(payload), row[0]))
            raw.commit()
        finally:
            raw.close()
        with self.assertRaisesRegex(MAEPError, "digest mismatch"):
            self.reader.has_task("T-NOT-THERE")

    def test_selectors_distinguish_absent_task_from_lookup_failure(self):
        from maep.memory_evidence_providers import CanonicalMemoryTaskSelectors
        from maep.native_authority import AuthorityError
        selectors = CanonicalMemoryTaskSelectors(memory_store=self.reader, canonical_task_id_source=self.reader)
        self.assertIs(selectors.task_exists("T-NOT-THERE"), False)
        self.assertIs(selectors.task_exists("T-MK-1"), True)
        os.chmod(self.fixture.db, 0o644)
        with self.assertRaisesRegex(AuthorityError, "existence check failed"):
            selectors.task_exists("T-NOT-THERE")
        os.chmod(self.fixture.db, 0o600)
