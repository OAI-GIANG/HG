import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path

from brain.routing_budget import RoutingBudgetError, SQLiteRoutingBudgetLedger


class SQLiteRoutingBudgetLedgerTests(unittest.TestCase):
    def test_rejects_path_swap_at_sqlite_open_boundary(self):
        import sqlite3
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix="hg-routing-open-race-") as directory:
            target = Path(directory) / "budget.sqlite3"
            external = Path(directory) / "external.sqlite3"
            conn = sqlite3.connect(external)
            conn.execute("CREATE TABLE sentinel(value TEXT)")
            conn.execute("INSERT INTO sentinel VALUES('untouched')")
            conn.commit()
            conn.close()
            original_connect = sqlite3.connect
            swapped = False

            def race_connect(database, *args, **kwargs):
                nonlocal swapped
                if not swapped and str(database).startswith("file:/proc/self/fd/"):
                    target.unlink()
                    target.symlink_to(external)
                    swapped = True
                return original_connect(database, *args, **kwargs)

            with patch("sqlite3.connect", side_effect=race_connect):
                with self.assertRaises(RoutingBudgetError):
                    SQLiteRoutingBudgetLedger(target)
            self.assertTrue(swapped)
            self.assertTrue(target.is_symlink())
            conn = original_connect(external)
            self.assertEqual(conn.execute("SELECT value FROM sentinel").fetchone()[0], "untouched")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {"sentinel"})
            conn.close()

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
