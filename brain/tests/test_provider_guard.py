import concurrent.futures
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from brain.provider_guard import (
    GuardedJSONProvider, ProviderCallBlocked, authorize_provider_calls,
)
from brain.routing_budget import SQLiteRoutingBudgetLedger


class FakeProvider:
    timeout_seconds = 2.0

    def __init__(self):
        self.calls = 0

    def generate_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        return '{"ok":true}'


class ProviderGuardTests(unittest.TestCase):
    def test_call_requires_scope_and_reserves_before_forwarding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.sqlite3"
            ledger = SQLiteRoutingBudgetLedger(path)
            raw = FakeProvider()
            provider = GuardedJSONProvider(raw)
            with self.assertRaisesRegex(ProviderCallBlocked, "no active HG router authorization"):
                provider.generate_json(system_prompt="s", user_prompt="u")
            self.assertEqual(raw.calls, 0)

            with authorize_provider_calls(
                ledger=ledger, task_ref="task:1", candidate_ref="candidate:1",
                policy_version="policy:1", route="SINGLE_MODEL", category="reasoning", limit=1,
            ):
                self.assertEqual(provider.generate_json(system_prompt="s", user_prompt="u"), '{"ok":true}')
                with self.assertRaisesRegex(ProviderCallBlocked, "reservation denied"):
                    provider.generate_json(system_prompt="s", user_prompt="u")
            self.assertEqual(raw.calls, 1)
            self.assertEqual(ledger.get_usage("task:1")["reasoning"], 1)
            with sqlite3.connect(path) as connection:
                row = connection.execute(
                    "SELECT task_ref,candidate_ref,policy_version,route,category "
                    "FROM routing_budget_reservations"
                ).fetchone()
            self.assertEqual(row, ("task:1", "candidate:1", "policy:1", "SINGLE_MODEL", "reasoning"))

    def test_concurrent_authorized_calls_never_exceed_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SQLiteRoutingBudgetLedger(Path(tmp) / "budget.sqlite3", timeout=10)
            raw = FakeProvider()
            provider = GuardedJSONProvider(raw)
            barrier = threading.Barrier(12)
            def invoke(index):
                barrier.wait()
                with authorize_provider_calls(
                    ledger=ledger, task_ref="task:concurrent", candidate_ref="candidate:1",
                    policy_version="policy:1", route="SINGLE_MODEL", category="reasoning", limit=3,
                ):
                    try:
                        provider.generate_json(system_prompt="s", user_prompt="u")
                        return True
                    except ProviderCallBlocked:
                        return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(invoke, range(12)))
            self.assertEqual(sum(results), 3)
            self.assertEqual(raw.calls, 3)
            self.assertEqual(SQLiteRoutingBudgetLedger(Path(tmp) / "budget.sqlite3").get_usage("task:concurrent")["reasoning"], 3)

    def test_authorization_scope_is_cleared_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SQLiteRoutingBudgetLedger(Path(tmp) / "budget.sqlite3")
            provider = GuardedJSONProvider(FakeProvider())
            with self.assertRaisesRegex(RuntimeError, "forced"):
                with authorize_provider_calls(
                    ledger=ledger, task_ref="task:1", candidate_ref="candidate:1",
                    policy_version="policy:1", route="SINGLE_MODEL", category="reasoning", limit=1,
                ):
                    raise RuntimeError("forced")
            with self.assertRaises(ProviderCallBlocked):
                provider.generate_json(system_prompt="s", user_prompt="u")


if __name__ == "__main__":
    unittest.main()
