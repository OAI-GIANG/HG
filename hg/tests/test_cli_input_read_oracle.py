"""WS-04 oracle: owner-supplied JSON read by the CLI has one meaning, and damage is located the way
the ledger reader sees it.

Surfaces: `hg bench --baseline FILE` (a regression gate), `hg eval --set FILE` (thresholds and
expected notes) and the bad-line list of `hg repair`. A repeated key reads last-value-wins in
`json.loads` while other readers keep the first; NaN compares False with everything, so a NaN
baseline hides every regression; a string or bool baseline either crashes the run or compares as
a number. Each such file must be refused with a reported problem (never a traceback, never a
silent pass), and `hg repair` must list exactly the lines the ledger reader refuses.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.assistant import evaluate
from hg.assistant.notes import Notebook
from hg.assistant.repair import inspect
from hg.verification.benchmark import BaselineError, load_baseline, verdict

REPO = Path(__file__).resolve().parents[2]
CLEAN_REPORT = {"metrics": {"pass_rate": 1.0, "completion_rate": 1.0, "correct_denial_rate": 1.0,
                            "recovery_rate": 1.0, "evidence_backed_closures": 1.0,
                            "unauthorized_effects": 0, "false_closures": 0},
                "failed_cases": [], "recovery": {"recovered": True, "reason": ""}}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-cli-oracle-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))

    def file(self, data, name="input.json"):
        path = self.tmp / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path


class BenchBaselineOracle(_Tmp):
    BAD = {
        "repeated metric": b'{"metrics": {"pass_rate": 2.0, "pass_rate": 0.5}}',
        "repeated metrics object": b'{"metrics": {"pass_rate": 2.0}, "metrics": {}}',
        "NaN": b'{"metrics": {"pass_rate": NaN}}',
        "Infinity": b'{"metrics": {"pass_rate": Infinity}}',
        "-Infinity": b'{"metrics": {"pass_rate": -Infinity}}',
        "string number": b'{"metrics": {"pass_rate": "1"}}',
        "bool": b'{"metrics": {"pass_rate": true}}',
        "list document": b'[]',
        "metrics not object": b'{"metrics": []}',
        "no metrics": b'{"pass_rate": 1.0}',
        "not UTF-8": b'{"metrics": {"pass_rate": 1.0}, "note": "\xff"}',
        "not JSON": b'{"metrics": ',
    }

    def test_ambiguous_or_unusable_baseline_is_refused(self):
        for label, data in self.BAD.items():
            with self.subTest(label):
                with self.assertRaises(BaselineError):
                    load_baseline(self.file(data))

    def test_missing_baseline_file_is_refused(self):
        with self.assertRaises(BaselineError):
            load_baseline(self.tmp / "absent.json")

    def test_controls(self):
        base = load_baseline(self.file(b'{"metrics": {"pass_rate": 0.5, "recovery_rate": null}, "x": 1}'))
        self.assertEqual(verdict(CLEAN_REPORT, base), [])
        worse = load_baseline(self.file(b'{"metrics": {"pass_rate": 2}}'))
        self.assertEqual(verdict(CLEAN_REPORT, worse), ["regression: pass_rate 2 -> 1.0"])

    def test_cli_reports_an_unusable_baseline_and_fails_before_running(self):
        for label in ("NaN", "string number", "not UTF-8"):
            with self.subTest(label):
                path = self.file(self.BAD[label])
                run = subprocess.run([sys.executable, "-m", "hg", "bench", "--baseline", str(path)],
                                     cwd=REPO, capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 1, run.stderr)
                self.assertNotIn("Traceback", run.stderr)
                out = json.loads(run.stdout)
                self.assertTrue(out["verdict"][0].startswith("baseline unusable:"), out)
                self.assertNotIn("metrics", out)          # the benchmark did not run


class EvalSpecOracle(_Tmp):
    SPEC = {"thresholds": {"grounded_rate": 0.9}, "notes": [], "questions": []}

    def test_ambiguous_spec_is_refused_before_any_model_call(self):
        bad = {
            "repeated threshold": b'{"thresholds": {"grounded_rate": 0.0, "grounded_rate": 0.9}, '
                                  b'"notes": [], "questions": []}',
            "NaN": b'{"thresholds": {"grounded_rate": NaN}, "notes": [], "questions": []}',
            "not UTF-8": b'{"thresholds": {}, "notes": [], "questions": [], "x": "\xff"}',
            "list document": b'[]',
        }
        for label, data in bad.items():
            with self.subTest(label):
                calls = []
                with self.assertRaises(evaluate.EvalSpecError):
                    evaluate.run(self.file(data), router_factory=lambda: calls.append(1))
                self.assertEqual(calls, [])

    def test_shipped_spec_loads(self):
        spec = evaluate.load_spec(REPO / "hg" / "assistant" / "eval_vi.json")
        self.assertIsInstance(spec["questions"], list)
        self.assertGreater(len(spec["questions"]), 0)


class RepairBadLinesOracle(_Tmp):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        nb = Notebook(self.home)
        for text in ("Ghi chú một.", "Ghi chú hai.", "Ghi chú ba."):
            nb.add(text, origin="test")
        self.path = self.home / "notes.jsonl"
        self.lines = self.path.read_bytes().split(b"\n")[:-1]

    def damage(self, number, line):
        lines = list(self.lines)
        lines[number - 1] = line
        self.path.write_bytes(b"\n".join(lines) + b"\n")

    def test_bad_lines_are_the_lines_the_ledger_reader_refuses(self):
        second = json.loads(self.lines[1])
        cases = {
            "repeated key": self.lines[1][:-1] + b', "kind": "x"}',
            "not UTF-8": self.lines[1][:-1] + b', "x": "\xff"}',
            "duplicate event_id": json.dumps(dict(json.loads(self.lines[0]), seq=second["seq"])).encode(),
            "blank": b"",
        }
        for label, line in cases.items():
            with self.subTest(label):
                self.damage(2, line)
                report = inspect(self.path)
                self.assertEqual(report["status"], "DAMAGED")
                self.assertEqual(report["bad_lines"], [2], report)

    def test_control_garbage_line(self):
        self.damage(1, b"garbage")
        self.assertEqual(inspect(self.path)["bad_lines"], [1])


if __name__ == "__main__":
    unittest.main()
