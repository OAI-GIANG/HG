import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path

from brain.routing_budget import RoutingBudgetError, SQLiteRoutingBudgetLedger


class SQLiteRoutingBudgetLedgerTests(unittest.TestCase):
    def test_reservations_are_durable_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.sqlite3"
            ledger = SQLiteRoutingBudgetLedger(path)
            self.assertTrue(ledger.reserve("T-1", "reasoning", 2))
            self.assertTrue(ledger.reserve("T-1", "reasoning", 2))
            self.assertFalse(ledger.reserve("T-1", "reasoning", 2))
            reopened = SQLiteRoutingBudgetLedger(path)
            self.assertEqual(reopened.get_usage("T-1")["reasoning"], 2)
            self.assertTrue(reopened.reserve("T-1", "council", 1))
            self.assertEqual(reopened.get_usage("T-1")["council"], 1)

    def test_concurrent_reservations_never_exceed_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.sqlite3"
            ledgers = [SQLiteRoutingBudgetLedger(path, timeout=10) for _ in range(12)]
            barrier = threading.Barrier(len(ledgers))

            def reserve(ledger):
                barrier.wait()
                return ledger.reserve("T-CONCURRENT", "reasoning", 3)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ledgers)) as pool:
                results = list(pool.map(reserve, ledgers))
            self.assertEqual(sum(results), 3)
            self.assertEqual(SQLiteRoutingBudgetLedger(path).get_usage("T-CONCURRENT")["reasoning"], 3)

    def test_invalid_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = SQLiteRoutingBudgetLedger(Path(directory) / "budget.sqlite3")
            with self.assertRaises(RoutingBudgetError):
                ledger.reserve("", "reasoning", 1)
            with self.assertRaises(RoutingBudgetError):
                ledger.reserve("T-1", "unknown", 1)
            with self.assertRaises(RoutingBudgetError):
                ledger.reserve("T-1", "reasoning", True)

    def test_task_counters_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = SQLiteRoutingBudgetLedger(Path(directory) / "budget.sqlite3")
            self.assertTrue(ledger.reserve("T-1", "reasoning", 1))
            self.assertEqual(ledger.get_usage("T-2")["reasoning"], 0)

    def test_identity_bound_reservation_is_unique_and_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.sqlite3"
            ledger = SQLiteRoutingBudgetLedger(path)
            args = dict(task_ref="T-1", candidate_ref="C-1", policy_version="P-1",
                        route="SINGLE_MODEL", category="reasoning", call_id="CALL-1", limit=1)
            self.assertTrue(ledger.reserve_bound(**args))
            self.assertFalse(ledger.reserve_bound(**args))
            reopened = SQLiteRoutingBudgetLedger(path)
            self.assertEqual(reopened.get_usage("T-1")["reasoning"], 1)
            changed = dict(args, candidate_ref="C-2", call_id="CALL-2")
            self.assertFalse(reopened.reserve_bound(**changed))

    def test_identity_bound_reservation_fails_closed_for_missing_binding_or_zero_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = SQLiteRoutingBudgetLedger(Path(directory) / "budget.sqlite3")
            args = dict(task_ref="T-1", candidate_ref="C-1", policy_version="P-1",
                        route="SINGLE_MODEL", category="reasoning", call_id="CALL-1", limit=1)
            for field in ("candidate_ref", "policy_version", "route", "call_id"):
                invalid = dict(args, **{field: " "})
                with self.assertRaises(RoutingBudgetError):
                    ledger.reserve_bound(**invalid)
            self.assertFalse(ledger.reserve_bound(**dict(args, limit=0)))
            self.assertEqual(ledger.get_usage("T-1")["reasoning"], 0)


if __name__ == "__main__":
    unittest.main()
