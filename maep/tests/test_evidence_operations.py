"""EC07 part 2 (T-EC07-FIX part 2): logical evidence-operation idempotency.

Acceptance criteria:
- the same operation_id with the same canonical evidence payload returns the committed
  evidence_id and appends nothing, even with a stale expected_version, a re-minted
  evidence_id or a new collected_at;
- the same operation_id with a different payload is a conflict and appends nothing;
- an operation_id is unique within one task; other tasks are independent;
- the operation_id is stored next to the evidence in the event data, never inside it;
- legacy evidence without an operation_id is never correlated with an operation;
- replay survives restore; a task holding one operation twice refuses to restore;
- an append that wrote the event but then failed is reported as IN_DOUBT, not as
  "state unchanged"; a retry with the same operation_id replays it exactly once;
- a torn ledger tail still fails closed (C1);
- replay keeps the writer capability, read-only and terminal-state checks.

Fixtures are synthetic ledgers in temporary directories.
"""
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from maep import task_store as task_store_module
from maep.core import MAEPError, POLICY_VERSION
from maep.ledger import append_event, read_events
from maep.policy import PolicyEvaluator
from maep.task_store import TaskStore
from maep.tests.test_task_store import Clock, closure, draft_task, evidence, gate, grant, request

REPO_ROOT = Path(__file__).resolve().parents[2]


def ev(evidence_id="E-1", *, result="PASS", collected_at="2026-10-23T10:05:00Z"):
    record = evidence(evidence_id)
    record["result"] = result
    record["collected_at"] = collected_at
    return record


def outcome_unknown_type():
    return getattr(task_store_module, "LedgerOutcomeUnknown", None)


class EvidenceOperationCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "tasks.jsonl"
        self.clock = Clock()
        self.evaluator = PolicyEvaluator([grant(), grant("T-2")], lambda condition, req: True)
        self.store = TaskStore(self.ledger, policy_evaluator=self.evaluator, clock=self.clock)
        self.store.create_task(draft_task())

    def restore(self, **kwargs):
        return TaskStore.restore(self.ledger, policy_evaluator=self.evaluator, clock=self.clock, **kwargs)

    def version(self, task_id="T-1", store=None):
        return (store or self.store).snapshot(task_id)["version"]

    def evidence_events(self, task_id=None):
        return [e for e in read_events(self.ledger)
                if e["type"] == "EVIDENCE_RECORDED" and (task_id is None or e["task_id"] == task_id)]

    def record(self, record, operation_id, *, task_id="T-1", expected_version=None, store=None):
        store = store or self.store
        if expected_version is None:
            expected_version = self.version(task_id, store)
        return store.record_evidence(task_id, record, expected_version=expected_version,
                                     operation_id=operation_id)


class ReplayAndConflictTests(EvidenceOperationCase):
    def test_same_operation_same_payload_is_replayed_without_a_second_event(self):
        before = self.version()
        self.assertEqual(self.record(ev("E-1"), "op-1"), "E-1")
        committed = self.store.snapshot("T-1")

        # A retry re-mints the evidence_id and the collection time and still carries the old
        # expected_version: it must return the committed record and append nothing.
        again = self.record(ev("E-2", collected_at="2026-10-23T10:06:00Z"), "op-1", expected_version=before)

        self.assertEqual(again, "E-1")
        self.assertEqual(len(self.evidence_events()), 1)
        self.assertEqual(self.store.snapshot("T-1"), committed)
        self.assertEqual(set(committed["evidence"]), {"E-1"})

    def test_same_operation_different_payload_conflicts_and_appends_nothing(self):
        self.record(ev("E-1", result="PASS"), "op-1")
        committed, size = self.store.snapshot("T-1"), self.ledger.stat().st_size

        with self.assertRaisesRegex(MAEPError, "operation_id .*conflict"):
            self.record(ev("E-2", result="FAIL"), "op-1")

        self.assertEqual(self.ledger.stat().st_size, size)
        self.assertEqual(self.store.snapshot("T-1"), committed)

    def test_operation_id_is_scoped_to_one_task(self):
        self.store.create_task(draft_task("T-2"))
        self.assertEqual(self.record(ev("E-1"), "op-1"), "E-1")
        self.assertEqual(self.record(ev("E-9"), "op-1", task_id="T-2"), "E-9")
        self.assertEqual(len(self.evidence_events("T-1")), 1)
        self.assertEqual(len(self.evidence_events("T-2")), 1)

    def test_operation_id_is_stored_next_to_the_evidence_not_inside_it(self):
        self.record(ev("E-1"), "op-1")
        (event,) = self.evidence_events()
        self.assertEqual(event["data"], {"evidence": ev("E-1"), "operation_id": "op-1"})
        self.assertNotIn("operation_id", self.store.snapshot("T-1")["evidence"]["E-1"])

    def test_evidence_without_an_operation_keeps_the_previous_behaviour(self):
        self.store.record_evidence("T-1", ev("E-1"), expected_version=self.version())
        (event,) = self.evidence_events()
        self.assertEqual(event["data"], {"evidence": ev("E-1")})
        with self.assertRaisesRegex(MAEPError, "evidence_id already recorded"):
            self.store.record_evidence("T-1", ev("E-1"), expected_version=self.version())

    def test_legacy_evidence_without_an_operation_is_never_correlated(self):
        self.store.record_evidence("T-1", ev("E-1"), expected_version=self.version())
        # Same observed content, but the first record carries no operation_id: it is a
        # separate record, never matched by content or time.
        self.assertEqual(self.record(ev("E-2"), "op-1"), "E-2")
        self.assertEqual(len(self.evidence_events()), 2)

    def test_invalid_operation_ids_are_refused_before_any_write(self):
        for bad in ["", " ", "a" * 129, "op\n1", "op/1", "op 1", 5, b"op-1", True]:
            with self.subTest(operation_id=bad):
                with self.assertRaisesRegex(MAEPError, "operation_id"):
                    self.record(ev("E-1"), bad)
        self.assertEqual(self.evidence_events(), [])

    def test_longest_valid_operation_id_is_accepted(self):
        op = "a" * 128
        self.assertEqual(self.record(ev("E-1"), op), "E-1")
        self.assertEqual(self.record(ev("E-2"), op), "E-1")


class RestoreTests(EvidenceOperationCase):
    def test_replay_survives_restore(self):
        before = self.version()
        self.record(ev("E-1"), "op-1")
        restored = self.restore()
        self.assertEqual(self.record(ev("E-2"), "op-1", expected_version=before, store=restored), "E-1")
        self.assertEqual(len(self.evidence_events()), 1)

    def test_conflict_survives_restore(self):
        self.record(ev("E-1", result="PASS"), "op-1")
        restored = self.restore()
        with self.assertRaisesRegex(MAEPError, "operation_id .*conflict"):
            self.record(ev("E-2", result="FAIL"), "op-1", store=restored)

    def test_task_holding_one_operation_twice_refuses_to_restore(self):
        self.record(ev("E-1"), "op-1")
        version = self.version() + 1
        # Only reachable by editing the ledger: a well-formed event repeating the operation.
        append_event(self.ledger, {
            "event_id": f"T-1@{version}", "type": "EVIDENCE_RECORDED", "task_id": "T-1", "version": version,
            "policy_version": self.evidence_events()[0]["policy_version"],
            "recorded_at": "2026-10-23T10:07:00+00:00",
            "data": {"evidence": ev("E-2"), "operation_id": "op-1"},
        })
        with self.assertRaisesRegex(MAEPError, "operation_id .*twice"):
            self.restore()

    def test_torn_tail_fails_closed_even_for_a_replay(self):
        self.record(ev("E-1"), "op-1")
        with self.ledger.open("ab") as stream:
            stream.write(b'{"event_id":"T-1@99"}')
        size = self.ledger.stat().st_size
        with self.assertRaisesRegex(MAEPError, "torn ledger tail"):
            self.record(ev("E-2"), "op-1", expected_version=2)
        self.assertEqual(self.ledger.stat().st_size, size)


class AppendOutcomeTests(EvidenceOperationCase):
    def test_append_error_after_the_write_is_in_doubt_not_unchanged(self):
        def append_then_fail(path, event):
            append_event(path, event)
            raise OSError("fsync failed after the write")

        failing = self.restore(ledger_append=append_then_fail)
        with self.assertRaises(MAEPError) as caught:
            failing.record_evidence("T-1", ev("E-1"), expected_version=self.version(store=failing))

        kind = outcome_unknown_type()
        self.assertIsNotNone(kind, "task_store must define LedgerOutcomeUnknown")
        self.assertIsInstance(caught.exception, kind)
        self.assertNotIn("state unchanged", str(caught.exception))
        self.assertEqual(len(self.evidence_events()), 1)

    def test_append_error_before_any_write_reports_state_unchanged(self):
        def fail_before_write(path, event):
            raise OSError("no space left before the write")

        failing = self.restore(ledger_append=fail_before_write)
        with self.assertRaisesRegex(MAEPError, "state unchanged") as caught:
            failing.record_evidence("T-1", ev("E-1"), expected_version=self.version(store=failing))
        kind = outcome_unknown_type()
        if kind is not None:
            self.assertNotIsInstance(caught.exception, kind)
        self.assertEqual(self.evidence_events(), [])

    def test_lost_acknowledgement_then_retry_with_same_operation_is_recorded_once(self):
        def append_then_fail(path, event):
            append_event(path, event)
            raise OSError("acknowledgement lost after the write")

        before = self.version()
        failing = self.restore(ledger_append=append_then_fail)
        with self.assertRaises(MAEPError):
            self.record(ev("E-1"), "op-1", store=failing)

        retried = self.record(ev("E-2", collected_at="2026-10-23T10:09:00Z"), "op-1",
                              expected_version=before, store=self.restore())
        self.assertEqual(retried, "E-1")
        self.assertEqual(len(self.evidence_events()), 1)

    def test_failure_before_write_then_retry_with_same_operation_appends_once(self):
        def fail_before_write(path, event):
            raise OSError("no space left before the write")

        failing = self.restore(ledger_append=fail_before_write)
        with self.assertRaisesRegex(MAEPError, "state unchanged"):
            self.record(ev("E-1"), "op-1", store=failing)
        self.assertEqual(self.record(ev("E-2"), "op-1", store=self.restore()), "E-2")
        self.assertEqual(len(self.evidence_events()), 1)

    def test_process_killed_right_after_the_append_then_retry_replays(self):
        child = (
            "import os, sys\n"
            "from maep.ledger import append_event\n"
            "from maep.policy import PolicyEvaluator\n"
            "from maep.task_store import TaskStore\n"
            "from maep.tests.test_task_store import evidence, grant\n"
            "def append_then_die(path, event):\n"
            "    append_event(path, event)\n"
            "    os._exit(0)\n"
            "store = TaskStore.restore(sys.argv[1], policy_evaluator=PolicyEvaluator([grant()], lambda c, r: True),\n"
            "                          ledger_append=append_then_die)\n"
            "store.record_evidence('T-1', evidence('E-1'), expected_version=store.snapshot('T-1')['version'],\n"
            "                      operation_id='op-crash')\n"
            "sys.exit(3)\n"
        )
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
        before = self.version()
        done = subprocess.run([sys.executable, "-c", child, str(self.ledger)], cwd=REPO_ROOT, env=env,
                              capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace")[-800:])
        self.assertEqual(len(self.evidence_events()), 1)

        replayed = self.record(ev("E-7", collected_at="2026-10-23T10:10:00Z"), "op-crash",
                               expected_version=before, store=self.restore())
        self.assertEqual(replayed, "E-1")
        self.assertEqual(len(self.evidence_events()), 1)


class ConcurrencyTests(EvidenceOperationCase):
    def test_two_writers_racing_the_same_operation_leave_one_event(self):
        barrier = threading.Barrier(2, timeout=20)

        def append_after_both_read(path, event):
            barrier.wait()
            return append_event(path, event)

        stores = [self.restore(ledger_append=append_after_both_read) for _ in range(2)]
        before = self.version()
        results, errors = {}, {}

        def run(index):
            try:
                results[index] = self.record(ev(f"E-{index}"), "op-race", expected_version=before,
                                             store=stores[index])
            except MAEPError as exc:
                errors[index] = exc

        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertFalse(any(t.is_alive() for t in threads))

        self.assertEqual(len(self.evidence_events()), 1)
        self.assertEqual((len(results), len(errors)), (1, 1))
        (winner,) = results.values()
        (loser_index,) = errors
        self.assertIn("state unchanged", str(errors[loser_index]))
        # The loser retries its own operation: it replays the winner's record.
        retried = self.record(ev(f"E-{loser_index}"), "op-race", expected_version=before, store=self.restore())
        self.assertEqual(retried, winner)
        self.assertEqual(len(self.evidence_events()), 1)

    def test_threads_sharing_one_store_record_the_operation_once(self):
        before = self.version()
        start = threading.Barrier(4, timeout=20)
        results = []

        def run(index):
            start.wait()
            results.append(self.record(ev(f"E-{index}"), "op-shared", expected_version=before))

        threads = [threading.Thread(target=run, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(len(self.evidence_events()), 1)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(results), 4)


class GuardTests(EvidenceOperationCase):
    def test_replay_still_requires_the_claimed_writer(self):
        self.record(ev("E-1"), "op-1")
        self.store.claim_writer()
        with self.assertRaisesRegex(MAEPError, "writer"):
            self.record(ev("E-1"), "op-1")

    def test_read_only_view_refuses_even_a_replay(self):
        self.record(ev("E-1"), "op-1")
        view = self.restore(read_only=True)
        with self.assertRaisesRegex(MAEPError, "read-only"):
            self.record(ev("E-1"), "op-1", store=view)

    def test_terminal_task_replays_a_committed_operation_but_refuses_a_new_one(self):
        order = ["READY", "ASSESSED", "PLANNED", "AUTHORIZED", "RUNNING", "VERIFYING", "ACCEPTED",
                 "CLOSED_VERIFIED"]
        for state in order:
            if state == "AUTHORIZED":
                self.store.record_authorization_request("T-1", request(), expected_version=self.version())
            if state == "VERIFYING":
                self.store.record_result("T-1", result_ref="run://1", candidate_ref="abc123",
                                         expected_version=self.version())
            if state == "ACCEPTED":
                self.record(ev("E-1"), "op-close")
                self.store.set_mandatory_gates("T-1", [gate()], expected_version=self.version())
            if state == "CLOSED_VERIFIED":
                self.store.record_closure("T-1", closure(), expected_version=self.version())
            self.store.apply_transition("T-1", state, expected_version=self.version())
        self.assertEqual(self.store.snapshot("T-1")["task"]["state"], "CLOSED_VERIFIED")
        size = self.ledger.stat().st_size

        self.assertEqual(self.record(ev("E-5"), "op-close"), "E-1")
        with self.assertRaisesRegex(MAEPError, "terminal"):
            self.record(ev("E-6"), "op-new")
        self.assertEqual(self.ledger.stat().st_size, size)


class ContentIdentityTests(EvidenceOperationCase):
    def test_reordered_list_is_different_content(self):
        first = ev("E-1")
        first["limitations"] = ["a", "b"]
        self.record(first, "op-1")
        second = ev("E-2")
        second["limitations"] = ["b", "a"]
        with self.assertRaisesRegex(MAEPError, "operation_id .*conflict"):
            self.record(second, "op-1")

    def test_tuple_and_list_are_the_same_json_content(self):
        first = ev("E-1")
        first["test_ids"] = ("AC-1", "AC-2")
        self.record(first, "op-1")
        retry = ev("E-2")
        retry["test_ids"] = ["AC-1", "AC-2"]
        self.assertEqual(self.record(retry, "op-1", store=self.restore()), "E-1")

    def test_unicode_and_float_metadata_replay_after_restore(self):
        record = ev("E-1")
        record["integrity_metadata"] = {"ghi_chú": "Chủ Nhân — kiểm chứng", "ratio": 0.1 + 0.2, "count": 3}
        self.record(record, "op-1")
        retry = ev("E-2", collected_at="2026-10-23T11:00:00Z")
        retry["integrity_metadata"] = dict(record["integrity_metadata"])
        self.assertEqual(self.record(retry, "op-1", store=self.restore()), "E-1")


class DurabilityAndTamperTests(EvidenceOperationCase):
    def test_replay_fsyncs_the_ledger_before_reporting_success(self):
        self.record(ev("E-1"), "op-1")
        with mock.patch.object(task_store_module.os, "fsync", wraps=os.fsync) as fsync:
            self.assertEqual(self.record(ev("E-2"), "op-1"), "E-1")
        self.assertTrue(fsync.called)

    def test_replay_whose_fsync_fails_is_in_doubt(self):
        self.record(ev("E-1"), "op-1")
        with mock.patch.object(task_store_module.os, "fsync", side_effect=OSError("EIO")):
            with self.assertRaises(MAEPError) as caught:
                self.record(ev("E-2"), "op-1")
        self.assertIsInstance(caught.exception, outcome_unknown_type())

    def test_tampered_operation_of_the_wrong_type_refuses_restore_cleanly(self):
        self.record(ev("E-1"), "op-1")
        for index, bad in enumerate([["op-2"], {"op": 2}, 7, None]):
            with self.subTest(operation_id=bad):
                version = len(read_events(self.ledger)) + 1
                path = Path(self.directory.name) / f"tampered-{index}.jsonl"
                path.write_bytes(self.ledger.read_bytes())
                append_event(path, {
                    "event_id": f"T-1@{version}", "type": "EVIDENCE_RECORDED", "task_id": "T-1",
                    "version": version, "policy_version": POLICY_VERSION,
                    "recorded_at": "2026-10-23T10:08:00+00:00",
                    "data": {"evidence": ev(f"E-{index + 10}"), "operation_id": bad},
                })
                with self.assertRaisesRegex(MAEPError, "invalid evidence operation"):
                    TaskStore.restore(path, policy_evaluator=self.evaluator, clock=self.clock)

    def test_stale_history_task_refuses_even_a_replay(self):
        old = "MAEP-1.0.0"
        path = Path(self.directory.name) / "history.jsonl"
        task = draft_task()
        task["policy_version"] = old
        append_event(path, {"event_id": "T-1@1", "type": "TASK_CREATED", "task_id": "T-1", "version": 1,
                            "policy_version": old, "recorded_at": "2026-10-20T10:00:00+00:00",
                            "data": {"task": task}})
        append_event(path, {"event_id": "T-1@2", "type": "EVIDENCE_RECORDED", "task_id": "T-1", "version": 2,
                            "policy_version": old, "recorded_at": "2026-10-20T10:01:00+00:00",
                            "data": {"evidence": ev("E-1"), "operation_id": "op-1"}})
        history = TaskStore.restore(path, policy_evaluator=self.evaluator, clock=self.clock,
                                    history_versions=(old,))
        self.assertEqual(history.snapshot("T-1")["policy_status"], "STALE")
        with self.assertRaisesRegex(MAEPError, "read-only history"):
            history.record_evidence("T-1", ev("E-1"), expected_version=2, operation_id="op-1")


if __name__ == "__main__":
    unittest.main()
