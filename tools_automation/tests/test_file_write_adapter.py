"""Point-of-effect checks of the runtime.service fs.write adapter (no coordinator involved)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from maep.native_authority import AuthorizationResult, Decision, _digest
from tools_automation.contracts import validate_adapter_result
from tools_automation.file_write_adapter import AdapterInputError, RootedFileWriteAdapter


def request(path="out/result.txt", content="hello", resource=None, scope=("file:out",)):
    return {"task_ref": "T-1", "action": "WRITE", "resource": resource or "file:" + path,
            "scope": list(scope), "params": {"path": path, "content": content}}


def allow(req, *, expires_in=60, **changes):
    now = datetime.now(timezone.utc)
    result = AuthorizationResult(
        decision=Decision.ALLOW, reason_codes=("AUTHORIZED",), principal_ref="STT", action=req["action"],
        resource=req["resource"], task_ref=req["task_ref"], candidate_ref="cand", root_generation=1,
        root_digest="sha256:" + "a" * 64, policy_version="MAEP-1.2.0", policy_digest="sha256:" + "b" * 64,
        applicability_ref="APP", applicability_classification="NOT_REQUIRED", gate_ref=None,
        gate_verified=False, gate_evidence_refs=(), issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=expires_in)).isoformat(), request_digest=_digest(req),
        decision_digest="sha256:" + "c" * 64)
    return replace(result, **changes)


class FileWriteAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hg-fswrite-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "root"
        self.root.mkdir()
        self.adapter = RootedFileWriteAdapter(self.root)

    def run_adapter(self, req, authorization=None):
        result = self.adapter.execute(request=req, authorization=authorization or allow(req), idempotency_key="k-1")
        return validate_adapter_result(result)

    def test_authorized_write_is_atomic_verified_and_idempotent(self):
        req = request()
        first = self.run_adapter(req)
        self.assertEqual(first["outcome"], "SUCCESS")
        self.assertEqual(first["provider_ref"], "sha256:" + hashlib.sha256(b"hello").hexdigest())
        self.assertEqual((self.root / "out/result.txt").read_text(), "hello")
        self.assertEqual(self.run_adapter(req)["provider_ref"], first["provider_ref"])
        self.assertEqual([p.name for p in (self.root / "out").iterdir()], ["result.txt"])     # no temp files
        self.assertEqual(self.adapter.reconcile(self.adapter.intent(req)), "APPLIED")
        self.assertEqual(self.adapter.reconcile(self.adapter.intent(request(content="other"))), "NOT_APPLIED")
        self.assertEqual(self.adapter.reconcile({"path": "../x", "sha256": "s"}), "UNKNOWN")

    def assert_refused(self, req, authorization=None):
        result = self.run_adapter(req, authorization)
        self.assertEqual((result["outcome"], result["effect"]), ("FAILURE", "NONE"), result)
        self.assertFalse((self.root / "out").exists())
        return result

    def test_inputs_outside_the_planned_effect_are_refused_without_effect(self):
        for req in (request(path="../escape.txt", resource="file:../escape.txt", scope=("file:..",)),
                    request(path="/etc/passwd", resource="file:/etc/passwd", scope=("file:/etc",)),
                    request(resource="file:out/other.txt"),                  # resource is not the path
                    request(scope=("file:elsewhere",)),                       # path outside scope
                    request(scope=("file:ou",)),                              # prefix must be a directory
                    request(content="x" * (1 << 20 + 1)),
                    dict(request(), params={"path": "out/result.txt"}),
                    dict(request(), action="DELETE")):
            with self.subTest(req=str(req)[:80]):
                self.assert_refused(req)

    def test_authorization_must_bind_this_exact_request(self):
        req = request()
        tampered = dict(req, params={"path": "out/result.txt", "content": "changed"})
        cases = [allow(req, decision=Decision.DENY), allow(req, action="READ"),
                 allow(req, resource="file:out/x.txt"), allow(req, task_ref="T-2"),
                 allow(req, expires_in=-1), allow(req, expires_at="not-a-time"), {"decision": "ALLOW"}]
        for authorization in cases:
            with self.subTest(authorization=str(authorization)[:60]):
                self.assert_refused(req, authorization)
        self.assert_refused(tampered, allow(req))      # content not covered by the decision digest

    def test_symlink_escape_and_bad_root_are_refused(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "out").symlink_to(outside, target_is_directory=True)
        result = self.adapter.execute(request=request(), authorization=allow(request()), idempotency_key="k")
        self.assertEqual(result["outcome"], "FAILURE")
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / "out").unlink()
        (self.root / "real").mkdir()
        (self.root / "out").symlink_to(self.root / "real", target_is_directory=True)   # inside the root
        self.assertEqual(self.run_adapter(request())["outcome"], "FAILURE")
        self.assertEqual(list((self.root / "real").iterdir()), [])
        with self.assertRaises(AdapterInputError):
            RootedFileWriteAdapter("relative/root")
        with self.assertRaises(AdapterInputError):
            RootedFileWriteAdapter(Path(self.tmp.name) / "missing")

    def test_failure_after_the_write_started_is_not_reported_as_success(self):
        original = os.replace

        def broken(src, dst):
            raise OSError("disk full")
        os.replace = broken
        try:
            with self.assertRaises(OSError):
                self.adapter.execute(request=request(), authorization=allow(request()), idempotency_key="k")
        finally:
            os.replace = original
        self.assertEqual([p for p in (self.root / "out").iterdir()], [])   # temp file cleaned, no target


if __name__ == "__main__":
    unittest.main()
