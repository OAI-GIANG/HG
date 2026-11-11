"""WS-04 oracle: a memory record's value is stored exactly, and equal values are equal.

MemoryStore (C-14) persists records as JSON in an append-only ledger. A record's `value`
must therefore be one that JSON stores exactly: `remember()` returns the record it wrote,
and that record must be what a reopened store reads back. A value JSON would change (a
tuple becomes a list, a non-string key becomes a string) must be refused before any byte
is written, in every layer, rather than stored as something else.

The conflict rule (a FACT/DECISION that contradicts the ACTIVE record on the same subject
is refused) must compare values by meaning: the same value given again, with its object
keys in another order or after a reopen (the ledger writes keys sorted), is not a
contradiction. Controls: values that really differ still conflict, and exact values
(nested objects/lists, non-ASCII text, numbers, booleans, null) round-trip unchanged.
"""
import math
import tempfile
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.memory.store import MemoryConflict, MemoryStore

INEXACT = {
    "tuple": (1, 2),
    "nested tuple": {"a": [1, (2, 3)]},
    "int key": {1: "x"},
    "bool key": {True: "x"},
    "none key": {None: "x"},
    "float key": {1.5: "x"},
    "set": {1, 2},
    "nan": math.nan,
    "bytes": b"ab",
}

EXACT = {
    "object": {"b": {"y": [1, 2.5, None, True, False], "x": "chào"}, "a": -0.0},
    "list": [[], {}, "", 0, 10 ** 30, -1e-300],
    "string": "Tiếng Việt   ok",
    "int": 7,
    "none": None,
}


def decision(store, value, **kw):
    return store.remember(layer="PROJECT", kind="DECISION", subject=kw.pop("subject", "cfg"),
                          content=kw.pop("content", "mode"), value=value, source="USER",
                          source_ref="cli", **kw)


class MemoryValueOracle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "memory.jsonl"
        self.store = MemoryStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def size(self):
        return self.path.stat().st_size if self.path.exists() else 0

    def test_inexact_value_refused_before_write(self):
        for name, value in INEXACT.items():
            for layer, task_id in (("PROJECT", None), ("WORKING", "T-1")):
                with self.subTest(value=name, layer=layer):
                    before = self.size()
                    with self.assertRaises(MAEPError):
                        self.store.remember(layer=layer, kind="DECISION" if layer == "PROJECT" else "PREFERENCE",
                                            subject=f"s-{name}", content="c", value=value,
                                            source="USER", source_ref="cli", task_id=task_id)
                    self.assertEqual(self.size(), before)
                    self.assertEqual(self.store.working("T-1"), [])
        self.assertEqual(MemoryStore(self.path, read_only=True).all_records(), [])

    def test_exact_value_round_trips(self):
        for name, value in EXACT.items():
            with self.subTest(value=name):
                written = decision(self.store, value, subject=f"s-{name}")
                reopened = MemoryStore(self.path, read_only=True).get(written["memory_id"])
                self.assertEqual(reopened, written)
                self.assertEqual(reopened["value"], value)
                self.assertEqual(type(reopened["value"]), type(value))

    def test_same_value_other_key_order_is_not_a_conflict(self):
        decision(self.store, {"b": 2, "a": {"d": 1, "c": [1]}})
        decision(self.store, {"b": 2, "a": {"d": 1, "c": [1]}})          # given again, same order
        decision(self.store, {"a": {"c": [1], "d": 1}, "b": 2})          # same value, keys reordered
        reopened = MemoryStore(self.path)
        self.assertEqual(reopened.restore_conflicts, [])
        self.assertEqual(reopened.conflicts(), [])
        decision(reopened, {"b": 2, "a": {"d": 1, "c": [1]}})             # after a reopen
        self.assertEqual(len(reopened.active(subject="cfg")), 4)

    def test_supersede_with_reordered_value(self):
        first = decision(self.store, {"b": 1, "a": 1})
        second = decision(self.store, {"a": 1, "b": 1}, supersedes=first["memory_id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual([r["memory_id"] for r in self.store.active(subject="cfg")], [second["memory_id"]])

    def test_different_values_still_conflict(self):
        cases = [({"a": 1}, {"a": 2}), ({"a": 1}, {"a": 1, "b": None}), ([1, 2], [2, 1]),
                 (1, "1"), (True, 1), (None, "x"), ({"a": [1]}, {"a": [1.5]})]
        for i, (first, second) in enumerate(cases):
            with self.subTest(first=first, second=second):
                subject = f"c-{i}"
                kept = decision(self.store, first, subject=subject)
                before = self.size()
                with self.assertRaises(MemoryConflict):
                    decision(self.store, second, subject=subject)
                self.assertEqual(self.size(), before)
                self.assertEqual([r["memory_id"] for r in self.store.active(subject=subject)],
                                 [kept["memory_id"]])


if __name__ == "__main__":
    unittest.main()
