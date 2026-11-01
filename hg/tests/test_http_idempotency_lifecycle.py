"""H1.3.1 idempotency lifecycle under adverse conditions (HG_SERVICE_V1 §5 "Idempotency").

Through the real HGHTTPServer, runtime and IdempotencyStore:

- ownership release when execute_task raises BaseException (not only Exception);
- SQLite transaction failures in begin/finish/in_doubt: rollback, or fail closed (store unusable);
- crash after the side effect and before the COMPLETE receipt, in a real child process that
  exits with os._exit(), followed by a restart from the same database;
- payload mismatch while a receipt is STARTED (active or orphaned) or IN_DOUBT;
- deterministic interleavings of duplicate requests with finish()/in_doubt();
- server_close() draining a running request before closing the store.

Faults are injected by wrapping the store's real connection (FaultyConnection); nothing in
production code is changed for testing. Every concurrency test is ordered with Events and an
observed lock, not sleeps.
"""
import hashlib
import http.client
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hg.http_api import HGHTTPServer, IdempotencyStore, canonical_json
from hg.tests import idempotency_crash_child as crash_child
from hg.tests import test_http_api as http_api_tests
from hg.tests.support import TempDirMixin

TOKEN = http_api_tests.TOKEN
REPO_ROOT = Path(__file__).resolve().parents[2]
WAIT = 5.0


class SimulatedCrash(BaseException):
    """Derives from BaseException directly, like SystemExit and KeyboardInterrupt."""


class FaultyConnection:
    """Delegates to the store's real SQLite connection and injects faults.

    execute_faults: [(sql substring, exception)] -- the first matching execute() raises,
                    before the statement reaches SQLite; each entry is used once.
    commit_faults:  [(sql substring, action)] -- after a matching execute() succeeds, the
                    next commit() raises `action` (an exception) or calls it (a callable may
                    block or raise) instead of committing; each entry is used once.
    rollback_fault: an exception every rollback() raises without rolling back.
    """

    def __init__(self, real):
        self._real = real
        self.execute_faults = []
        self.commit_faults = []
        self.rollback_fault = None
        self._armed = None

    def execute(self, sql, *args):
        for index, (match, exc) in enumerate(self.execute_faults):
            if match in sql:
                del self.execute_faults[index]
                raise exc
        cursor = self._real.execute(sql, *args)
        for index, (match, action) in enumerate(self.commit_faults):
            if match in sql:
                del self.commit_faults[index]
                self._armed = action
                break
        return cursor

    def commit(self):
        action, self._armed = self._armed, None
        if isinstance(action, BaseException):
            raise action
        if action is not None:
            action()
        return self._real.commit()

    def rollback(self):
        if self.rollback_fault is not None:
            raise self.rollback_fault
        return self._real.rollback()

    @property
    def in_transaction(self):
        return self._real.in_transaction

    def close(self):
        return self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


class ObservedLock:
    """A threading.Lock that records when an acquirer had to wait for it."""

    def __init__(self):
        self._lock = threading.Lock()
        self.contended = threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(blocking=False):
            return True
        if not blocking:
            return False
        self.contended.set()
        return self._lock.acquire(timeout=timeout)

    def release(self):
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class ThreadExceptions:
    """threading.excepthook stand-in: records exceptions that end a handler thread."""

    def __init__(self):
        self.seen = []
        self.event = threading.Event()

    def __call__(self, args):
        self.seen.append(args.exc_type)
        self.event.set()


def wait_until(condition, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def durable_receipts(db_path, scratch):
    """Committed receipts only: read a copy of the database and its WAL, never the original."""
    inspect = Path(tempfile.mkdtemp(dir=scratch))
    copy = inspect / "copy.sqlite3"
    shutil.copyfile(db_path, copy)
    wal = Path(str(db_path) + "-wal")
    if wal.exists():
        shutil.copyfile(wal, Path(str(copy) + "-wal"))
    conn = sqlite3.connect(copy)
    try:
        return {key: (state, response) for key, state, response in
                conn.execute("SELECT idem_key, state, response_json FROM requests")}
    finally:
        conn.close()


class _LifecycleBase(http_api_tests.HTTPAPITests):
    """The HTTP API fixture (real runtime, fake GitHub trust, real store) plus helpers."""

    def setUp(self):
        super().setUp()
        self.store = self.server.idempotency
        self.db_path = self.workdir / "http-idempotency.sqlite3"
        self.execute_calls = 0
        self._original_execute = self.runtime.orch.execute_task

    def count_execute(self, behaviour=None):
        """Patch execute_task: count calls; `behaviour(task, steps, original)` may block or raise."""
        def execute(task, steps):
            self.execute_calls += 1
            if behaviour is None:
                return self._original_execute(task, steps)
            return behaviour(task, steps, self._original_execute)
        patcher = patch.object(self.runtime.orch, "execute_task", side_effect=execute)
        patcher.start()
        self.addCleanup(patcher.stop)

    def faulty_db(self):
        faulty = FaultyConnection(self.store._db)
        self.store._db = faulty
        return faulty

    def receipt(self, key):
        """(state, response_json) through the store's own connection, or None."""
        with self.store._lock:
            return self.store._db.execute(
                "SELECT state, response_json FROM requests WHERE idem_key=?", (key,)).fetchone()

    def post(self, key, payload=None):
        return self.request("POST", "/v1/tasks", body=payload or self.payload(),
                            headers={"Idempotency-Key": key})

    def post_expecting_disconnect(self, key, payload=None):
        """Status if the server answered, None if it closed the connection without a response."""
        raw = json.dumps(payload or self.payload(), separators=(",", ":")).encode()
        conn = http.client.HTTPConnection(self.host, self.port, timeout=WAIT)
        try:
            conn.request("POST", "/v1/tasks", body=raw, headers={
                "Authorization": "Bearer " + TOKEN.decode(), "Idempotency-Key": key,
                "Content-Type": "application/json", "Content-Length": str(len(raw))})
            try:
                return conn.getresponse().status
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                return None
        finally:
            conn.close()

    def task_payload(self, task_id, content):
        """A payload for another task: the runtime refuses a second task with the same task_id."""
        payload = self.payload(content)
        payload["task"]["task_id"] = task_id
        payload["steps"][0]["authorization_id"] = "A-" + task_id
        return payload

    def digest(self, payload=None):
        return hashlib.sha256(canonical_json(payload or self.payload())).hexdigest()

    def ready(self):
        return self.request("GET", "/v1/health/ready")

    def assert_no_active_keys(self):
        self.assertEqual(self.store._active_keys, set(), "a request left stale active ownership")

    def written(self):
        target = self.root / "out/hello.txt"
        return target.read_text(encoding="utf-8") if target.exists() else None

    def action_started(self):
        return len(self.runtime.actions.events("ACTION_STARTED"))

    def restart_store(self):
        """A new IdempotencyStore on the same database, as after a process restart."""
        self.store.close()
        self.store = self.server.idempotency = IdempotencyStore(self.db_path)
        return self.store


# Do not re-run the inherited HTTP API tests from this module.
for _name in [n for n in dir(http_api_tests.HTTPAPITests) if n.startswith("test_")]:
    setattr(_LifecycleBase, _name, None)


class OwnershipReleaseTests(_LifecycleBase):
    """Workstream A: no stale active ownership after BaseException; cleanup never masks."""

    def _raise_from_execute(self, exc_type):
        def behaviour(task, steps, original):
            original(task, steps)                 # the side effect happens, then the crash
            raise exc_type("raised after the side effect")
        self.count_execute(behaviour)

    def _assert_base_exception_path(self, exc_type, key):
        hook = ThreadExceptions()
        with patch.object(threading, "excepthook", hook):
            self._raise_from_execute(exc_type)
            status = self.post_expecting_disconnect(key)
            self.assertTrue(hook.event.wait(WAIT), "handler thread did not end with the exception")
        # Not turned into an HTTP response, and the ORIGINAL exception ended the thread.
        self.assertIsNone(status)
        self.assertEqual(hook.seen, [exc_type])
        self.assert_no_active_keys()
        self.assertEqual(self.receipt(key)[0], "IN_DOUBT")
        status, body = self.post(key)
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual(self.execute_calls, 1)
        self.assertEqual(self.action_started(), 1)
        self.assertEqual(self.written(), "xin chao")

    def test_base_exception_from_execute_releases_ownership_and_retry_is_in_doubt(self):
        self._assert_base_exception_path(SimulatedCrash, "base-exc-1")

    def test_system_exit_from_execute_releases_ownership_and_retry_is_in_doubt(self):
        self._assert_base_exception_path(SystemExit, "system-exit-1")

    def test_base_exception_with_failing_in_doubt_keeps_original_and_fails_closed(self):
        faulty = self.faulty_db()
        faulty.execute_faults.append(("SET state='IN_DOUBT'",
                                      sqlite3.DatabaseError("database disk image is malformed")))
        hook = ThreadExceptions()
        with patch.object(threading, "excepthook", hook):
            self._raise_from_execute(SimulatedCrash)
            status = self.post_expecting_disconnect("double-fault-1")
            self.assertTrue(hook.event.wait(WAIT))
        self.assertIsNone(status)
        self.assertEqual(hook.seen, [SimulatedCrash], "the cleanup failure replaced the original")
        self.assert_no_active_keys()
        self.assertEqual(durable_receipts(self.db_path, self.tmp)["double-fault-1"][0], "STARTED")
        # The store could not record the outcome: it accepts no execution at all.
        status, body = self.post("double-fault-1")
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        status, body = self.post("double-fault-other", self.task_payload("HTTP-T-9", "new"))
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        status, body = self.ready()
        self.assertEqual((status, body["status"], body["idempotency"]), (503, "NOT_READY", "UNUSABLE"))
        # After a restart the durable STARTED receipt is IN_DOUBT; never executed again.
        self.restart_store()
        status, body = self.post("double-fault-1")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual(self.execute_calls, 1)
        self.assertEqual(self.written(), "xin chao")

    def test_exception_with_transient_in_doubt_failure_answers_500_and_stays_in_doubt(self):
        faulty = self.faulty_db()
        faulty.execute_faults.append(("SET state='IN_DOUBT'", sqlite3.OperationalError("disk I/O error")))
        self._raise_from_execute(RuntimeError)
        status, body = self.post("transient-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assert_no_active_keys()
        self.assertFalse(self.store._db.in_transaction)
        self.assertEqual(self.receipt("transient-1")[0], "STARTED")
        status, body = self.post("transient-1")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual(self.ready()[1]["idempotency"], "USABLE")
        self.assertEqual(self.execute_calls, 1)


class TransactionFailureTests(_LifecycleBase):
    """Workstream B: no transaction is left open; an unknown state fails closed."""

    def _fail_execution(self):
        """The first execution fails after its side effect; later ones succeed."""
        remaining = [1]

        def behaviour(task, steps, original):
            result = original(task, steps)
            if remaining[0]:
                remaining[0] -= 1
                raise RuntimeError("runtime failed after the side effect")
            return result
        self.count_execute(behaviour)

    def test_in_doubt_commit_failure_is_rolled_back_and_store_keeps_working(self):
        faulty = self.faulty_db()
        faulty.commit_faults.append(("SET state='IN_DOUBT'", sqlite3.OperationalError("database is locked")))
        self._fail_execution()
        status, body = self.post("idc-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assertFalse(self.store._db.in_transaction, "a failed COMMIT left the transaction open")
        self.assert_no_active_keys()
        status, body = self.post("idc-1")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        status, body = self.ready()
        self.assertEqual((status, body["status"], body["idempotency"]), (200, "READY", "USABLE"))
        # A new request still executes normally.
        status, body = self.post("idc-2", self.task_payload("HTTP-T-2", "second"))
        self.assertEqual(status, 200)
        self.assertEqual(self.receipt("idc-2")[0], "COMPLETE")
        self.assertEqual(self.written(), "second")

    def test_in_doubt_commit_and_rollback_failure_makes_store_unusable(self):
        faulty = self.faulty_db()
        faulty.commit_faults.append(("SET state='IN_DOUBT'", sqlite3.OperationalError("database is locked")))
        faulty.rollback_fault = sqlite3.OperationalError("disk I/O error")
        self._fail_execution()
        status, body = self.post("idr-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assert_no_active_keys()
        self.assertEqual(durable_receipts(self.db_path, self.tmp)["idr-1"][0], "STARTED")
        for key, payload in (("idr-1", None), ("idr-new", self.task_payload("HTTP-T-9", "new"))):
            status, body = self.post(key, payload)
            self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        status, body = self.ready()
        self.assertEqual((status, body["status"], body["idempotency"]), (503, "NOT_READY", "UNUSABLE"))
        self.assertEqual(self.execute_calls, 1)
        self.assertEqual(self.action_started(), 1)

    def test_finish_update_failure_records_in_doubt_and_never_reexecutes(self):
        faulty = self.faulty_db()
        faulty.execute_faults.append(("SET state='COMPLETE'", sqlite3.OperationalError("disk I/O error")))
        self.count_execute()
        status, body = self.post("fu-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assertEqual(self.written(), "xin chao")
        self.assert_no_active_keys()
        self.assertEqual(self.receipt("fu-1")[0], "IN_DOUBT")
        status, body = self.post("fu-1")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual(self.ready()[1]["idempotency"], "USABLE")
        self.assertEqual((self.execute_calls, self.action_started()), (1, 1))

    def test_finish_commit_failure_records_in_doubt_and_never_reexecutes(self):
        faulty = self.faulty_db()
        faulty.commit_faults.append(("SET state='COMPLETE'", sqlite3.OperationalError("database is locked")))
        self.count_execute()
        status, body = self.post("fc-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assertFalse(self.store._db.in_transaction)
        self.assert_no_active_keys()
        self.assertEqual(self.receipt("fc-1")[0], "IN_DOUBT")
        status, body = self.post("fc-1")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual((self.execute_calls, self.action_started()), (1, 1))

    def test_begin_failure_answers_503_without_execution_and_store_recovers(self):
        faulty = self.faulty_db()
        faulty.execute_faults.append(("BEGIN IMMEDIATE", sqlite3.OperationalError("database is locked")))
        self.count_execute()
        status, body = self.post("bf-1")
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        self.assertEqual(self.execute_calls, 0)
        self.assertIsNone(self.receipt("bf-1"))
        status, body = self.post("bf-1")
        self.assertEqual(status, 200)
        self.assertEqual((self.execute_calls, self.receipt("bf-1")[0]), (1, "COMPLETE"))

    def test_database_replaced_during_execution_makes_store_unusable(self):
        displaced = self.workdir / "displaced.sqlite3"

        def behaviour(task, steps, original):
            result = original(task, steps)
            staging = self.workdir / "staging.sqlite3"
            replacement = sqlite3.connect(staging)
            replacement.execute("CREATE TABLE marker(v TEXT)")
            replacement.commit()
            replacement.close()
            staging.chmod(0o600)
            self.db_path.replace(displaced)          # the path no longer names the bound inode
            staging.replace(self.db_path)
            return result
        self.count_execute(behaviour)
        status, body = self.post("swap-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assert_no_active_keys()
        self.assertEqual(self.receipt("swap-1")[0], "STARTED")      # the bound (displaced) database
        for key, payload in (("swap-1", None), ("swap-new", self.task_payload("HTTP-T-9", "new"))):
            status, body = self.post(key, payload)
            self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        self.assertEqual(self.ready()[1]["idempotency"], "UNUSABLE")
        self.assertEqual(self.execute_calls, 1)

    def test_receipt_changed_underneath_an_active_request_makes_store_unusable(self):
        def behaviour(task, steps, original):
            result = original(task, steps)
            with self.store._lock:                   # another writer moves the row out of STARTED
                self.store._db.execute("UPDATE requests SET state='IN_DOUBT' WHERE idem_key='moved-1'")
                self.store._db.commit()
            return result
        self.count_execute(behaviour)
        status, body = self.post("moved-1")
        self.assertEqual((status, body["error"]), (500, "internal_error"))
        self.assert_no_active_keys()
        status, body = self.post("moved-new", self.task_payload("HTTP-T-9", "new"))
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        self.assertEqual(self.execute_calls, 1)

    def test_base_exception_inside_begin_transaction_rolls_back_and_fails_closed(self):
        faulty = self.faulty_db()
        faulty.commit_faults.append(("INSERT INTO requests", SimulatedCrash("crash at COMMIT of STARTED")))
        with self.assertRaises(SimulatedCrash):           # not converted into a mode or a 503
            self.store.begin("bx-1", self.digest())
        self.assertFalse(self.store._db.in_transaction)
        self.assertIsNone(self.receipt("bx-1"))            # STARTED was rolled back
        self.assert_no_active_keys()
        self.assertEqual(self.store.status, "UNUSABLE")
        self.count_execute()
        status, body = self.post("bx-1")
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        self.assertEqual(self.execute_calls, 0)

    def test_transaction_found_open_before_begin_fails_closed_without_execution(self):
        self.store._db.execute("BEGIN")                     # left open by someone else
        self.store._db.execute("UPDATE requests SET state=state")
        self.count_execute()
        status, body = self.post("open-1")
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))
        self.assertEqual((self.execute_calls, self.store.status), (0, "UNUSABLE"))
        status, body = self.ready()
        self.assertEqual((status, body["idempotency"]), (503, "UNUSABLE"))


class ReadinessTests(_LifecycleBase):
    """The readiness report says whether the idempotency store can accept a task."""

    def test_ready_reports_usable_store(self):
        status, body = self.ready()
        self.assertEqual((status, body["status"], body["idempotency"]), (200, "READY", "USABLE"))

    def test_ready_without_configured_store_keeps_prior_readiness(self):
        self.server.shutdown()
        self.thread.join(WAIT)
        self.server.server_close()
        self.server = HGHTTPServer(
            runtime=self.runtime, token=TOKEN, host="127.0.0.1", port=0, max_body_bytes=2048,
            release_report=lambda: {"result": "VERIFIED", "release_id": "a" * 64},
            trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "b" * 40}})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.address
        status, body = self.ready()
        self.assertEqual((status, body["status"], body["idempotency"]), (200, "READY", "NOT_CONFIGURED"))
        status, body = self.post("no-store")
        self.assertEqual((status, body["error"]), (503, "idempotency_unavailable"))


class StateMachineTests(_LifecycleBase):
    """Workstream D: a different body never becomes a new request, whatever the receipt state."""

    def test_different_payload_while_started_and_active_conflicts(self):
        entered, release = threading.Event(), threading.Event()

        def behaviour(task, steps, original):
            entered.set()
            if not release.wait(WAIT):
                raise TimeoutError("test gate timed out")
            return original(task, steps)
        self.count_execute(behaviour)
        first = {}
        thread = threading.Thread(target=lambda: first.setdefault("r", self.post("mm-active")))
        thread.start()
        try:
            self.assertTrue(entered.wait(WAIT))
            status, body = self.post("mm-active", self.payload("changed"))
            self.assertEqual((status, body["error"]), (409, "idempotency_conflict"))
            self.assertEqual(self.store._active_keys, {"mm-active"})
        finally:
            release.set()
            thread.join(WAIT)
        self.assertEqual(first["r"][0], 200)
        self.assertEqual((self.execute_calls, self.written()), (1, "xin chao"))
        self.assertEqual(self.receipt("mm-active")[0], "COMPLETE")
        self.assert_no_active_keys()

    def test_different_payload_while_started_and_orphaned_conflicts(self):
        self.count_execute()
        digest = self.digest()
        self.assertEqual(self.store.begin("mm-orphan", digest)[0], "NEW")
        self.restart_store()
        status, body = self.post("mm-orphan", self.payload("changed"))
        self.assertEqual((status, body["error"]), (409, "idempotency_conflict"))
        status, body = self.post("mm-orphan")
        self.assertEqual((status, body["error"]), (409, "outcome_in_doubt"))
        self.assertEqual((self.execute_calls, self.written()), (0, None))
        self.assertEqual(self.receipt("mm-orphan")[0], "STARTED")

    def test_different_payload_while_in_doubt_conflicts(self):
        self.count_execute()
        digest = self.digest()
        self.store.begin("mm-doubt", digest)
        self.store.in_doubt("mm-doubt")
        status, body = self.post("mm-doubt", self.payload("changed"))
        self.assertEqual((status, body["error"]), (409, "idempotency_conflict"))
        self.assertEqual((self.execute_calls, self.written()), (0, None))
        self.assertEqual(self.receipt("mm-doubt")[0], "IN_DOUBT")
        self.assert_no_active_keys()


class ConcurrencyTests(_LifecycleBase):
    """Workstream E: deterministic interleavings; one execution per key in one process."""

    def _block_execute(self):
        entered, release = threading.Event(), threading.Event()

        def behaviour(task, steps, original):
            entered.set()
            if not release.wait(WAIT):
                raise TimeoutError("test gate timed out")
            return original(task, steps)
        self.count_execute(behaviour)
        return entered, release

    def test_simultaneous_same_key_requests_execute_once(self):
        entered, release = self._block_execute()
        workers, results = 4, []
        barrier = threading.Barrier(workers)
        done = threading.Semaphore(0)

        def worker():
            barrier.wait(WAIT)
            results.append(self.post("race-same"))
            done.release()
        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for thread in threads:
            thread.start()
        try:
            self.assertTrue(entered.wait(WAIT))
            for _ in range(workers - 1):              # every duplicate answered while one runs
                self.assertTrue(done.acquire(timeout=WAIT))
            self.assertEqual([(s, b["error"]) for s, b in results],
                             [(409, "request_in_progress")] * (workers - 1))
            self.assertEqual(self.store._active_keys, {"race-same"})
        finally:
            release.set()
            for thread in threads:
                thread.join(WAIT)
        self.assertEqual(results[-1][0], 200)
        self.assertEqual((self.execute_calls, self.action_started()), (1, 1))
        self.assertEqual(self.receipt("race-same")[0], "COMPLETE")
        self.assert_no_active_keys()

    def test_duplicate_after_execute_and_before_finish_is_in_progress_then_replay(self):
        self.count_execute()
        at_finish, go = threading.Event(), threading.Event()
        real_finish = self.store.finish

        def gated_finish(key, response):
            at_finish.set()                           # side effect done, receipt not written
            if not go.wait(WAIT):
                raise TimeoutError("test gate timed out")
            return real_finish(key, response)
        self.store.finish = gated_finish
        first = {}
        thread = threading.Thread(target=lambda: first.setdefault("r", self.post("pre-finish")))
        thread.start()
        try:
            self.assertTrue(at_finish.wait(WAIT))
            status, body = self.post("pre-finish")
            self.assertEqual((status, body["error"]), (409, "request_in_progress"))
            self.assertEqual(self.receipt("pre-finish")[0], "STARTED")
        finally:
            go.set()
            thread.join(WAIT)
        self.assertEqual(first["r"][0], 200)
        status, replay = self.post("pre-finish")
        self.assertEqual((status, replay["replayed"]), (200, True))
        self.assertEqual(replay["result"], first["r"][1]["result"])
        self.assertEqual(self.execute_calls, 1)
        self.assert_no_active_keys()

    def _duplicate_waiting_for_transition(self, key, commit_match, behaviour):
        """First request holds the store lock inside a transition's COMMIT; a duplicate waits."""
        lock = ObservedLock()
        self.store._lock = lock
        in_commit, go = threading.Event(), threading.Event()

        def blocking_commit():
            in_commit.set()
            if not go.wait(WAIT):
                raise TimeoutError("test gate timed out")
        self.faulty_db().commit_faults.append((commit_match, blocking_commit))
        self.count_execute(behaviour)
        first, duplicate = {}, {}
        t1 = threading.Thread(target=lambda: first.setdefault("r", self.post(key)))
        t1.start()
        try:
            self.assertTrue(in_commit.wait(WAIT), "first request did not reach the transition")
            t2 = threading.Thread(target=lambda: duplicate.setdefault("r", self.post(key)))
            t2.start()
            self.assertTrue(lock.contended.wait(WAIT), "duplicate did not wait for the store lock")
            self.assertNotIn("r", duplicate)
        finally:
            go.set()
            t1.join(WAIT)
        t2.join(WAIT)
        return first["r"], duplicate["r"]

    def test_duplicate_waiting_on_finish_commit_gets_replay_not_in_doubt(self):
        first, duplicate = self._duplicate_waiting_for_transition(
            "lock-finish", "SET state='COMPLETE'", None)
        self.assertEqual(first[0], 200)
        self.assertEqual((duplicate[0], duplicate[1]["replayed"]), (200, True))
        self.assertEqual(duplicate[1]["result"], first[1]["result"])
        self.assertEqual(self.execute_calls, 1)
        self.assertEqual(self.receipt("lock-finish")[0], "COMPLETE")
        self.assert_no_active_keys()

    def test_duplicate_waiting_on_in_doubt_commit_gets_in_doubt_not_execution(self):
        def failing(task, steps, original):
            original(task, steps)
            raise RuntimeError("failed after the side effect")
        first, duplicate = self._duplicate_waiting_for_transition(
            "lock-doubt", "SET state='IN_DOUBT'", failing)
        self.assertEqual((first[0], first[1]["error"]), (500, "internal_error"))
        self.assertEqual((duplicate[0], duplicate[1]["error"]), (409, "outcome_in_doubt"))
        self.assertEqual(self.execute_calls, 1)
        self.assertEqual(self.receipt("lock-doubt")[0], "IN_DOUBT")
        self.assert_no_active_keys()

    def test_concurrent_different_keys_each_execute_once(self):
        self.count_execute()
        barrier = threading.Barrier(3)
        results = {}

        def worker(index):
            barrier.wait(WAIT)
            results[index] = self.post(f"multi-{index}", self.task_payload(f"HTTP-M-{index}", f"content-{index}"))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(WAIT)
        self.assertEqual(sorted(status for status, _ in results.values()), [200, 200, 200])
        self.assertEqual(self.execute_calls, 3)
        self.assertEqual({self.receipt(f"multi-{i}")[0] for i in range(3)}, {"COMPLETE"})
        self.assertEqual(self.action_started(), 3)
        self.assert_no_active_keys()


class ShutdownTests(_LifecycleBase):
    """Workstream F: the store outlives every handler that can still use it."""

    def test_server_close_drains_running_request_before_closing_store(self):
        entered, release = threading.Event(), threading.Event()

        def behaviour(task, steps, original):
            entered.set()
            if not release.wait(WAIT):
                raise TimeoutError("test gate timed out")
            return original(task, steps)
        self.count_execute(behaviour)
        closed_while_running = []
        real_close = self.store.close

        def observed_close():
            closed_while_running.append(not release.is_set())
            real_close()
        self.store.close = observed_close
        result = {}
        client = threading.Thread(target=lambda: result.setdefault("r", self.post("drain-1")))
        client.start()
        closer = None
        try:
            self.assertTrue(entered.wait(WAIT))
            self.server.shutdown()                     # stop accepting; the handler keeps running
            self.thread.join(WAIT)
            closer = threading.Thread(target=self.server.server_close)
            closer.start()
            self.assertTrue(wait_until(lambda: self.server.socket.fileno() == -1),
                            "server_close did not close the listener")
            self.assertEqual(closed_while_running, [], "store closed while a handler was running")
        finally:
            release.set()
            client.join(WAIT)
            if closer is not None:
                closer.join(WAIT)
        self.assertEqual(closed_while_running, [False])
        self.assertEqual(result["r"][0], 200)
        self.assertEqual(result["r"][1]["result"]["task"]["state"], "CLOSED_VERIFIED")
        reopened = IdempotencyStore(self.db_path)
        try:
            digest = self.digest()
            mode, prior = reopened.begin("drain-1", digest)
            self.assertEqual((mode, prior), ("REPLAY", result["r"][1]["result"]))
        finally:
            reopened.close()

    def test_closed_store_refuses_use_and_close_is_idempotent(self):
        self.server.shutdown()
        self.thread.join(WAIT)
        self.server.server_close()
        self.server.server_close()
        with self.assertRaises(Exception) as caught:
            self.store.begin("after-close", "d")
        self.assertEqual(type(caught.exception).__name__, "IdempotencyUnavailable")
        self.store.in_doubt("after-close")             # never raises, even when closed
        self.assert_no_active_keys()


class CrashWindowTests(TempDirMixin):
    """Workstream C: the process dies after the side effect, before a durable COMPLETE receipt.

    A real child process runs the HTTP request and exits with os._exit() (no cleanup runs).
    The parent then restarts from the same workdir and database and retries the same request.
    """

    def _crash(self, point, expected_exit):
        db = self.workdir / "http-idempotency.sqlite3"
        marker = Path(self.tmp) / f"marker-{point}.json"
        proc = subprocess.run(
            [sys.executable, "-m", "hg.tests.idempotency_crash_child",
             str(self.workdir), str(db), str(marker), point],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, expected_exit, proc.stderr[-2000:])
        observed = json.loads(marker.read_text(encoding="utf-8"))
        # Evidence the side effect really happened exactly once before the crash.
        self.assertEqual(observed["file"], "xin chao")
        self.assertEqual((observed["action_started"], observed["action_completed"]), (1, 1))
        self.assertEqual((self.root / "out/hello.txt").read_text(encoding="utf-8"), "xin chao")
        # The COMPLETE receipt never became durable.
        self.assertEqual(durable_receipts(db, self.tmp)[crash_child.KEY], ("STARTED", None))
        return db, observed

    def _restart_and_retry(self, db):
        runtime, server = crash_child.build_server(self.workdir, db)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), thread.join(WAIT), server.server_close()))
        self.assertEqual(len(runtime.actions.events("ACTION_STARTED")), 1)   # restored from disk
        calls = []
        original = runtime.orch.execute_task

        def counting(task, steps):
            calls.append(task["task_id"])
            return original(task, steps)
        host, port = server.address
        with patch.object(runtime.orch, "execute_task", side_effect=counting):
            for payload, expected in ((crash_child.crash_payload(), (409, "outcome_in_doubt")),
                                      (crash_child.crash_payload("changed"), (409, "idempotency_conflict")),
                                      (crash_child.crash_payload(), (409, "outcome_in_doubt"))):
                raw = json.dumps(payload, separators=(",", ":")).encode()
                conn = http.client.HTTPConnection(host, port, timeout=WAIT)
                conn.request("POST", "/v1/tasks", body=raw, headers={
                    "Authorization": "Bearer " + TOKEN.decode(), "Idempotency-Key": crash_child.KEY,
                    "Content-Type": "application/json", "Content-Length": str(len(raw))})
                response = conn.getresponse()
                body = json.loads(response.read().decode("utf-8"))
                conn.close()
                self.assertEqual((response.status, body["error"]), expected)
        self.assertEqual(calls, [], "the retry after restart executed the task again")
        self.assertEqual(len(runtime.actions.events("ACTION_STARTED")), 1)
        self.assertEqual((self.root / "out/hello.txt").read_text(encoding="utf-8"), "xin chao")
        self.assertEqual(server.idempotency._active_keys, set())

    def test_crash_after_side_effect_before_finish_is_in_doubt_after_restart(self):
        db, _observed = self._crash("before-finish", crash_child.CRASH_BEFORE_FINISH)
        self._restart_and_retry(db)

    def test_crash_at_finish_commit_is_in_doubt_after_restart(self):
        db, observed = self._crash("at-finish-commit", crash_child.CRASH_AT_FINISH_COMMIT)
        self.assertEqual((observed["update_executed_uncommitted"], observed["in_transaction"]), (True, True))
        self._restart_and_retry(db)


if __name__ == "__main__":
    unittest.main()
