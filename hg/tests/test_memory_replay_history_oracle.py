"""Oracle: a memory ledger loads only if MemoryStore's own API could have written it (WS-04).

MemoryStore (C-14) promises that nothing is overwritten (MAEP-015): supersede and retract
append status events and history() returns every version. The owner's notes (`hg note`,
`hg ask`, `hg serve` chat) are MemoryStore records. The oracle is the write API itself:
`remember` writes a new memory_id with status ACTIVE and version 1 (or the superseded
record's version + 1, same subject, record still ACTIVE) and never persists WORKING
memory; `retract` writes status RETRACTED with a reason, only for an ACTIVE record; the
store owns the MEMORY_* event kinds and writes no others (other writers may share the
ledger: notes.jsonl also holds NOTE_TRUST, which the store ignores). A ledger that breaks one of these rules (a forged or
hand-edited line, a foreign writer) must be refused when it is opened, as TaskStore
refuses an inconsistent task history -- never replayed into a different state (a
forgotten note back to ACTIVE, a note's text replaced with its history lost).

Controls: every history the API writes reopens to the same records; competing ACTIVE
records on one subject still load and are reported in restore_conflicts (designed).
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from maep.core import MAEPError
from hg.assistant.notes import Notebook
from hg.memory.store import MemoryStore

REPO = Path(__file__).resolve().parents[2]


def _append_raw(path, kind, payload):
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    event = {"event_id": uuid.uuid4().hex, "seq": len(events) + 1, "kind": kind, "task_id": None,
             "at": events[-1]["at"], "payload": payload}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _seed(path):
    """Two notes written through the API; the second is forgotten (retracted)."""
    store = MemoryStore(path)
    kept = store.remember(layer="SEMANTIC", kind="NOTE", subject="wifi", content="mật khẩu ở tủ",
                          source="USER", source_ref="hg note")
    gone = store.remember(layer="SEMANTIC", kind="NOTE", subject="door", content="mã cửa cũ",
                          source="USER", source_ref="hg note")
    store.retract(gone["memory_id"], reason="owner forgot it")
    return kept, gone


def _write(record, **changes):
    forged = copy.deepcopy(record)
    forged.update(changes)
    return {"record": forged}


# name -> (kind, payload builder(kept, gone))
FORGED = {
    "same_memory_id_new_text": ("MEMORY_WRITE", lambda k, g: _write(k, content="forged text")),
    "same_memory_id_of_forgotten_note": ("MEMORY_WRITE", lambda k, g: _write(g, status="ACTIVE")),
    "write_status_retracted": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1",
                                                                   status="RETRACTED")),
    "write_status_bogus": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1",
                                                               status="BOGUS")),
    "write_version_not_1": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1", version=7)),
    "write_version_bool": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1", version=True)),
    "supersede_unknown": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", supersedes="M-none",
                                                              version=2)),
    "supersede_forgotten_note": ("MEMORY_WRITE", lambda k, g: _write(g, memory_id="M-x1",
                                                                     supersedes=g["memory_id"], version=2)),
    "supersede_other_subject": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="other",
                                                                    supersedes=k["memory_id"], version=2)),
    "supersede_wrong_version": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1",
                                                                    supersedes=k["memory_id"], version=5)),
    "persisted_working_memory": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1",
                                                                     layer="WORKING", kind="PREFERENCE",
                                                                     source="SYSTEM", task_id="T-1")),
    "empty_memory_id": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="", subject="s1")),
    "status_reactivates_forgotten": ("MEMORY_STATUS", lambda k, g: {"memory_id": g["memory_id"],
                                                                     "status": "ACTIVE", "reason": "x"}),
    "status_bogus": ("MEMORY_STATUS", lambda k, g: {"memory_id": k["memory_id"], "status": "BOGUS",
                                                    "reason": "x"}),
    "status_without_reason": ("MEMORY_STATUS", lambda k, g: {"memory_id": k["memory_id"],
                                                             "status": "RETRACTED"}),
    "status_blank_reason": ("MEMORY_STATUS", lambda k, g: {"memory_id": k["memory_id"],
                                                           "status": "RETRACTED", "reason": " "}),
    "status_on_retracted": ("MEMORY_STATUS", lambda k, g: {"memory_id": g["memory_id"],
                                                           "status": "RETRACTED", "reason": "again"}),
    "status_payload_not_object": ("MEMORY_STATUS", lambda k, g: ["RETRACTED"]),
    "write_payload_not_object": ("MEMORY_WRITE", lambda k, g: "record"),
    "write_record_not_object": ("MEMORY_WRITE", lambda k, g: {"record": ["x"]}),
    "write_record_missing_field": ("MEMORY_WRITE", lambda k, g: {"record": {
        key: v for key, v in dict(k, memory_id="M-x1", subject="s1").items() if key != "source_ref"}}),
    "write_layer_unhashable": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1",
                                                                   layer=["SEMANTIC"])),
    "write_evidence_refs_number": ("MEMORY_WRITE", lambda k, g: _write(k, memory_id="M-x1", subject="s1",
                                                                       evidence_refs=5)),
    "unknown_event_kind": ("MEMORY_PURGE", lambda k, g: {"memory_id": k["memory_id"]}),
}


class ForgedHistoryRefused(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _forged_ledger(self, name):
        path = self.root / f"{name}.jsonl"
        kept, gone = _seed(path)
        kind, build = FORGED[name]
        _append_raw(path, kind, build(kept, gone))
        return path

    def test_store_refuses_every_forged_history(self):
        for name in FORGED:
            path = self._forged_ledger(name)
            for read_only in (True, False):
                with self.subTest(case=name, read_only=read_only):
                    with self.assertRaises(MAEPError):
                        MemoryStore(path, read_only=read_only)

    def test_notes_and_cli_refuse_forged_notes_ledger(self):
        for name in ("same_memory_id_new_text", "status_reactivates_forgotten", "same_memory_id_of_forgotten_note",
                     "unknown_event_kind"):
            with self.subTest(case=name):
                home = self.root / f"home-{name}"
                notebook = Notebook(home)
                notes = home / "notes.jsonl"
                kept, gone = _seed(notes)
                os.chmod(notes, 0o600)
                kind, build = FORGED[name]
                _append_raw(notes, kind, build(kept, gone))
                with self.assertRaises(MAEPError):
                    notebook.active()
                env = dict(os.environ, HG_HOME=str(home), PYTHONPATH=str(REPO))
                env.pop("HG_MODEL_PROVIDER", None)
                run = subprocess.run([sys.executable, "-m", "hg", "note", "list", "--json"], cwd=str(REPO),
                                     env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 78, run.stdout + run.stderr)
                self.assertNotIn("forged text", run.stdout)
                self.assertNotIn("mã cửa cũ", run.stdout)
                self.assertNotIn("Traceback", run.stderr)


class GenuineHistoryLoads(unittest.TestCase):
    """Controls: what the API writes reopens unchanged."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "memory.jsonl"

    def test_api_histories_reopen_identically(self):
        store = MemoryStore(self.path)
        a = store.remember(layer="SEMANTIC", kind="NOTE", subject="n", content="v1", source="USER",
                           source_ref="hg note")
        b = store.remember(layer="SEMANTIC", kind="NOTE", subject="n", content="v2", source="USER",
                           source_ref="hg note", supersedes=a["memory_id"])
        store.remember(layer="SEMANTIC", kind="NOTE", subject="n", content="v3", source="USER",
                       source_ref="hg note", supersedes=b["memory_id"])
        h = store.remember(layer="SEMANTIC", kind="HYPOTHESIS", subject="h", content="maybe", source="INFERENCE",
                           source_ref="planner", limitations=["unverified"])
        store.promote(h["memory_id"], evidence_refs=["E-1"], source_ref="test")
        d = store.remember(layer="PROJECT", kind="DECISION", subject="mode", content="offline",
                           value={"b": 1, "a": [1, 2]}, source="USER", source_ref="cli")
        store.retract(d["memory_id"], reason="changed mind")
        store.remember(layer="EPISODIC", kind="EVENT", subject="task:T-1", content="ended", source="SYSTEM",
                       source_ref="tasks.jsonl:T-1@3", task_id="T-1")
        store.remember(layer="WORKING", kind="PREFERENCE", subject="w", content="scratch", source="SYSTEM",
                       source_ref="x", task_id="T-1")
        expected = store.all_records()
        for read_only in (True, False):
            with self.subTest(read_only=read_only):
                reopened = MemoryStore(self.path, read_only=read_only)
                self.assertEqual(reopened.all_records(), expected)
                self.assertEqual([r["version"] for r in reopened.history("n")], [1, 2, 3])
                self.assertEqual(reopened.restore_conflicts, [])

    def test_events_of_other_writers_are_ignored(self):
        store = MemoryStore(self.path)
        note = store.remember(layer="SEMANTIC", kind="NOTE", subject="n", content="v", source="USER",
                              source_ref="hg note")
        _append_raw(self.path, "NOTE_TRUST", {"memory_id": note["memory_id"], "reason": "owner"})
        _append_raw(self.path, "ASK", {"q": "x"})
        self.assertEqual(MemoryStore(self.path, read_only=True).all_records(), store.all_records())

    def test_absent_ledger_is_empty(self):
        self.assertEqual(MemoryStore(self.path, read_only=True).all_records(), [])

    def test_competing_active_records_still_load_and_are_reported(self):
        store = MemoryStore(self.path)
        first = store.remember(layer="SEMANTIC", kind="FACT", subject="port", content="8080", source="EVIDENCE",
                               source_ref="probe", evidence_refs=["E-1"])
        _append_raw(self.path, "MEMORY_WRITE", _write(first, memory_id="M-x2", content="9090"))
        reopened = MemoryStore(self.path, read_only=True)
        self.assertEqual(reopened.restore_conflicts,
                         [{"subject": "port", "memory_ids": sorted([first["memory_id"], "M-x2"])}])


if __name__ == "__main__":
    unittest.main()
