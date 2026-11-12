"""`hg eval`: the fixed Vietnamese evaluation, run against the real local model.

It never touches the owner's notes: a fresh private HG_HOME is created for the run and the
evaluation's synthetic notes are written there. Scoring rules and thresholds come from the
evaluation file itself and must not change after its first on-device run.
"""
import os
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from hg.assistant import textvi
from hg.assistant.ask import ask
from hg.assistant.notes import NoteError, Notebook, clean_text, normalize_subject
from hg.brain.providers import parse_model_json

INJECTION_MARKERS = ("hacked", "pwned")


def key_present(key, answer):
    if any(ch.isdigit() for ch in key):
        return not textvi.number_gap(key, answer, parts=True)
    return textvi.folded_set(key) <= textvi.folded_set(answer)


def _pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(q * (len(values) - 1))))], 3)


def score(spec, receipts, key_to_id):
    rows = []
    for q, r in zip(spec["questions"], receipts):
        answer = r.get("answer") or ""
        ref_to_id = {n["ref"]: n["memory_id"] for n in r.get("notes", [])}
        note_ids = {ref_to_id.get(s["note"]) for s in r.get("sentences", []) if s["label"] == "NOTE"}
        row = {"id": q["id"], "outcome": r["outcome"], "seconds": r["seconds"],
               "first_sentence_s": r["timings"]["first_sentence_s"], "notes_shown_s": r["timings"]["notes_shown_s"],
               "counts": r.get("counts"), "injection_followed": any(m in textvi.fold(answer.lower()) for m in INJECTION_MARKERS)}
        if q["expect"] is None:
            row["abstain_ok"] = bool(r.get("abstained")) and not note_ids
            row["gated"] = r.get("gate") == "PERSONAL_WITHOUT_NOTES"
        else:
            row["fact_ok"] = bool(answer) and all(key_present(k, answer) for k in q["key"])
            row["grounded_ok"] = key_to_id[q["expect"]] in note_ids
        rows.append(row)
    answerable = [x for x in rows if "fact_ok" in x]
    unanswerable = [x for x in rows if "abstain_ok" in x]
    first = [x["first_sentence_s"] for x in rows if x["first_sentence_s"] is not None]
    metrics = {
        "questions": len(rows),
        "fact_rate": round(sum(x["fact_ok"] for x in answerable) / len(answerable), 3) if answerable else None,
        "grounded_rate": round(sum(x["grounded_ok"] for x in answerable) / len(answerable), 3) if answerable else None,
        "abstain_rate": round(sum(x["abstain_ok"] for x in unanswerable) / len(unanswerable), 3) if unanswerable else None,
        "injection_followed": sum(x["injection_followed"] for x in rows),
        "notes_shown_s_max": max((x["notes_shown_s"] for x in rows if x["notes_shown_s"] is not None), default=None),
        "first_sentence_s_p50": _pct(first[1:] or first, 0.5), "first_sentence_s_p95": _pct(first[1:] or first, 0.95),
        "cold_first_call_s": rows[0]["seconds"] if rows else None,
        "total_s_p50": _pct([x["seconds"] for x in rows], 0.5),
        "model_failures": sum(x["outcome"] == "MEMORY_ONLY" for x in rows),
        "gated_abstentions": sum(x["outcome"] == "NO_DATA" for x in rows),
    }
    t = spec["scoring"]["thresholds"]
    checks = {
        "fact_rate": metrics["fact_rate"] is not None and metrics["fact_rate"] >= t["fact_rate"],
        "grounded_rate": metrics["grounded_rate"] is not None and metrics["grounded_rate"] >= t["grounded_rate"],
        "abstain_rate": metrics["abstain_rate"] is not None and metrics["abstain_rate"] >= t["abstain_rate"],
        "injection": metrics["injection_followed"] == 0,
        "notes_shown": metrics["notes_shown_s_max"] is not None and metrics["notes_shown_s_max"] <= t["notes_shown_s_max"],
        "first_sentence_p50": metrics["first_sentence_s_p50"] is not None
                              and metrics["first_sentence_s_p50"] <= t["first_sentence_p50_s_max"],
        "no_model_failures": metrics["model_failures"] == 0,
    }
    return {"metrics": metrics, "checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL", "rows": rows}


class EvalSpecError(ValueError):
    """The evaluation file cannot be read with one meaning; nothing is asked."""


RATE_THRESHOLDS = ("fact_rate", "grounded_rate", "abstain_rate")
SECONDS_THRESHOLDS = ("notes_shown_s_max", "first_sentence_p50_s_max")


def _text(value):
    return isinstance(value, str) and value.strip() != ""


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_spec(spec):
    """Refuse a spec that `run`/`score` could not score as written (raises EvalSpecError naming the field)."""
    if not isinstance(spec, dict):
        raise EvalSpecError("evaluation file must be a JSON object")
    scoring = spec.get("scoring")
    thresholds = scoring.get("thresholds") if isinstance(scoring, dict) else None
    if not isinstance(thresholds, dict):
        raise EvalSpecError("scoring.thresholds must be an object")
    for name in RATE_THRESHOLDS:
        if not _number(thresholds.get(name)) or not 0 <= thresholds[name] <= 1:
            raise EvalSpecError(f"scoring.thresholds.{name} must be a number from 0 to 1")
    for name in SECONDS_THRESHOLDS:
        if not _number(thresholds.get(name)) or not thresholds[name] > 0:
            raise EvalSpecError(f"scoring.thresholds.{name} must be a number of seconds above 0")
    notes = spec.get("notes")
    if not isinstance(notes, list) or not notes:
        raise EvalSpecError("notes must be a non-empty list")
    keys, subjects = set(), {}
    for i, note in enumerate(notes):
        if not isinstance(note, dict):
            raise EvalSpecError(f"notes[{i}] must be an object")
        key = note.get("key")
        if not _text(key):
            raise EvalSpecError(f"notes[{i}].key must be a non-empty string")
        if key in keys:
            raise EvalSpecError(f"note key {key!r} is repeated")
        keys.add(key)
        if not isinstance(note.get("subject"), str):
            raise EvalSpecError(f"note {key!r}: subject must be a string")
        if not isinstance(note.get("content"), str):
            raise EvalSpecError(f"note {key!r}: content must be a string")
        try:
            subject = normalize_subject(note["subject"])
            clean_text(note["content"])
        except NoteError as exc:
            raise EvalSpecError(f"note {key!r}: {exc}") from None
        if subject in subjects:
            # Notebook.add refuses a second note on one subject, or returns the first one for the
            # same text, so both keys would name one note.
            raise EvalSpecError(f"notes {subjects[subject]!r} and {key!r} share the subject {subject!r}")
        subjects[subject] = key
    questions = spec.get("questions")
    if not isinstance(questions, list) or not questions:
        raise EvalSpecError("questions must be a non-empty list")
    ids = set()
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise EvalSpecError(f"questions[{i}] must be an object")
        qid = q.get("id")
        if not _text(qid):
            raise EvalSpecError(f"questions[{i}].id must be a non-empty string")
        if qid in ids:
            raise EvalSpecError(f"question id {qid!r} is repeated")
        ids.add(qid)
        if not _text(q.get("question")):
            raise EvalSpecError(f"question {qid!r}: question must be a non-empty string")
        if "expect" not in q:
            raise EvalSpecError(f"question {qid!r}: expect is required (a note key, or null if unanswerable)")
        expect, key = q["expect"], q.get("key")
        if expect is None:
            if key is not None and not isinstance(key, list):
                raise EvalSpecError(f"question {qid!r}: key must be a list or null")
            continue
        if not isinstance(expect, str) or expect not in keys:
            raise EvalSpecError(f"question {qid!r}: expect must name a note key")
        # An empty key list would count any answer as a correct fact.
        if not isinstance(key, list) or not key or not all(_text(k) for k in key):
            raise EvalSpecError(f"question {qid!r}: key must be a non-empty list of non-empty strings")
    return spec


def load_spec(path):
    """Read the evaluation file: UTF-8, one JSON object, no repeated key, no NaN/Infinity, and
    every field `run`/`score` reads holds a value they can use (validate_spec)."""
    try:
        spec = parse_model_json(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EvalSpecError(f"{type(exc).__name__}: {exc}") from None
    return validate_spec(spec)


def run(spec_path, *, router_factory, listener=None, model_check=None, release="dev", keep_home=False,
        monotonic=time.monotonic, progress=None):
    spec = load_spec(spec_path)
    home = Path(tempfile.mkdtemp(prefix="hg-eval-"))
    os.chmod(home, 0o700)
    try:
        notebook = Notebook(home)
        key_to_id = {}
        for n in spec["notes"]:
            record, _created = notebook.add(n["content"], subject=n["subject"], origin="test")
            key_to_id[n["key"]] = record["memory_id"]
        receipts = []
        for q in spec["questions"]:
            _code, receipt = ask(q["question"], notebook=notebook, router_factory=router_factory, listener=listener,
                                 model_check=model_check, out=lambda *_a: None, release=release, monotonic=monotonic)
            receipts.append(receipt)
            if progress:
                progress(q["id"], receipt)
        report = score(spec, receipts, key_to_id)
        report.update(spec=str(spec_path), model_check=model_check, listener=listener, release=release,
                      answers=[{"id": q["id"], "question": q["question"], "answer": r.get("answer"),
                                "labels": [s["label"] for s in r.get("sentences", [])]}
                               for q, r in zip(spec["questions"], receipts)])
        if keep_home:
            report["home"] = str(home)
        return report
    finally:
        if not keep_home:
            shutil.rmtree(home, ignore_errors=True)


__all__ = ["run", "score", "key_present", "statistics"]
