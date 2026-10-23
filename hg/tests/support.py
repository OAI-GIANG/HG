"""Shared fixtures: the real runtime from hg.runtime in a temporary directory.

Grants here are test fixtures. They are not anchored to the trust root (RT-06 BLOCKED).
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from maep.core import POLICY_VERSION
from hg.runtime import DEFAULT_PRINCIPAL as PRINCIPAL
from hg.runtime import build_runtime

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now = self.now + timedelta(**delta)


def make_task(task_id="T-1", criteria=("AC-1",), state="DRAFT"):
    return {
        "task_id": task_id, "objective": "Write a file and verify its content",
        "scope": {"include": ["out/"], "exclude": []}, "inputs": [],
        "outputs": [{"name": "file", "description": "out/hello.txt"}],
        "acceptance_criteria": [
            {"criterion_id": c, "description": "content matches", "mandatory": True,
             "evidence_types": ["TEST_RESULT"]} for c in criteria],
        "evidence_requirements": ["verifier result"], "risks": [],
        "stop_conditions": ["scope exceeded", "authorization denied"],
        "next_action": "execute plan", "state": state, "policy_version": POLICY_VERSION,
    }


def grant(authorization_id="AUTH-W1", *, action="WRITE", resource="file:out/hello.txt",
          scope=("out/",), task_id="T-1", hours=2, decision="ALLOW", principal=PRINCIPAL):
    return {
        "authorization_id": authorization_id, "principal": principal, "action": action,
        "resource": resource, "scope": list(scope), "conditions": [], "task_id": task_id,
        "policy_version": POLICY_VERSION, "decision": decision,
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=hours)).isoformat(),
    }


def write_step(step_id="S-1", *, path="out/hello.txt", content="xin chao", authorization_id="AUTH-W1",
               resource=None, scope=("out/",), action="WRITE", tool="fs.write"):
    return {"step_id": step_id, "tool": tool, "action": action,
            "resource": resource or f"file:{path}", "scope": list(scope),
            "authorization_id": authorization_id, "params": {"path": path, "content": content}}


def content_verifier(root, path="out/hello.txt", expected="xin chao"):
    def file_content_matches(_snapshot):
        target = Path(root) / path
        actual = target.read_text(encoding="utf-8") if target.is_file() else None
        return actual == expected, f"expected {expected!r}, found {actual!r}"
    return file_content_matches


class TempDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.clock = Clock()

    def tearDown(self):
        self._tmp.cleanup()

    @property
    def workdir(self):
        return Path(self.tmp) / "rt"

    @property
    def root(self):
        return self.workdir / "root"

    def build(self, grants=(), *, verifiers=None, **kwargs):
        """Build (or, if ledgers exist, resume) the runtime in this test's work directory."""
        if verifiers is None:
            verifiers = {"AC-1": content_verifier(self.root)}
        if "authority" not in kwargs:
            kwargs["allow_fixture_grants"] = True      # tests use fixture grants unless anchored
        return build_runtime(self.workdir, grants, verifiers=verifiers, clock=self.clock, **kwargs)
