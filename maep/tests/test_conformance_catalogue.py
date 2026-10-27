"""MAEP traceability: every rule is mapped, and every mapping names a test that exists.

`CLAUDE.md` listed this check as proposed: "A test asserting every rule MAEP-001..028 is mapped
in maep/spec/MAEP_CONFORMANCE_TEST_CATALOGUE_V1.md". An unmapped rule is a normative claim with
no executable evidence, and a mapped test that no longer exists is a claim whose evidence has
rotted (MAEP-024). Both are test failures here instead of a review note.

The catalogue is parsed as text and the test modules are parsed with `ast`; nothing is imported,
so this check cannot pass because an import worked, and cannot fail because an unrelated module
did not.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "maep" / "spec" / "MAEP_CONFORMANCE_TEST_CATALOGUE_V1.md"
TEST_ROOTS = (ROOT / "maep" / "tests", ROOT / "hg" / "tests", ROOT / ".claude" / "hooks")
RULES = tuple("MAEP-%03d" % number for number in range(1, 29))

_PY_FILE = re.compile(r"[\w./-]+\.py\b")
_DOTTED = re.compile(r"\b([A-Za-z_]\w*)\.([a-z_]\w*)\b")
_CLASS = re.compile(r"\b([A-Za-z_]\w*Tests)\b")
_RULE = re.compile(r"^MAEP-(\d{3})$")
_NUMBER = re.compile(r"^\d{3}$")


def catalogue_rows():
    """Rows of the catalogue table as [test id, anchor, rules, expected]."""
    rows = []
    for line in CATALOGUE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| T-"):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def rules_in(cell):
    """Rule IDs in one cell; `MAEP-001, 002` continues the MAEP- prefix."""
    found, last = set(), None
    for token in re.split(r"[,\s]+", cell):
        match = _RULE.match(token)
        if match:
            last = token
            found.add(token)
            continue
        if last is not None and _NUMBER.match(token):
            found.add("MAEP-" + token)
    return found


def covered_rules():
    rules = set()
    for row in catalogue_rows():
        rules |= rules_in(row[2])
    return rules


def test_index():
    """class name -> method names, read from the test sources without importing them."""
    index = {}
    for root in TEST_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = {item.name for item in node.body
                               if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
                    index.setdefault(node.name, set()).update(methods)
    return index


def anchors_in(cell):
    """(class, method or None) pairs a catalogue anchor cell cites."""
    text = _PY_FILE.sub(" ", cell)
    found, seen = [], set()
    for pair in _DOTTED.findall(text) + [(name, None) for name in _CLASS.findall(text)]:
        if pair not in seen:
            seen.add(pair)
            found.append(pair)
    return found


class ConformanceCatalogueTests(unittest.TestCase):
    def test_the_catalogue_is_present_and_not_empty(self):
        rows = catalogue_rows()
        self.assertGreater(len(rows), 28)                 # at least one row per rule
        self.assertEqual(len({row[0] for row in rows}), len(rows), "test IDs must be unique")

    def test_every_rule_001_to_028_is_mapped_to_a_test(self):
        unmapped = [rule for rule in RULES if rule not in covered_rules()]
        self.assertEqual(unmapped, [])

    def test_no_row_maps_a_rule_outside_the_registry(self):
        self.assertEqual(sorted(covered_rules() - set(RULES)), [])

    def test_every_cited_test_anchor_exists_in_the_suite(self):
        index = test_index()
        self.assertGreater(len(index), 50)                # the index is real, not empty
        missing = []
        for row in catalogue_rows():
            for name, method in anchors_in(row[1]):
                if name not in index:
                    missing.append(f"{row[0]}: class {name} is not in the suite")
                elif method is not None and method not in index[name]:
                    missing.append(f"{row[0]}: {name}.{method} is not in the suite")
        self.assertEqual(missing, [])

    def test_every_row_states_an_anchor_and_an_expected_result(self):
        for row in catalogue_rows():
            with self.subTest(row=row[0]):
                self.assertEqual(len(row), 4, row)
                self.assertRegex(row[0], r"^T-\d{3}$")
                self.assertTrue(row[1], "anchor is empty")
                self.assertTrue(row[3], "expected result is empty")


class StateTableParityTests(unittest.TestCase):
    """MAEP-007/026: the spec table and the implementation must be one definition.

    Two definitions of the allowed edges is exactly the drift the acceptance checklist forbids;
    this pins them together in both directions, so neither side can move alone.
    """

    SPEC = ROOT / "maep" / "spec" / "STATE_TRANSITION_TABLE_V1.md"
    WORD = re.compile(r"\b[A-Z][A-Z_]{2,}\b")

    @classmethod
    def spec_states(cls):
        for line in cls.SPEC.read_text(encoding="utf-8").splitlines():
            if line.startswith("States:"):
                return set(cls.WORD.findall(line))
        raise AssertionError("the state table no longer declares its states")

    @classmethod
    def spec_edges(cls):
        edges = set()
        for line in cls.SPEC.read_text(encoding="utf-8").splitlines():
            if not line.startswith("- ") or "->" not in line:
                continue
            if "only by creating a new linked task" in line:
                continue        # continuation creates a task; it is not a mutation of this one
            source, _, target = line[2:].partition("->")
            for src in cls.WORD.findall(source):
                for dst in cls.WORD.findall(target):
                    edges.add((src, dst))
        return edges

    def test_spec_and_code_declare_the_same_states(self):
        from maep.core import STATES
        self.assertEqual(self.spec_states(), set(STATES))

    def test_spec_and_code_allow_the_same_edges(self):
        from maep.core import TRANSITIONS
        code = {(src, dst) for src, targets in TRANSITIONS.items() for dst in targets}
        self.assertEqual(self.spec_edges() - code, set(), "the spec allows an edge the code does not")
        self.assertEqual(code - self.spec_edges(), set(), "the code allows an edge the spec does not")


if __name__ == "__main__":
    unittest.main()
