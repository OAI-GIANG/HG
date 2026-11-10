"""False-accept oracle for ledger reads (WS-04).

Each case starts from ledgers written through the runtime (``tasks.jsonl`` by the
TaskStore, ``actions.jsonl`` by an EventLog) and then damages the file or a record in it.
The expected outcome comes from how the case was built: the canonical writer can never
produce any of these files, so no read may return events and no restart may resume from
them. Controls show that the undamaged ledgers still load, so a reader that rejects
everything cannot satisfy the oracle. A read must also fail promptly: a special file
planted at a ledger path must not block runtime start or an operator status read.

Out of scope, by design: the ledger carries no hash chain or external anchor, so removing
whole records from the end of a ledger, or rewriting it consistently, is not detectable
from the file alone. Those are not cases here.
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hg.runtime import build_runtime
from hg.verification.evidence import EventLog
from maep import ledger
from maep.core import MAEPError
from maep.task_store import TaskStore

_PROMPT_SECONDS = 5.0


def _task(task_id):
    from maep.core import POLICY_VERSION
    return {
        "task_id": task_id,
        "objective": "Ledger read oracle",
        "scope": {"include": ["evidence/"], "exclude": []},
        "inputs": [],
        "outputs": [{"name": "evidence", "description": "candidate-bound evidence"}],
        "acceptance_criteria": [{
            "criterion_id": "AC-ORACLE-1",
            "description": "Evidence payload hash verifies",
            "mandatory": True,
            "evidence_types": ["ARTIFACT"],
        }],
        "evidence_requirements": ["payload hash and provenance"],
        "risks": [],
        "stop_conditions": ["scope exceeded"],
        "next_action": "review evidence",
        "state": "DRAFT",
        "policy_version": POLICY_VERSION,
    }


def _call_with_deadline(fn, release_path=None):
    """Run fn in a daemon thread; report whether it returned within the deadline.

    If it blocks on a FIFO, open the FIFO for writing so the reader is released and the
    thread can finish instead of outliving the test.
    """
    out = {}

    def run():
        try:
            out["value"] = fn()
        except Exception as exc:  # the oracle inspects the exception type below
            out["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_PROMPT_SECONDS)
    hung = thread.is_alive()
    if hung and release_path is not None:
        try:
            os.close(os.open(release_path, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        thread.join(_PROMPT_SECONDS)
    return hung, out


class LedgerReadOracleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name).resolve() / "runtime"
        runtime = build_runtime(self.workdir, [], allow_fixture_grants=True)
        runtime.orch.submit_task(_task("ORACLE-1"))
        runtime.orch.assess("ORACLE-1")
        runtime.orch.record_artifact_evidence(
            "ORACLE-1", b"raw evidence\n", evidence_type="ARTIFACT", source_ref="test://oracle/raw",
            candidate_ref="candidate:oracle", method="oracle_capture", result="CAPTURED",
            payload_kind="text/plain", limitations=["test fixture"])
        self.tasks = self.workdir / "tasks.jsonl"
        self.actions = self.workdir / "actions.jsonl"
        log = EventLog(self.actions)
        for n in range(3):
            log.append("ORACLE_ACTION", "ORACLE-1", {"n": n})
        self.tasks_bytes = self.tasks.read_bytes()
        self.actions_bytes = self.actions.read_bytes()
        self.assertGreaterEqual(self.tasks_bytes.count(b"\n"), 3)
        self.assertEqual(self.actions_bytes.count(b"\n"), 3)

    # -- helpers ------------------------------------------------------------------------
    def _readers(self, path, *, semantic_only=False):
        # read_events checks framing only (file type, encoding, records, unique event_id);
        # history (order, gaps, identity) is checked by the stores that replay it.
        readers = [] if semantic_only else [("read_events", lambda: ledger.read_events(path))]
        readers.append(("runtime restart", lambda: build_runtime(self.workdir, [], allow_fixture_grants=True)))
        if path == self.tasks:
            readers.append(("TaskStore.restore read-only",
                            lambda: TaskStore.restore(path, read_only=True)))
        else:
            readers.append(("EventLog read-only", lambda: EventLog(path, read_only=True).events()))
        return readers

    def _assert_never_accepted(self, path, label, *, release_path=None, semantic_only=False):
        for name, fn in self._readers(path, semantic_only=semantic_only):
            with self.subTest(ledger=path.name, case=label, read=name):
                hung, out = _call_with_deadline(fn, release_path)
                self.assertFalse(hung, f"{name} blocked instead of failing")
                self.assertNotIn("value", out, out)
                self.assertIsInstance(out.get("error"), MAEPError, out)

    def _restore(self, path):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        path.write_bytes(self.tasks_bytes if path == self.tasks else self.actions_bytes)
        os.chmod(path, 0o600)

    def _write_lines(self, path, lines):
        path.write_bytes(b"".join(lines))
        os.chmod(path, 0o600)

    def _lines(self, path):
        data = self.tasks_bytes if path == self.tasks else self.actions_bytes
        return data.splitlines(keepends=True)

    # -- control --------------------------------------------------------------------------
    def test_control_undamaged_ledgers_load(self):
        for path in (self.tasks, self.actions):
            for name, fn in self._readers(path):
                with self.subTest(ledger=path.name, read=name):
                    fn()
        self.assertEqual(len(EventLog(self.actions, read_only=True).events()), 3)
        restored = TaskStore.restore(self.tasks, read_only=True)
        self.assertIn("ORACLE-1", restored._records)

    # -- wrong file type or ownership bits --------------------------------------------------
    def test_non_regular_or_writable_ledger_is_never_accepted(self):
        for path in (self.tasks, self.actions):
            decoy = self.workdir.parent / f"decoy-{path.name}"
            decoy.write_bytes(path.read_bytes())
            os.chmod(decoy, 0o600)
            path.unlink()
            os.symlink(decoy, path)
            self._assert_never_accepted(path, "symlink to identical bytes")
            path.unlink()
            path.mkdir(mode=0o700)
            self._assert_never_accepted(path, "directory")
            self._restore(path)
            for mode in (0o620, 0o602):
                os.chmod(path, mode)
                self._assert_never_accepted(path, f"mode {oct(mode)}")
            self._restore(path)

    def test_fifo_at_ledger_path_fails_promptly(self):
        # Opening a FIFO for reading blocks until a writer appears. A reader that does not
        # open non-blocking would hang runtime start and every operator status read.
        for path in (self.tasks, self.actions):
            path.unlink()
            os.mkfifo(path, 0o600)
            self._assert_never_accepted(path, "fifo", release_path=path)
            self._restore(path)

    def test_fifo_at_ledger_path_does_not_block_an_append(self):
        self.actions.unlink()
        os.mkfifo(self.actions, 0o600)
        hung, out = _call_with_deadline(lambda: ledger.append_event(self.actions, {"event_id": "x"}),
                                        self.actions)
        self.assertFalse(hung, "append blocked on a FIFO at the ledger path")
        self.assertIsInstance(out.get("error"), ledger.LedgerAppendRefused, out)

    # -- damaged bytes -----------------------------------------------------------------------
    def test_damaged_framing_is_never_accepted(self):
        for path in (self.tasks, self.actions):
            lines = self._lines(path)
            cases = {
                "torn tail": [*lines[:-1], lines[-1].rstrip(b"\n")],
                "truncated mid-record": [*lines[:-1], lines[-1][: len(lines[-1]) // 2]],
                "blank line": [lines[0], b"\n", *lines[1:]],
                "invalid json": [lines[0], b"{not json}\n", *lines[1:]],
                "non-utf8 byte": [lines[0], lines[1][:-2] + b"\xff" + lines[1][-2:], *lines[2:]],
                "utf8 bom": [b"\xef\xbb\xbf" + lines[0], *lines[1:]],
                "non-object record": [lines[0], b"[1, 2]\n", *lines[1:]],
                "missing event_id": [lines[0], json.dumps({"kind": "X"}).encode() + b"\n", *lines[1:]],
                "duplicated record": [*lines, lines[-1]],
            }
            for label, damaged in cases.items():
                self._write_lines(path, damaged)
                self._assert_never_accepted(path, label)
            self._restore(path)

    def test_record_with_duplicate_keys_is_never_accepted(self):
        # json.loads keeps the last value of a repeated key, so a record such as
        # {"type": "BOGUS", ..., "type": "TRANSITION"} reads as the original event while
        # another parser may read the first value. The canonical writer serialises a dict
        # and can never repeat a key; such a record is ambiguous and must be refused.
        for path in (self.tasks, self.actions):
            lines = self._lines(path)
            key = "type" if path == self.tasks else "kind"
            first = lines[0]
            self.assertTrue(first.startswith(b"{"))
            shadowed = b'{"%s":"SHADOWED",' % key.encode() + first[1:]
            self._write_lines(path, [shadowed, *lines[1:]])
            self._assert_never_accepted(path, "duplicate top-level key")
            nested = first.replace(b'"event_id":', b'"event_id":"decoy","event_id":', 1)
            self._write_lines(path, [nested, *lines[1:]])
            self._assert_never_accepted(path, "duplicate event_id key")
            self._restore(path)

    # -- damaged history -----------------------------------------------------------------------
    def test_damaged_history_is_never_accepted(self):
        for path in (self.tasks, self.actions):
            lines = self._lines(path)
            cases = {
                "middle record removed": [lines[0], *lines[2:]],
                "records reordered": [lines[1], lines[0], *lines[2:]],
            }
            for label, damaged in cases.items():
                self._write_lines(path, damaged)
                self._assert_never_accepted(path, label, semantic_only=True)
            self._restore(path)

    def test_rewritten_identity_is_never_accepted(self):
        lines = self._lines(self.tasks)
        event = json.loads(lines[1])
        event["event_id"] = event["task_id"] + "@99"
        self._write_lines(self.tasks, [lines[0], json.dumps(event).encode() + b"\n", *lines[2:]])
        self._assert_never_accepted(self.tasks, "event_id/version disagree", semantic_only=True)
        self._restore(self.tasks)
        lines = self._lines(self.actions)
        event = json.loads(lines[1])
        event["seq"] = 7
        self._write_lines(self.actions, [lines[0], json.dumps(event).encode() + b"\n", *lines[2:]])
        self._assert_never_accepted(self.actions, "sequence rewritten", semantic_only=True)
        self._restore(self.actions)


if __name__ == "__main__":
    unittest.main()
