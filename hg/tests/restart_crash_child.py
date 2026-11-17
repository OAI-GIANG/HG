"""Child process for hg/tests/test_restart_recovery.py (RF-2). Not a test module.

It builds a real anchored runtime in WORKDIR, runs one fs.write task through
BrainOrchestrator -> ActionGateway, and kills its own process with os._exit() at POINT.
No cleanup, no finally block and no blocker write runs: this is what a service process
killed by Android (SIGKILL) leaves behind.

    python -m hg.tests.restart_crash_child WORKDIR POINT

POINT:
  before-start      after the task is RUNNING, before ACTION_STARTED is written
  before-effect     after ACTION_STARTED is durable, before the file is written
  after-effect      after the file is written, before ACTION_COMPLETED is written
  after-completion  after ACTION_COMPLETED (SUCCEEDED), before the task leaves RUNNING
Exit code 3 means the crash point was never reached.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.http_api import planned_write_readback_verifier
from hg.runtime import build_runtime
from hg.tests.support import Clock, make_task, write_step
from hg.tools import gateway as gw

TASK_ID = "RF2-T-1"
EXIT = {"before-start": 90, "before-effect": 91, "after-effect": 92, "after-completion": 93}
NOT_REACHED = 3


def task():
    t = make_task(task_id=TASK_ID)
    t["acceptance_criteria"] = [{"criterion_id": "AC-READBACK", "description": "write content reads back",
                                 "mandatory": True, "evidence_types": ["TEST_RESULT"]}]
    return t


def steps():
    return [write_step(authorization_id="RF2-A-1")]


def build(workdir, clock=None, *, recover_interrupted=True):
    """The service's assembly (hg/service.py create_service): anchored, per-task grants, RF-2 on."""
    workdir = Path(workdir)
    clock = clock or Clock()
    authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0, clock=clock)
    return build_runtime(workdir, [], authority=authority, issue_task_grants=True, clock=clock,
                         verifiers={"AC-READBACK": planned_write_readback_verifier(workdir / "root")},
                         recover_interrupted=recover_interrupted)


def main(argv):
    workdir, point = argv
    code = EXIT[point]
    real_write = gw.LocalFileWriteAdapter.execute
    real_execute = gw.ActionGateway.execute

    def write(self, params, permit=None):
        if point == "before-effect":
            os._exit(code)
        observed = real_write(self, params, permit)
        if point == "after-effect":
            os._exit(code)
        return observed

    def execute(self, task_id, step_id):
        if point == "before-start":
            os._exit(code)
        outcome = real_execute(self, task_id, step_id)
        if point == "after-completion":
            os._exit(code)
        return outcome

    gw.LocalFileWriteAdapter.execute = write
    gw.ActionGateway.execute = execute
    build(workdir, recover_interrupted=False).orch.execute_task(task(), steps())
    return NOT_REACHED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
