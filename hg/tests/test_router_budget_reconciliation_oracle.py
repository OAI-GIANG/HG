"""WS-08 oracle: ModelRouter accounting reconciles with the calls it made.

The router's `usage` (calls, input/output tokens, cost_usd) is the per-session budget
record. It is checked here against totals computed independently, in exact arithmetic,
from the calls that succeeded, and against the OK MODEL_CALL events in the ledger:

1. cost_usd equals the exact sum of per-call costs (to the 6 decimals it is reported in),
   however many calls there are and however small each one is;
2. a provider answer whose usage is not a JSON-like object of non-negative integer token
   counts is refused as INVALID_RESPONSE (retry/fallback as usual), never a Python crash
   out of complete() and never a negative or fractional addition to the totals;
3. a price (cost_per_mtok) is a pair of finite non-negative numbers, checked when the
   router is built; the price used is the one checked, not a later mutation.
"""
import math
import unittest
from fractions import Fraction
from pathlib import Path

from maep.core import MAEPError
from hg.brain.providers import ModelProvider, ModelRouter, ProviderError, make_request
from hg.verification.evidence import EventLog
from hg.tests.support import TempDirMixin

REQ = make_request("s", [{"role": "user", "content": "q"}], max_tokens=16)


class UsageProvider(ModelProvider):
    """Answers every call with the next usage value from a script (test double)."""

    _MISSING = object()

    def __init__(self, name, usages, *, price=(0.0, 0.0)):
        self.name, self.model, self.offline = name, name + "-1", True
        self.cost_per_mtok = price
        self.usages = list(usages)

    def complete(self, request):
        usage = self.usages.pop(0)
        response = {"text": "ok", "provider": self.name, "model": self.model, "finish_reason": "stop"}
        if usage is not self._MISSING:
            response["usage"] = usage
        return response


def exact_cost(calls):
    return sum((Fraction(cin) * tin + Fraction(cout) * tout for tin, tout, cin, cout in calls),
               Fraction(0)) / 1_000_000


class RouterBudgetReconciliationOracle(TempDirMixin, unittest.TestCase):

    def assert_reconciled(self, router, calls, log=None):
        self.assertEqual(router.usage["calls"], len(calls))
        self.assertEqual(router.usage["input_tokens"], sum(c[0] for c in calls))
        self.assertEqual(router.usage["output_tokens"], sum(c[1] for c in calls))
        exact = exact_cost(calls)
        self.assertLessEqual(abs(Fraction(router.usage["cost_usd"]) - exact), Fraction(1, 2_000_000) + Fraction(1, 10**12),
                             f"cost_usd {router.usage['cost_usd']} vs exact {float(exact)}")
        if log is not None:
            ok = [e["payload"] for e in log.events("MODEL_CALL") if e["payload"]["status"] == "OK"]
            self.assertEqual(len(ok), len(calls))
            self.assertEqual(sum(p["usage"]["input_tokens"] for p in ok), router.usage["input_tokens"])
            self.assertEqual(sum(p["usage"]["output_tokens"] for p in ok), router.usage["output_tokens"])

    def test_cost_is_the_exact_sum_of_call_costs(self):
        cases = {
            "tiny calls": ((0.1, 0.4), [(4, 0)] * 1000),               # 4e-7 USD each
            "mixed": ((3.0, 15.0), [(1, 1), (0, 0), (17, 3), (100000, 2000), (2, 0)] * 40),
            "odd price": ((0.075, 0.3), [(7, 1), (13, 0), (1, 1)] * 300),
            "free": ((0.0, 0.0), [(50, 50)] * 10),
        }
        for label, (price, tokens) in cases.items():
            with self.subTest(label):
                log = EventLog(Path(self.tmp) / f"{label}.jsonl")
                provider = UsageProvider("p", [{"input_tokens": i, "output_tokens": o} for i, o in tokens],
                                         price=price)
                router = ModelRouter([provider], max_retries=0, event_log=log)
                done = []
                for i, o in tokens:
                    router.complete(REQ)
                    done.append((i, o, price[0], price[1]))
                self.assert_reconciled(router, done, log)

    def test_two_providers_reconcile_together(self):
        a = UsageProvider("a", [{"input_tokens": 3, "output_tokens": 1}] * 500, price=(0.1, 0.4))
        b = UsageProvider("b", [{"input_tokens": 9, "output_tokens": 2}] * 500, price=(3.0, 15.0))
        router = ModelRouter([a, b], routes={"x": ["a"], "y": ["b"]}, max_retries=0)
        done = []
        for n in range(500):
            router.complete(REQ, kind="x" if n % 2 else "y")
            done.append((3, 1, 0.1, 0.4) if n % 2 else (9, 2, 3.0, 15.0))
        self.assert_reconciled(router, done)

    def test_malformed_usage_is_invalid_response_not_a_crash(self):
        bad = {
            "usage missing": UsageProvider._MISSING,
            "usage null": None,
            "usage string": "12",
            "usage list": [3, 1],
            "negative input": {"input_tokens": -5, "output_tokens": 1},
            "negative output": {"input_tokens": 1, "output_tokens": -1},
            "bool count": {"input_tokens": True, "output_tokens": 0},
            "float count": {"input_tokens": 1.5, "output_tokens": 0},
            "string count": {"input_tokens": "3", "output_tokens": 0},
            "null count": {"input_tokens": None, "output_tokens": 0},
            "nan count": {"input_tokens": float("nan"), "output_tokens": 0},
        }
        for label, usage in bad.items():
            with self.subTest(label):
                log = EventLog(Path(self.tmp) / f"bad-{len(label)}-{label.replace(' ', '_')}.jsonl")
                broken = UsageProvider("broken", [usage])
                good = UsageProvider("good", [{"input_tokens": 2, "output_tokens": 1}], price=(1.0, 1.0))
                router = ModelRouter([broken, good], max_retries=0, event_log=log)
                try:
                    response = router.complete(REQ)
                except ProviderError as exc:     # pragma: no cover - reported as a failure below
                    self.fail(f"fallback not reached: {exc}")
                self.assertEqual(response["provider"], "good")
                self.assertEqual(response["attempts"][0], {"provider": "broken", "attempt": 1,
                                                           "error": "INVALID_RESPONSE"})
                self.assert_reconciled(router, [(2, 1, 1.0, 1.0)], log)

    def test_malformed_usage_alone_is_unavailable(self):
        router = ModelRouter([UsageProvider("broken", [{"input_tokens": -1, "output_tokens": 0}])], max_retries=0)
        with self.assertRaises(ProviderError) as ctx:
            router.complete(REQ)
        self.assertEqual(ctx.exception.kind, "UNAVAILABLE")
        self.assertIn("INVALID_RESPONSE", str(ctx.exception))
        self.assert_reconciled(router, [])

    def test_absent_count_fields_are_zero(self):
        router = ModelRouter([UsageProvider("p", [{}, {"input_tokens": 4}, {"output_tokens": 2}], price=(1.0, 2.0))],
                             max_retries=0)
        for _ in range(3):
            router.complete(REQ)
        self.assert_reconciled(router, [(0, 0, 1.0, 2.0), (4, 0, 1.0, 2.0), (0, 2, 1.0, 2.0)])

    def test_bad_price_is_refused_when_the_router_is_built(self):
        for price in [(-1.0, 0.0), (0.0, -0.5), (math.nan, 0.0), (0.0, math.inf), (True, 0.0), ("3", 0.0),
                      (None, 0.0), (1.0,), (1.0, 2.0, 3.0), 3.0, None, [1.0, 2.0]]:
            with self.subTest(price=price):
                with self.assertRaises(MAEPError):
                    ModelRouter([UsageProvider("p", [], price=price)])

    def test_good_prices_are_accepted(self):
        for price in [(0.0, 0.0), (3, 15), (0.075, 0.3), (1e3, 1e3)]:
            with self.subTest(price=price):
                ModelRouter([UsageProvider("p", [], price=price)])

    def test_price_is_the_one_checked_at_build_time(self):
        provider = UsageProvider("p", [{"input_tokens": 10, "output_tokens": 10}] * 2, price=(1.0, 1.0))
        router = ModelRouter([provider], max_retries=0)
        router.complete(REQ)
        provider.cost_per_mtok = (math.nan, -1.0)
        router.complete(REQ)
        self.assertTrue(math.isfinite(router.usage["cost_usd"]))
        self.assert_reconciled(router, [(10, 10, 1.0, 1.0)] * 2)


if __name__ == "__main__":
    unittest.main()
