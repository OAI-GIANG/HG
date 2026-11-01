"""Child process for the crash-window tests in hg/tests/test_http_idempotency_lifecycle.py.

Not a test module (the name does not match test_*.py). It starts a real HGHTTPServer with a
real runtime in WORKDIR, sends one POST /v1/tasks over loopback, and kills its own process
with os._exit() at a chosen point AFTER execute_task has returned (the side effect is done)
but BEFORE the COMPLETE receipt is durable. No cleanup, no finally block and no in_doubt()
transition runs: this is what a crashed service process leaves behind.

    python -m hg.tests.idempotency_crash_child WORKDIR DB_PATH MARKER POINT

POINT:
  before-finish     exit CRASH_BEFORE_FINISH inside IdempotencyStore.finish, before its
                    transaction begins
  at-finish-commit  exit CRASH_AT_FINISH_COMMIT at the COMMIT of finish's transaction, after
                    the UPDATE to COMPLETE has executed but before it is committed

Before exiting, the child writes MARKER (JSON, fsynced) with what it observed at the crash
point: the file content on disk and the runtime's ACTION_STARTED / ACTION_COMPLETED counts.
Exit code 3 means the crash point was never reached.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
from pathlib import Path

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.http_api import HGHTTPServer, planned_write_readback_verifier
from hg.runtime import build_runtime
from hg.tests.support import Clock, make_task, write_step

TOKEN = b"test-token-that-is-long-enough-for-the-boundary"
KEY = "crash-window-1"
CRASH_BEFORE_FINISH = 86
CRASH_AT_FINISH_COMMIT = 87
NOT_REACHED = 3


def crash_payload(content="xin chao"):
    task = make_task(task_id="HTTP-T-1")
    task["acceptance_criteria"] = [{
        "criterion_id": "AC-READBACK", "description": "write content can be read back exactly",
        "mandatory": True, "evidence_types": ["TEST_RESULT"],
    }]
    return {"task": task, "steps": [write_step(authorization_id="HTTP-A-1", content=content)]}


def build_server(workdir, db_path):
    """The same assembly as HTTPAPITests.setUp: real runtime, fake GitHub trust, real store."""
    workdir = Path(workdir)
    clock = Clock()
    authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
    runtime = build_runtime(workdir, [], authority=authority, issue_task_grants=True, clock=clock,
                            verifiers={"AC-READBACK": planned_write_readback_verifier(workdir / "root")})
    server = HGHTTPServer(
        runtime=runtime, token=TOKEN, host="127.0.0.1", port=0, max_body_bytes=2048,
        release_report=lambda: {"result": "VERIFIED", "release_id": "a" * 64},
        trust_report=lambda: {"result": "LOADED", "provenance": {"commit": "b" * 40}},
        idempotency_path=db_path)
    return runtime, server


class _CrashOnCommit:
    """Delegates to the store's real connection; the first commit() kills the process."""

    def __init__(self, real, on_crash):
        self._real = real
        self._on_crash = on_crash
        self.update_executed = False

    def execute(self, sql, *args):
        cursor = self._real.execute(sql, *args)
        if "SET state='COMPLETE'" in sql:
            self.update_executed = cursor.rowcount == 1
        return cursor

    def commit(self):
        self._on_crash({"update_executed_uncommitted": self.update_executed,
                        "in_transaction": self._real.in_transaction})
        os._exit(CRASH_AT_FINISH_COMMIT)

    def __getattr__(self, name):
        return getattr(self._real, name)


def main(argv):
    workdir, db_path, marker, point = argv
    runtime, server = build_server(workdir, db_path)
    store = server.idempotency
    target = Path(workdir) / "root" / "out" / "hello.txt"

    def record(stage, extra=None):
        info = {"stage": stage,
                "file": target.read_text(encoding="utf-8") if target.is_file() else None,
                "action_started": len(runtime.actions.events("ACTION_STARTED")),
                "action_completed": len(runtime.actions.events("ACTION_COMPLETED"))}
        info.update(extra or {})
        tmp = Path(marker + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(info, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, marker)

    real_finish = store.finish
    if point == "before-finish":
        def finish(key, response):
            record(point)
            os._exit(CRASH_BEFORE_FINISH)
    elif point == "at-finish-commit":
        def finish(key, response):
            store._db = _CrashOnCommit(store._db, lambda extra: record(point, extra))
            return real_finish(key, response)
    else:
        raise SystemExit(f"unknown crash point: {point}")
    store.finish = finish

    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.address
    body = json.dumps(crash_payload(), separators=(",", ":")).encode()
    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.request("POST", "/v1/tasks", body=body, headers={
        "Authorization": "Bearer " + TOKEN.decode(), "Idempotency-Key": KEY,
        "Content-Type": "application/json", "Content-Length": str(len(body))})
    try:
        conn.getresponse().read()
    except OSError:
        pass
    return NOT_REACHED          # the process should have died at the crash point


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
