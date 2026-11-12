"""Oracle: an evaluation file is used only if every value is one `hg eval` can score (WS-04).

The documented contract (hg/assistant/cli.py `eval`, hg/assistant/evaluate.py `load_spec`): a file
that cannot be read with one meaning is refused before the model is contacted. Before this oracle
`load_spec` checked only that the file is one JSON object, so a wrong value was accepted and failed
later or, worse, scored: a missing threshold or an `expect` naming no note raised KeyError after
every question had been asked; a threshold given as a string raised TypeError at the verdict; an
answerable question with `key: []` counted as a correct fact whatever the model said; two notes with
the same subject either stopped the run (NoteConflict) or, with the same text, mapped two keys to
one note so either one counted as grounded; a threshold `true` or above 1 decided the verdict.

Oracle: the fields `evaluate.run` and `evaluate.score` read and the values they can use, and what
`Notebook.add` accepts for a note. deploy/termux/eval_resumable.py reads the file the same way.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.assistant import evaluate

ROOT = Path(__file__).resolve().parents[2]

GOOD = {
    "schema": "test",
    "scoring": {"thresholds": {"fact_rate": 0.8, "grounded_rate": 0.7, "abstain_rate": 0.8,
                               "notes_shown_s_max": 2.0, "first_sentence_p50_s_max": 15.0}},
    "notes": [
        {"key": "shoes", "subject": "giay-be-na", "content": "Giày của bé Na cỡ 28."},
        {"key": "trash", "subject": "xe-rac", "content": "Xe rác đi qua lúc 18 giờ 30."},
    ],
    "questions": [
        {"id": "Q1", "question": "Giày của bé Na cỡ mấy?", "expect": "shoes", "key": ["28"]},
        {"id": "Q2", "question": "Xe rác đi qua lúc mấy giờ?", "expect": "trash", "key": ["18", "30"]},
        {"id": "Q3", "question": "Mật khẩu wifi nhà mình là gì?", "expect": None, "key": None},
    ],
}


def _set(path, value):
    def mutate(spec):
        target = spec
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
    return mutate


def _drop(path):
    def mutate(spec):
        target = spec
        for part in path[:-1]:
            target = target[part]
        del target[path[-1]]
    return mutate


T = ("scoring", "thresholds")
BAD = {
    "no scoring": _drop(("scoring",)),
    "scoring not object": _set(("scoring",), []),
    "no thresholds": _drop(T),
    "thresholds not object": _set(T, [0.8]),
    **{f"no threshold {name}": _drop(T + (name,)) for name in GOOD["scoring"]["thresholds"]},
    "rate as string": _set(T + ("fact_rate",), "0.8"),
    "rate true": _set(T + ("grounded_rate",), True),
    "rate null": _set(T + ("abstain_rate",), None),
    "rate above 1": _set(T + ("fact_rate",), 1.5),
    "rate below 0": _set(T + ("abstain_rate",), -0.1),
    "seconds zero": _set(T + ("notes_shown_s_max",), 0),
    "seconds negative": _set(T + ("first_sentence_p50_s_max",), -1),
    "seconds as string": _set(T + ("first_sentence_p50_s_max",), "15"),
    "no notes": _drop(("notes",)),
    "notes not list": _set(("notes",), {"shoes": "x"}),
    "notes empty": _set(("notes",), []),
    "note not object": _set(("notes", 0), "Giày cỡ 28"),
    "note without key": _drop(("notes", 0, "key")),
    "note key not string": _set(("notes", 0, "key"), 1),
    "note key empty": _set(("notes", 0, "key"), ""),
    "note without subject": _drop(("notes", 0, "subject")),
    "note subject not string": _set(("notes", 0, "subject"), 5),
    "note subject Notebook refuses": _set(("notes", 0, "subject"), "auto:x"),
    "note subject with slash": _set(("notes", 0, "subject"), "a/b"),
    "note without content": _drop(("notes", 0, "content")),
    "note content not string": _set(("notes", 0, "content"), ["x"]),
    "note content blank": _set(("notes", 0, "content"), "   "),
    "note content too long": _set(("notes", 0, "content"), "x" * 4001),
    "repeated note key": _set(("notes", 1, "key"), "shoes"),
    "repeated subject": _set(("notes", 1, "subject"), "giay-be-na"),
    "repeated subject after normalising": _set(("notes", 1, "subject"), "Giay Be Na"),
    "repeated subject and text": lambda s: s["notes"].__setitem__(1, dict(s["notes"][0], key="other")),
    "no questions": _drop(("questions",)),
    "questions not list": _set(("questions",), {}),
    "questions empty": _set(("questions",), []),
    "question not object": _set(("questions", 0), "Q1"),
    "question without id": _drop(("questions", 0, "id")),
    "question id not string": _set(("questions", 0, "id"), 1),
    "question id empty": _set(("questions", 0, "id"), ""),
    "repeated question id": _set(("questions", 1, "id"), "Q1"),
    "question without text": _drop(("questions", 0, "question")),
    "question text not string": _set(("questions", 0, "question"), None),
    "question text blank": _set(("questions", 0, "question"), "  "),
    "question without expect": _drop(("questions", 0, "expect")),
    "expect names no note": _set(("questions", 0, "expect"), "car"),
    "expect not string": _set(("questions", 0, "expect"), 0),
    "answerable without key": _drop(("questions", 0, "key")),
    "answerable key null": _set(("questions", 0, "key"), None),
    "answerable key empty": _set(("questions", 0, "key"), []),
    "answerable key string": _set(("questions", 0, "key"), "28"),
    "answerable key item not string": _set(("questions", 0, "key"), [28]),
    "answerable key item blank": _set(("questions", 1, "key"), ["18", " "]),
    "unanswerable key not list": _set(("questions", 2, "key"), "x"),
}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-eval-oracle-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self, spec, name="spec.json"):
        path = self.tmp / name
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path


def _variant(mutate):
    spec = copy.deepcopy(GOOD)
    mutate(spec)
    return spec


class EvalSpecValueOracle(_Tmp):
    def test_unusable_spec_is_refused_by_load_spec(self):
        for label, mutate in BAD.items():
            with self.subTest(label):
                with self.assertRaises(evaluate.EvalSpecError):
                    evaluate.load_spec(self.file(_variant(mutate)))

    def test_unusable_spec_is_refused_before_any_model_call(self):
        for label, mutate in BAD.items():
            with self.subTest(label):
                calls = []
                with self.assertRaises(evaluate.EvalSpecError):
                    evaluate.run(self.file(_variant(mutate)), router_factory=lambda: calls.append(1))
                self.assertEqual(calls, [])

    def test_refusal_names_the_field(self):
        cases = {"no threshold fact_rate": "fact_rate", "expect names no note": "Q1",
                 "repeated subject": "giay-be-na", "answerable key empty": "Q1",
                 "repeated question id": "Q1", "note content too long": "shoes"}
        for label, needle in cases.items():
            with self.subTest(label):
                with self.assertRaises(evaluate.EvalSpecError) as caught:
                    evaluate.load_spec(self.file(_variant(BAD[label])))
                self.assertIn(needle, str(caught.exception))


class EvalSpecControls(_Tmp):
    def test_good_spec_loads_unchanged(self):
        self.assertEqual(evaluate.load_spec(self.file(GOOD)), GOOD)

    def test_shipped_specs_load(self):
        for name in ("eval_vi.json", "eval_vi_select.json", "eval_vi_v2.json", "eval_vi_v3.json"):
            with self.subTest(name):
                spec = evaluate.load_spec(ROOT / "hg" / "assistant" / name)
                self.assertGreater(len(spec["questions"]), 0)

    def test_usable_variants_load(self):
        usable = {
            "extra fields": lambda s: s.update(language="vi", author="owner", rule="frozen"),
            "integer thresholds": _set(T + ("fact_rate",), 1),
            "rate zero": _set(T + ("abstain_rate",), 0),
            "unanswerable key list": _set(("questions", 2, "key"), []),
            "unanswerable without key": _drop(("questions", 2, "key")),
            "only answerable": lambda s: s["questions"].pop(2),
            "note with no question": lambda s: s["notes"].append(
                {"key": "spare", "subject": "khac", "content": "Ghi chú không được hỏi."}),
        }
        for label, mutate in usable.items():
            with self.subTest(label):
                evaluate.load_spec(self.file(_variant(mutate)))


class EvalSpecCli(_Tmp):
    def _hg(self, *argv):
        home = self.tmp / "home"
        env = dict(os.environ, HG_HOME=str(home), NO_COLOR="1", PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-m", "hg", *argv], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=60)

    def test_cli_refuses_unusable_spec_with_input_exit(self):
        for label in ("no threshold fact_rate", "expect names no note", "answerable key empty", "repeated subject"):
            with self.subTest(label):
                result = self._hg("eval", "--set", str(self.file(_variant(BAD[label]))))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Tệp đánh giá không dùng được", result.stdout)
                self.assertNotIn("Traceback", result.stderr)


class EvalResumableReadsTheSameWay(_Tmp):
    def test_harness_uses_load_spec(self):
        source = (ROOT / "deploy" / "termux" / "eval_resumable.py").read_text(encoding="utf-8")
        self.assertIn("load_spec(", source)

    def test_harness_refuses_unusable_spec_before_creating_notes(self):
        work = self.tmp / "work"
        env = dict(os.environ, HOME=str(self.tmp), PYTHONPATH="")
        result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "deploy" / "termux" / "eval_resumable.py"),
                                 str(ROOT), str(self.file(_variant(BAD["answerable key empty"]))), str(work),
                                 str(self.tmp / "out.json")], env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evaluation file not usable", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(work.exists())
        self.assertFalse((self.tmp / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
