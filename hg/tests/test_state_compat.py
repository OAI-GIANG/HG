"""AC-R1: state written by the deployed release (commit f3dac34) loads with the current code.

The fixture directory was produced by running f3dac34's own runtime and IdempotencyStore
(one CLOSED_VERIFIED task with memory, one COMPLETE and one IN_DOUBT idempotency receipt).
A redeploy opens exactly these files, so a format break must fail here, in CI, first.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from hg.http_api import IdempotencyStore
from hg.memory.store import MemoryStore
from hg.tools.gateway import pending_from_events
from hg.verification.evidence import EventLog
from maep.task_store import TaskStore

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "state_f3dac34"


class DeployedStateCompatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hg-compat-")
        os.chmod(self.tmp, 0o700)
        self.state = Path(self.tmp) / "state"
        shutil.copytree(FIXTURE, self.state)
        os.chmod(self.state, 0o700)
        for path in self.state.rglob("*"):
            if path.is_file():
                os.chmod(path, 0o600)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_task_ledger_restores_closed_task(self):
        store = TaskStore.restore(self.state / "tasks.jsonl")
        self.assertEqual(store.snapshot("FX-1")["task"]["state"], "CLOSED_VERIFIED")

    def test_action_ledger_has_no_pending_actions(self):
        self.assertEqual(pending_from_events(EventLog(self.state / "actions.jsonl").events()), {})

    def test_memory_ledger_replays(self):
        memory = MemoryStore(self.state / "memory.jsonl")
        self.assertEqual(memory.stats()["conflicts"], 0)
        self.assertEqual([r["subject"] for r in memory.active()], ["task:FX-1"])

    def test_idempotency_database_keeps_receipts(self):
        store = IdempotencyStore(self.state / "http-idempotency.sqlite3")
        try:
            self.assertEqual(store.begin("fixture-key-0001", "sha256:abc"),
                             ("REPLAY", {"status": 201, "task_id": "FX-1"}))
            self.assertEqual(store.begin("fixture-key-0001", "sha256:other")[0], "CONFLICT")
            self.assertEqual(store.begin("fixture-key-0002", "sha256:def")[0], "IN_DOUBT")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
