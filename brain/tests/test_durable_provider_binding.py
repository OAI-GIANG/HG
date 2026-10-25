"""Brain integration tests with real local durable ledger and receipt adapters.

All state lives in TemporaryDirectory; no production runtime or database is used.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maep.local_runtime_providers import LocalReceiptSink, SQLiteIdempotencyLedger
from brain.tests.test_orchestrator import BrainTests, Adapter
from brain.orchestrator import OrchestrationError


class DurableBrainBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BrainTests()
        self.fixture.setUp()
        self.brain = self.fixture.brain
        self.adapter = self.fixture.adapter
        self.request = self.fixture.request
        self._temp = tempfile.TemporaryDirectory(prefix="hg-brain-durable-binding-")
        base = Path(self._temp.name)
        self.durable_ledger_path = base / "ledger.sqlite3"
        self.durable_receipt_dir = base / "receipts"
        self.durable_ledger = SQLiteIdempotencyLedger(self.durable_ledger_path)
        self.durable_receipts = LocalReceiptSink(self.durable_receipt_dir)
        self.brain.idempotency_ledger = self.durable_ledger
        self.brain.receipt_sink = self.durable_receipts

    def tearDown(self):
        try:
            self._temp.cleanup()
        finally:
            self.fixture.tearDown()

    def dispatch(self, key="durable:default"):
        return self.brain.dispatch(
            request=self.request, authenticated_context="fixture-session",
            candidate_target="candidate-target", adapter_name="test", idempotency_key=key,
        )

    def test_brain_dispatch_uses_durable_adapters_and_replay_is_blocked_after_reopen(self):
        result = self.dispatch(key="durable:success")
        self.assertEqual(result["outcome"], "SUCCESS")
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(self.durable_ledger.inspect("durable:success")["outcome"], "SUCCESS")
        self.assertTrue(self.durable_receipts.verify_integrity())
        self.assertGreaterEqual(len(self.durable_receipts.read_all()), 1)

        reopened_ledger = SQLiteIdempotencyLedger(self.durable_ledger_path)
        reopened_receipts = LocalReceiptSink(self.durable_receipt_dir)
        self.brain.idempotency_ledger = reopened_ledger
        self.brain.receipt_sink = reopened_receipts
        with self.assertRaisesRegex(OrchestrationError, "duplicate"):
            self.dispatch(key="durable:success")
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(reopened_ledger.inspect("durable:success")["outcome"], "SUCCESS")
        self.assertTrue(reopened_receipts.verify_integrity())

    def test_brain_timeout_persists_unknown_and_duplicate_after_reopen(self):
        timeout_adapter = Adapter(timeout=True)
        self.brain.adapter_registry["durable-timeout"] = timeout_adapter
        with self.assertRaisesRegex(OrchestrationError, "OUTCOME_UNKNOWN"):
            self.brain.dispatch(
                request=self.request, authenticated_context="fixture-session",
                candidate_target="candidate-target", adapter_name="durable-timeout",
                idempotency_key="durable:unknown",
            )
        self.assertEqual(timeout_adapter.calls, 1)
        row = self.durable_ledger.inspect("durable:unknown")
        self.assertEqual(row["outcome"], "UNKNOWN")
        self.assertEqual(row["receipt"]["outcome"], "UNKNOWN")

        reopened = SQLiteIdempotencyLedger(self.durable_ledger_path)
        with self.assertRaisesRegex(OrchestrationError, "duplicate"):
            self.brain.dispatch(
                request=self.request, authenticated_context="fixture-session",
                candidate_target="candidate-target", adapter_name="durable-timeout",
                idempotency_key="durable:unknown",
            )
        self.assertEqual(timeout_adapter.calls, 1)
        self.assertEqual(reopened.inspect("durable:unknown")["outcome"], "UNKNOWN")

    def test_brain_blocks_conflicting_preexisting_reservation_before_effect(self):
        # Simulate a durable key already reserved for a different request/decision.
        self.durable_ledger.claim(
            idempotency_key="durable:conflict", request_digest="sha256:reserved-other-request",
            decision_digest="sha256:reserved-other-decision",
        )
        with self.assertRaisesRegex(OrchestrationError, "duplicate, conflicting, or unresolved"):
            self.dispatch(key="durable:conflict")
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.durable_ledger.inspect("durable:conflict")["status"], "RESERVED")


if __name__ == "__main__":
    unittest.main()
