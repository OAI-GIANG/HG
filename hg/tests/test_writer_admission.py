"""D3-P1 regression coverage for cross-process writer admission; synthetic paths only."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from maep.admission import RuntimeWriterSession
from maep.core import MAEPError
from hg.assistant.home import locked
from hg.assistant.config import save as save_config
from hg.memory.store import MemoryStore
from hg.verification.evidence import EventLog
from maep.task_store import TaskStore
from maep.core import POLICY_VERSION


ROOT = Path(__file__).resolve().parents[2]


def _run_pair(script, args, barrier, *, timeout=15):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    procs = [subprocess.Popen([sys.executable, "-B", "-c", script, *(str(x) for x in args),
                               str(barrier), str(i)],
                              cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for i in range(2)]
    try:
        deadline = time.monotonic() + 10
        for i in range(2):
            ready = Path(str(barrier) + f".ready{i}")
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.005)
            if not ready.exists():
                raise AssertionError(f"worker {i} did not reach the synchronized start barrier")
        barrier.write_text("go", encoding="ascii")
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                raise AssertionError(f"worker exit={proc.returncode}\nstdout={out}\nstderr={err}")
            results.append(json.loads(out.strip().splitlines()[-1]))
        return results
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            if proc.poll() is None:
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired: proc.kill()
            if proc.stdout: proc.stdout.close()
            if proc.stderr: proc.stderr.close()


def _draft(task_id):
    return {
        "task_id": task_id, "objective": "synthetic admission race",
        "scope": {"include": ["maep/"], "exclude": []}, "inputs": [],
        "outputs": [{"name": "result", "description": "synthetic"}],
        "acceptance_criteria": [{"criterion_id": "AC-1", "description": "one writer wins",
                                 "mandatory": True, "evidence_types": ["TEST_RESULT"]}],
        "evidence_requirements": ["synthetic result"], "risks": [],
        "stop_conditions": ["race detected"], "next_action": "verify",
        "state": "DRAFT", "policy_version": POLICY_VERSION,
    }


class CrossProcessLedgerTests(unittest.TestCase):
    def test_eventlog_sequence_is_unique_across_processes(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-eventlog-") as td:
            path, barrier = Path(td) / "events.jsonl", Path(td) / "go"
            script = r'''
import json, sys, time
from hg.verification.evidence import EventLog
path, barrier, worker = sys.argv[1:4]
log = EventLog(path)
open(barrier+".ready"+worker,"w").close()
while not __import__("os").path.exists(barrier): time.sleep(.005)
event = log.append("RACE", "T-RACE", {"worker": __import__("os").getpid()})
print(json.dumps({"seq": event["seq"], "event_id": event["event_id"]}))
'''
            result = _run_pair(script, [path], barrier)
            seqs = sorted(x["seq"] for x in result)
            self.assertEqual(seqs, [1, 2])
            self.assertEqual(len({x["event_id"] for x in result}), 2)
            self.assertEqual([e["seq"] for e in EventLog(path).events()], [1, 2])

    def test_taskstore_duplicate_task_event_id_has_single_winner_across_processes(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-taskstore-") as td:
            path, barrier = Path(td) / "tasks.jsonl", Path(td) / "go"
            script = r'''
import json, sys, time
from maep.task_store import TaskStore
from maep.policy import PolicyEvaluator
from maep.core import POLICY_VERSION
path, barrier, worker = sys.argv[1:4]
store = TaskStore(path, policy_evaluator=PolicyEvaluator([], lambda *_: False))
task = {"task_id":"T-RACE","objective":"synthetic","scope":{"include":["maep/"],"exclude":[]},"inputs":[],
"outputs":[{"name":"x","description":"y"}],"acceptance_criteria":[{"criterion_id":"AC-1","description":"x","mandatory":True,"evidence_types":["TEST_RESULT"]}],
"evidence_requirements":["x"],"risks":[],"stop_conditions":["x"],"next_action":"x","state":"DRAFT","policy_version":POLICY_VERSION}
open(barrier+".ready"+worker,"w").close()
while not __import__("os").path.exists(barrier): time.sleep(.005)
try:
    store.create_task(task); result="CREATED"
except Exception as exc:
    result=type(exc).__name__
print(json.dumps({"result":result}))
'''
            result = _run_pair(script, [path], barrier)
            self.assertEqual(sorted(x["result"] for x in result), ["CREATED", "MAEPError"])
            restored = TaskStore.restore(path, policy_evaluator=None)
            self.assertEqual(restored.snapshot("T-RACE")["version"], 1)

    def test_memory_conflict_decision_is_serialized_across_processes(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-memory-") as td:
            path, barrier = Path(td) / "memory.jsonl", Path(td) / "go"
            script = r'''
import json, sys, time, os
from hg.memory.store import MemoryStore, MemoryConflict
path, barrier, worker = sys.argv[1:4]
store = MemoryStore(path)
value = str(os.getpid())
open(barrier+".ready"+worker,"w").close()
while not os.path.exists(barrier): time.sleep(.005)
try:
    store.remember(layer="SEMANTIC",kind="FACT",subject="same.subject",content="value "+value,
        value=value,source="EVIDENCE",source_ref="synthetic",evidence_refs=["E-SYN"])
    result="CREATED"
except MemoryConflict:
    result="CONFLICT"
print(json.dumps({"result":result}))
'''
            result = _run_pair(script, [path], barrier)
            self.assertEqual(sorted(x["result"] for x in result), ["CONFLICT", "CREATED"])
            events = EventLog(path).events()
            self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))

    def test_direct_runtime_store_construction_requires_lifetime_session(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-runtime-admission-") as td:
            root = Path(td) / "state"
            root.mkdir()
            marker = root / ".writer.lock"
            marker.touch(mode=0o600)
            path = root / "tasks.jsonl"
            with self.assertRaises(MAEPError):
                TaskStore(path)
            with self.assertRaises(MAEPError):
                EventLog(root / "actions.jsonl")
            with self.assertRaises(MAEPError):
                MemoryStore(root / "memory.jsonl")
            fd = os.open(marker, os.O_RDWR)
            session = RuntimeWriterSession(root, fd)
            try:
                TaskStore(path, writer_session=session)
                EventLog(root / "actions.jsonl", writer_session=session)
                MemoryStore(root / "memory.jsonl", writer_session=session)
            finally:
                session.close()


class AssistantHomeAdmissionTests(unittest.TestCase):
    def test_memory_writer_waits_for_home_exclusive_lock(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-home-lock-") as td:
            home = Path(td) / "assistant"
            home.mkdir(mode=0o700)
            barrier = Path(td) / "started"
            ready, release = threading.Event(), threading.Event()
            outcome = {}

            def hold():
                with locked(home, exclusive=True):
                    ready.set()
                    release.wait(4)

            holder = threading.Thread(target=hold)
            holder.start()
            self.assertTrue(ready.wait(2))
            script = r'''
import json, sys
from hg.memory.store import MemoryStore
home, started = sys.argv[1:3]
open(started,"w").close()
store=MemoryStore(home+"/notes.jsonl")
store.remember(layer="SEMANTIC",kind="NOTE",subject="synthetic",content="hello",
 source="USER",source_ref="synthetic")
print(json.dumps({"result":"WRITTEN"}))
'''
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.Popen([sys.executable, "-B", "-c", script, str(home), str(barrier)],
                                    cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 3
            while not barrier.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(barrier.exists())
            time.sleep(.25)
            self.assertFalse(proc.poll() is not None, "writer should be waiting behind HOME exclusive lock")
            self.assertFalse((home / "notes.jsonl").exists())
            release.set()
            holder.join(3)
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual(json.loads(out.strip())["result"], "WRITTEN")

    def test_config_save_waits_for_home_exclusive_lock(self):
        with tempfile.TemporaryDirectory(prefix="hg-d3-config-lock-") as td:
            home = Path(td) / "assistant"
            home.mkdir(mode=0o700)
            config = {"model": "synthetic-model"}
            ready, release = threading.Event(), threading.Event()

            def hold():
                with locked(home, exclusive=True):
                    ready.set()
                    release.wait(4)

            holder = threading.Thread(target=hold)
            holder.start()
            self.assertTrue(ready.wait(2))
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
            script = r'''
import json,sys
from hg.assistant.config import save,DEFAULTS
conf=dict(DEFAULTS); conf["model"]="synthetic-model"
save(sys.argv[1],conf); print(json.dumps({"result":"SAVED"}))
'''
            proc = subprocess.Popen([sys.executable, "-B", "-c", script, str(home)],
                                    cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(.25)
            self.assertIsNone(proc.poll())
            self.assertFalse((home / "config.json").exists())
            release.set()
            holder.join(3)
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual(json.loads(out.strip())["result"], "SAVED")
            self.assertTrue((home / "config.json").is_file())

    def test_shared_home_lease_is_never_upgraded_in_place(self):
        # Two threads each holding SH and waiting for EX would deadlock; refuse at once instead.
        from hg.assistant.home import Busy
        with tempfile.TemporaryDirectory(prefix="hg-g1-home-upgrade-") as td:
            home = Path(td) / "assistant"
            home.mkdir(mode=0o700)
            with locked(home, exclusive=False):
                started = time.monotonic()
                with self.assertRaises(Busy):
                    with locked(home, exclusive=True, wait_s=5):
                        pass
                self.assertLess(time.monotonic() - started, 1.0)
            with locked(home, exclusive=True):           # EX then SH in one thread is a reuse
                with locked(home, exclusive=False):
                    pass


class ReadOnlyStateViewTests(unittest.TestCase):
    """G1: operators and the switch precheck read service-owned state without writer admission,
    and a read-only view can never write."""

    def _service_state(self, td):
        root = Path(td) / "state"
        root.mkdir(mode=0o700)
        marker = root / ".writer.lock"
        marker.touch(mode=0o600)
        session = RuntimeWriterSession(root, os.open(marker, os.O_RDWR))
        try:
            store = TaskStore(root / "tasks.jsonl", writer_session=session)
            store.create_task(_draft("T-1"))
            EventLog(root / "actions.jsonl", writer_session=session).append("SYNTHETIC_NOTE", "T-1",
                                                                             {"note": "synthetic"})
            MemoryStore(root / "memory.jsonl", writer_session=session).remember(
                layer="SEMANTIC", kind="NOTE", subject="synthetic", content="hello",
                source="USER", source_ref="synthetic")
        finally:
            session.close()                 # the service exited; its .writer.lock marker stays
        return root

    def _bytes(self, root):
        return {p.name: p.read_bytes() for p in sorted(root.glob("*.jsonl"))}

    def test_status_and_health_read_state_owned_by_a_service(self):
        from hg.__main__ import status
        from hg.ops import health
        with tempfile.TemporaryDirectory(prefix="hg-g1-readonly-ops-") as td:
            root = self._service_state(td)
            before = self._bytes(root)
            report = status(root)
            self.assertEqual([t["task_id"] for t in report["tasks"]], ["T-1"])
            checks = {c["name"]: c["status"] for c in health(root)["checks"]}
            self.assertEqual((checks["task ledger"], checks["action ledger"], checks["memory"]),
                             ("OK", "OK", "OK"))
            self.assertNotIn("FAILING", checks.values())
            self.assertEqual(self._bytes(root), before)

    def test_read_only_views_refuse_every_write_and_leave_the_ledgers_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-readonly-writes-") as td:
            root = self._service_state(td)
            before = self._bytes(root)
            log = EventLog(root / "actions.jsonl", read_only=True)
            self.assertEqual(len(log.events()), 1)
            with self.assertRaisesRegex(MAEPError, "read-only"):
                log.append("SYNTHETIC_NOTE", "T-1", {"note": "second"})
            tasks = TaskStore.restore(root / "tasks.jsonl", read_only=True)
            self.assertEqual(tasks.snapshot("T-1")["version"], 1)
            with self.assertRaisesRegex(MAEPError, "read-only"):
                tasks.create_task(_draft("T-2"))
            with self.assertRaisesRegex(MAEPError, "read-only"):
                tasks.claim_writer()
            with self.assertRaisesRegex(MAEPError, "read-only"):
                tasks.apply_transition("T-1", "ASSESSED", expected_version=1)
            memory = MemoryStore(root / "memory.jsonl", read_only=True)
            for layer in ("SEMANTIC", "WORKING"):
                with self.assertRaisesRegex(MAEPError, "read-only"):
                    memory.remember(layer=layer, kind="NOTE", subject="x", content="y", source="USER",
                                    source_ref="synthetic", task_id="T-1")
            with self.assertRaisesRegex(MAEPError, "read-only"):
                memory.retract(memory.all_records()[0]["memory_id"], reason="synthetic")
            with self.assertRaisesRegex(MAEPError, "restored view"):
                TaskStore(root / "tasks.jsonl", read_only=True)
            # A writable store still needs the lifetime session.
            with self.assertRaises(MAEPError):
                TaskStore.restore(root / "tasks.jsonl")
            self.assertEqual(self._bytes(root), before)


class AppendOutcomeTests(unittest.TestCase):
    """F13: an append whose bytes reached the file but whose call failed (fsync/close error)
    leaves the outcome unknown to the caller; the next append must still number from disk."""

    def _flaky_once(self):
        from maep import ledger as ledger_mod
        real, calls = ledger_mod._append_unlocked, {"n": 0}

        def flaky(fd, event):
            real(fd, event)
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("injected failure after the bytes reached the file")
        return mock.patch.object(ledger_mod, "_append_unlocked", flaky)

    def test_eventlog_failure_after_write_never_reuses_a_sequence_number(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-append-outcome-") as td:
            path = Path(td) / "events.jsonl"
            log = EventLog(path)
            with self._flaky_once():
                with self.assertRaises(OSError):
                    log.append("SYNTHETIC", None, {"n": 1})
                log.append("SYNTHETIC", None, {"n": 2})          # same process, same instance
            self.assertEqual([(e["seq"], e["payload"]["n"]) for e in EventLog(path).events()], [(1, 1), (2, 2)])

    def test_memory_outcome_write_failure_keeps_the_memory_ledger_loadable(self):
        with tempfile.TemporaryDirectory(prefix="hg-g1-memory-outcome-") as td:
            path = Path(td) / "memory.jsonl"
            memory = MemoryStore(path)
            snapshot = {"task": {"task_id": "T-1", "state": "CLOSED_VERIFIED", "objective": "synthetic"},
                        "version": 7, "result": None, "evidence": {}}
            with self._flaky_once():
                with self.assertRaises(OSError):
                    memory.record_task_outcome(snapshot)            # best-effort caller swallows this
                memory.remember(layer="SEMANTIC", kind="NOTE", subject="next", content="later write",
                                source="USER", source_ref="synthetic")
            reloaded = MemoryStore(path)                           # what `hg serve` does at startup
            self.assertEqual(sorted(r["subject"] for r in reloaded.all_records()), ["next", "task:T-1"])


class LedgerLockTests(unittest.TestCase):
    def test_nested_read_reuses_the_hold_and_upgrade_fails_fast(self):
        from maep.ledger import append_event, ledger_lock, read_events
        with tempfile.TemporaryDirectory(prefix="hg-g1-ledger-nest-") as td:
            path = Path(td) / "events.jsonl"
            append_event(path, {"event_id": "E-1"})
            started = time.monotonic()
            with ledger_lock(path, exclusive=True, create=True):
                self.assertEqual([e["event_id"] for e in read_events(path)], ["E-1"])
            with ledger_lock(path, exclusive=False):
                with self.assertRaisesRegex(MAEPError, "cannot upgrade"):
                    append_event(path, {"event_id": "E-2"})
            self.assertLess(time.monotonic() - started, 2.0)      # no self-wait on a second flock
            append_event(path, {"event_id": "E-2"})               # the hold was released cleanly
            self.assertEqual([e["event_id"] for e in read_events(path)], ["E-1", "E-2"])

    def test_ledger_writable_by_another_user_is_refused_but_readable_mode_is_not(self):
        from maep.ledger import append_event, read_events
        with tempfile.TemporaryDirectory(prefix="hg-g1-ledger-mode-") as td:
            path = Path(td) / "events.jsonl"
            append_event(path, {"event_id": "E-1"})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)       # created private
            os.chmod(path, 0o644)                                        # e.g. a copy under umask 022
            self.assertEqual(len(read_events(path)), 1)
            for mode in (0o620, 0o602):
                os.chmod(path, mode)
                with self.assertRaisesRegex(MAEPError, "no other user can write"):
                    read_events(path)
                with self.assertRaisesRegex(MAEPError, "no other user can write"):
                    append_event(path, {"event_id": "E-2"})


if __name__ == "__main__":
    unittest.main()
