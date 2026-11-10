"""False-accept oracle for evidence-store reads (WS-04).

Each case starts from a payload committed through the runtime and then damages the
stored blob or the metadata that references it. The expected outcome comes from how the
case was built: none of these reads may return bytes or a PASS. Controls show that an
undamaged reference still verifies, so a store that rejects everything cannot satisfy
the oracle. A read must also fail promptly: a special file planted at a blob path must
not block the reader.
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hg.runtime import build_runtime
from hg.verification.artifacts import EvidenceArtifactError, EvidenceArtifactStore
from hg.verification.independent import IndependentVerifier
from maep.core import MAEPError

_PAYLOAD = b"raw evidence: 12 passed, 0 failed\n"
_OTHER = b"different evidence bytes\n"
_PROMPT_SECONDS = 5.0


def _task(task_id):
    from maep.core import POLICY_VERSION
    return {
        "task_id": task_id,
        "objective": "Evidence-store read oracle",
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
    started = time.monotonic()
    thread.start()
    thread.join(_PROMPT_SECONDS)
    hung = thread.is_alive()
    if hung and release_path is not None:
        try:
            os.close(os.open(release_path, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        thread.join(_PROMPT_SECONDS)
    return hung, out, time.monotonic() - started


class EvidenceStoreReadOracleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name).resolve() / "runtime"
        self.runtime = build_runtime(self.workdir, [], allow_fixture_grants=True)
        self.runtime.orch.submit_task(_task("ORACLE-1"))
        self.runtime.orch.assess("ORACLE-1")
        evidence_id = self.runtime.orch.record_artifact_evidence(
            "ORACLE-1", _PAYLOAD, evidence_type="ARTIFACT", source_ref="test://oracle/raw",
            candidate_ref="candidate:oracle", method="oracle_capture", result="CAPTURED",
            payload_kind="text/plain", limitations=["test fixture"])
        self.record = self.runtime.store.snapshot("ORACLE-1")["evidence"][evidence_id]
        self.meta = dict(self.record["integrity_metadata"])
        self.store = self.runtime.evidence_artifacts
        self.blob = self.store._blob_path(self.meta["sha256"])

    def _assert_never_accepted(self, label, *, release_path=None):
        """The runtime read path and the raw store read must both refuse, promptly."""
        for name, fn in (
            ("verify_artifact_evidence", lambda: self.runtime.orch.verify_artifact_evidence(self.record)),
            ("get", lambda: self.store.get(self.meta["payload_ref"])),
        ):
            with self.subTest(case=label, read=name):
                hung, out, _ = _call_with_deadline(fn, release_path)
                self.assertFalse(hung, f"{name} blocked instead of failing")
                self.assertNotIn("value", out, out)
                self.assertIsInstance(out.get("error"), MAEPError, out)

    def _replace_blob(self, maker):
        self.blob.unlink()
        maker(self.blob)

    # -- control --------------------------------------------------------------------
    def test_control_undamaged_reference_verifies(self):
        checked = self.runtime.orch.verify_artifact_evidence(self.record)
        self.assertEqual(checked["status"], "PASS")
        self.assertEqual(self.store.get(self.meta["payload_ref"]), _PAYLOAD)

    # -- damaged blob bytes ---------------------------------------------------------
    def test_damaged_blob_bytes_are_never_accepted(self):
        cases = {
            "flipped byte": bytes([_PAYLOAD[0] ^ 1]) + _PAYLOAD[1:],
            "truncated": _PAYLOAD[:-1],
            "empty": b"",
            "appended": _PAYLOAD + b"\n",
            "other payload": _OTHER,
        }
        for label, data in cases.items():
            self.blob.write_bytes(data)
            os.chmod(self.blob, 0o600)
            self._assert_never_accepted(label)

    def test_blob_of_another_digest_moved_into_place_is_never_accepted(self):
        other = self.store.put(_OTHER)
        os.replace(self.store._blob_path(other["sha256"]), self.blob)
        self._assert_never_accepted("swapped blob")

    def test_hardlink_to_another_blob_is_never_accepted(self):
        other = self.store.put(_OTHER)
        self._replace_blob(lambda p: os.link(self.store._blob_path(other["sha256"]), p))
        self._assert_never_accepted("hardlink")

    # -- wrong file type or ownership bits --------------------------------------------
    def test_non_regular_or_non_private_blob_is_never_accepted(self):
        decoy = self.workdir.parent / "decoy"
        decoy.write_bytes(_PAYLOAD)
        os.chmod(decoy, 0o600)
        self._replace_blob(lambda p: os.symlink(decoy, p))
        self._assert_never_accepted("symlink to identical bytes")
        self.blob.unlink()
        self.blob.write_bytes(_PAYLOAD)
        for mode in (0o640, 0o604, 0o620):
            os.chmod(self.blob, mode)
            self._assert_never_accepted(f"mode {oct(mode)}")
        os.chmod(self.blob, 0o600)

    def test_directory_at_blob_path_is_never_accepted(self):
        self._replace_blob(lambda p: p.mkdir(mode=0o700))
        self._assert_never_accepted("directory")

    def test_fifo_at_blob_path_fails_promptly(self):
        # Opening a FIFO for reading blocks until a writer appears. A reader that does
        # not open non-blocking would hang the verification of the whole task.
        self._replace_blob(lambda p: os.mkfifo(p, 0o600))
        self._assert_never_accepted("fifo", release_path=self.blob)

    def test_fifo_at_blob_path_does_not_block_a_rewrite(self):
        self._replace_blob(lambda p: os.mkfifo(p, 0o600))
        hung, out, _ = _call_with_deadline(lambda: self.store.put(_PAYLOAD), self.blob)
        self.assertFalse(hung, "put blocked on a FIFO at the blob path")
        self.assertIsInstance(out.get("error"), EvidenceArtifactError, out)

    def test_namespace_damage_is_never_accepted(self):
        prefix = self.blob.parent
        os.chmod(prefix, 0o755)
        self._assert_never_accepted("group/world readable digest directory")
        os.chmod(prefix, 0o700)
        os.chmod(self.store.root, 0o750)
        self._assert_never_accepted("group readable root")
        os.chmod(self.store.root, 0o700)

    # -- damaged metadata ----------------------------------------------------------------
    def test_damaged_metadata_is_never_accepted(self):
        digest = self.meta["sha256"]
        other = self.store.put(_OTHER)
        cases = {
            "size off by one": {**self.meta, "payload_bytes": self.meta["payload_bytes"] + 1},
            "size zero": {**self.meta, "payload_bytes": 0},
            "size bool": {**self.meta, "payload_bytes": True},
            "size negative": {**self.meta, "payload_bytes": -1},
            "size string": {**self.meta, "payload_bytes": str(self.meta["payload_bytes"])},
            "ref/digest disagree": {**self.meta, "payload_ref": other["payload_ref"]},
            "digest uppercase": {**self.meta, "sha256": digest.upper(),
                                 "payload_ref": "sha256:" + digest.upper()},
            "digest trailing newline": {**self.meta, "sha256": digest + "\n",
                                        "payload_ref": "sha256:" + digest + "\n"},
            "digest short": {**self.meta, "sha256": digest[:63], "payload_ref": "sha256:" + digest[:63]},
            "ref other scheme": {**self.meta, "payload_ref": "md5:" + digest},
            "missing ref": {k: v for k, v in self.meta.items() if k != "payload_ref"},
            "missing digest": {k: v for k, v in self.meta.items() if k != "sha256"},
            "absent blob": {**self.meta, "sha256": "0" * 64, "payload_ref": "sha256:" + "0" * 64},
        }
        for label, metadata in cases.items():
            with self.subTest(label):
                with self.assertRaises(MAEPError):
                    self.runtime.orch.verify_artifact_evidence({**self.record, "integrity_metadata": metadata})
        for label, ref in {
            "traversal": "sha256:../" + digest[3:],
            "no prefix": digest,
            "bytes": ("sha256:" + digest).encode(),
            "uppercase": "sha256:" + digest.upper(),
        }.items():
            with self.subTest(label):
                with self.assertRaises(EvidenceArtifactError):
                    self.store.get(ref)
        self.assertIsInstance(self.runtime.orch.verify_artifact_evidence(self.record), dict)

    def test_read_only_view_rejects_the_same_damage(self):
        view = EvidenceArtifactStore(self.store.root, read_only=True)
        self.assertEqual(view.get(self.meta["payload_ref"]), _PAYLOAD)
        self.blob.write_bytes(_OTHER)
        os.chmod(self.blob, 0o600)
        with self.assertRaises(EvidenceArtifactError):
            view.get(self.meta["payload_ref"])


class VerifierSpecialFileTests(unittest.TestCase):
    """The independent verifier must refuse a FIFO candidate without waiting for its timeout."""

    def test_fifo_candidate_is_rejected_before_the_worker_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            os.mkfifo(root / "x.py", 0o600)
            os.mkfifo(root / "x.sqlite3", 0o600)
            verifier = IndependentVerifier()
            for label, call in (
                ("python", lambda: verifier.verify_python_syntax(root, "x.py", candidate_ref="f")),
                ("sqlite", lambda: verifier.verify_sqlite_integrity(root, "x.sqlite3", candidate_ref="f")),
            ):
                with self.subTest(label):
                    started = time.monotonic()
                    report = call()
                    elapsed = time.monotonic() - started
                    self.assertNotEqual(report["status"], "PASS", report)
                    self.assertNotEqual(report["status"], "INCONCLUSIVE", report)
                    self.assertLess(elapsed, _PROMPT_SECONDS, report)
                    self.assertIn("regular file", report.get("reason", ""), report)


if __name__ == "__main__":
    unittest.main()
