import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hg.runtime import build_runtime
from hg.tests.support import TempDirMixin, grant, make_task, write_step
from hg.verification.artifacts import EvidenceArtifactError, EvidenceArtifactStore
from hg.verification.bounded import EvidenceWindowError, extract_log_window
from hg.verification.independent import IndependentVerifier, python_syntax_verifier
from maep.admission import RuntimeWriterSession
from maep.core import MAEPError, validate_evidence


def _task(task_id="S03-EVIDENCE-1"):
    from maep.core import POLICY_VERSION
    return {
        "task_id": task_id,
        "objective": "Exercise S03 evidence storage",
        "scope": {"include": ["evidence/"], "exclude": []},
        "inputs": [],
        "outputs": [{"name": "evidence", "description": "candidate-bound evidence"}],
        "acceptance_criteria": [{
            "criterion_id": "AC-S03-1",
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


class EvidenceMetadataValidationTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "evidence_id": "EV-S03-1",
            "evidence_type": "ARTIFACT",
            "source_ref": "test://evidence",
            "candidate_ref": "candidate:1",
            "collected_at": "2026-11-03T00:00:00Z",
            "collector": "s03-test",
            "method": "unit-test",
            "result": "PASS",
            "limitations": [],
        }

    def test_scalar_integrity_metadata_is_valid(self):
        self.record["integrity_metadata"] = {
            "payload_ref": "sha256:" + "a" * 64,
            "sha256": "a" * 64,
            "payload_bytes": 12,
            "payload_store": "content-addressed-filesystem-v1",
        }
        self.assertTrue(validate_evidence(self.record))

    def test_nested_integrity_metadata_is_rejected(self):
        self.record["integrity_metadata"] = {"nested": {"not": "scalar"}}
        with self.assertRaises(MAEPError):
            validate_evidence(self.record)

    def test_non_finite_integrity_metadata_number_is_rejected(self):
        self.record["integrity_metadata"] = {"not_a_number": float("nan")}
        with self.assertRaises(MAEPError):
            validate_evidence(self.record)


class EvidenceArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir(mode=0o700)
        self.store = EvidenceArtifactStore(self.state / "evidence-artifacts")

    def test_content_addressed_write_read_and_deduplicate(self):
        payload = b"original raw evidence\nsecond line\n"
        metadata = self.store.put(payload)
        self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(metadata["payload_ref"], "sha256:" + metadata["sha256"])
        self.assertEqual(self.store.get(metadata["payload_ref"]), payload)
        self.assertEqual(self.store.verify_metadata(metadata)["status"], "PASS")
        before = list((self.state / "evidence-artifacts" / "sha256").rglob("*"))
        self.assertEqual(self.store.put(payload), metadata)
        after = list((self.state / "evidence-artifacts" / "sha256").rglob("*"))
        self.assertEqual(len([p for p in before if p.is_file()]), len([p for p in after if p.is_file()]))

    def test_payload_tampering_is_detected(self):
        metadata = self.store.put(b"untampered")
        path = self.store._blob_path(metadata["sha256"])
        path.write_bytes(b"tampered!!")
        with self.assertRaises(EvidenceArtifactError):
            self.store.verify_metadata(metadata)

    def test_size_limit_is_enforced_on_write_and_read(self):
        with self.assertRaises(EvidenceArtifactError):
            self.store.put(b"12345", max_bytes=4)
        metadata = self.store.put(b"12345", max_bytes=8)
        with self.assertRaises(EvidenceArtifactError):
            self.store.get(metadata["payload_ref"], max_bytes=4)

    def test_orphans_are_reported_but_never_deleted(self):
        referenced = self.store.put(b"referenced")
        orphan = self.store.put(b"orphan")
        self.assertEqual(self.store.find_orphans([referenced["payload_ref"]]), [orphan["payload_ref"]])
        self.assertEqual(self.store.get(orphan["payload_ref"]), b"orphan")

    def test_unpublished_temporary_file_is_reported_separately(self):
        root = self.state / "evidence-artifacts"
        namespace = root / "sha256"
        prefix = namespace / "aa"
        root.mkdir(mode=0o700)
        namespace.mkdir(mode=0o700)
        prefix.mkdir(mode=0o700)
        temp = prefix / ".tmp-interrupted-write"
        temp.write_bytes(b"partial")
        temp.chmod(0o600)
        self.assertEqual(self.store.find_temporary_artifacts(), ["sha256/aa/.tmp-interrupted-write"])
        self.assertEqual(self.store.find_orphans([]), [])
        self.assertTrue(temp.exists())

    def test_custom_read_limit_rejects_non_integer_values(self):
        metadata = self.store.put(b"data")
        for invalid in (True, 0, -1, "4"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(EvidenceArtifactError):
                    self.store.get(metadata["payload_ref"], max_bytes=invalid)

    def test_read_only_view_refuses_writes(self):
        self.store.put(b"present")
        read_only = EvidenceArtifactStore(self.state / "evidence-artifacts", read_only=True)
        with self.assertRaises(EvidenceArtifactError):
            read_only.put(b"must-not-write")

    def test_symlink_root_is_rejected(self):
        target = self.state / "real"
        target.mkdir(mode=0o700)
        link = self.state / "linked"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(EvidenceArtifactError):
            EvidenceArtifactStore(link)

    def test_broken_symlink_root_is_rejected(self):
        link = self.state / "broken"
        link.symlink_to(self.state / "missing", target_is_directory=True)
        with self.assertRaises(EvidenceArtifactError):
            EvidenceArtifactStore(link)

    def test_get_rejects_symlinked_digest_directory(self):
        metadata = self.store.put(b"namespace-safe")
        namespace = self.state / "evidence-artifacts" / "sha256"
        prefix = namespace / metadata["sha256"][:2]
        moved = namespace / (metadata["sha256"][:2] + "-real")
        prefix.rename(moved)
        prefix.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(EvidenceArtifactError):
            self.store.get(metadata["payload_ref"])

    def test_protected_state_requires_the_active_writer_session(self):
        marker = self.state / ".writer.lock"
        fd = os.open(marker, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with self.assertRaises(MAEPError):
                EvidenceArtifactStore(self.state / "evidence-artifacts")
            session = RuntimeWriterSession(self.state, fd)
            store = EvidenceArtifactStore(
                self.state / "evidence-artifacts",
                writer_session=session,
            )
            self.assertFalse(store.read_only)
            session.close()
            fd = None
        finally:
            if fd is not None:
                os.close(fd)


class RuntimeEvidenceIntegrationTests(unittest.TestCase):
    def test_artifact_reference_is_committed_to_maep_ledger_and_survives_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "runtime"
            runtime = build_runtime(workdir, [], allow_fixture_grants=True)
            runtime.orch.submit_task(_task())
            runtime.orch.assess("S03-EVIDENCE-1")
            raw = b"raw test output: ERROR sample\n"
            evidence_id = runtime.orch.record_artifact_evidence(
                "S03-EVIDENCE-1", raw,
                evidence_type="ARTIFACT",
                source_ref="test://s03/raw-output",
                candidate_ref="candidate:sha256:abc",
                method="test_artifact_capture",
                result="CAPTURED",
                payload_kind="text/plain",
                limitations=["test fixture; not production evidence"],
            )
            snapshot = runtime.store.snapshot("S03-EVIDENCE-1")
            record = snapshot["evidence"][evidence_id]
            checked = runtime.orch.verify_artifact_evidence(record)
            self.assertEqual(checked["status"], "PASS")
            self.assertEqual(runtime.evidence_artifacts.get(checked["payload_ref"]), raw)

            from maep.task_store import TaskStore
            restored = TaskStore.restore(workdir / "tasks.jsonl", policy_evaluator=runtime.evaluator)
            replayed = restored.snapshot("S03-EVIDENCE-1")["evidence"][evidence_id]
            self.assertEqual(replayed["integrity_metadata"]["sha256"], checked["sha256"])
            self.assertEqual(runtime.evidence_artifacts.verify_metadata(replayed["integrity_metadata"])["status"], "PASS")


class IndependentVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.verifier = IndependentVerifier(timeout_s=5)

    def test_python_syntax_passes_in_separate_process_without_bytecode(self):
        source = b"def add(a, b):\n    return a + b\n"
        (self.root / "good.py").write_bytes(source)
        expected = hashlib.sha256(source).hexdigest()
        report = self.verifier.verify_python_syntax(
            self.root, "good.py", candidate_ref="candidate-A", expected_sha256=expected
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["candidate_ref"], "candidate-A")
        self.assertEqual(report["sha256"], expected)
        self.assertIn("separate-process-same-uid", report["verification_boundary"])
        self.assertFalse((self.root / "__pycache__").exists())

    def test_python_syntax_failure_is_not_promoted_to_pass(self):
        (self.root / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
        report = self.verifier.verify_python_syntax(self.root, "bad.py", candidate_ref="candidate-B")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("reason", report)

    def test_expected_candidate_hash_mismatch_fails(self):
        (self.root / "main.py").write_text("x = 1\n", encoding="utf-8")
        report = self.verifier.verify_python_syntax(
            self.root, "main.py", candidate_ref="candidate-C", expected_sha256="0" * 64
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("does not match", report["reason"])

    def test_path_traversal_is_blocked(self):
        report = self.verifier.verify_python_syntax(self.root, "../escape.py", candidate_ref="candidate-D")
        self.assertEqual(report["status"], "BLOCKED")

    def test_symlink_target_is_blocked(self):
        outside = self.root / "outside.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        link = self.root / "link.py"
        link.symlink_to(outside)
        report = self.verifier.verify_python_syntax(self.root, "link.py", candidate_ref="candidate-E")
        self.assertEqual(report["status"], "BLOCKED")

    def test_sqlite_integrity_passes_read_only_and_does_not_change_bytes(self):
        db_path = self.root / "state.sqlite3"
        db = sqlite3.connect(db_path)
        try:
            db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO sample(value) VALUES ('ok')")
            db.commit()
        finally:
            db.close()
        before = hashlib.sha256(db_path.read_bytes()).hexdigest()
        report = self.verifier.verify_sqlite_integrity(self.root, "state.sqlite3", candidate_ref="candidate-F")
        after = hashlib.sha256(db_path.read_bytes()).hexdigest()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["integrity_result"], "ok")
        self.assertEqual(before, after)

    def test_invalid_sqlite_is_not_passed(self):
        (self.root / "bad.sqlite3").write_bytes(b"not a database")
        report = self.verifier.verify_sqlite_integrity(self.root, "bad.sqlite3", candidate_ref="candidate-G")
        self.assertEqual(report["status"], "BLOCKED")

    def test_wal_backed_database_is_blocked_until_a_closed_snapshot_exists(self):
        db_path = self.root / "live.sqlite3"
        db = sqlite3.connect(db_path)
        try:
            db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
            db.commit()
        finally:
            db.close()
        Path(str(db_path) + "-wal").write_bytes(b"active-wal-marker")
        report = self.verifier.verify_sqlite_integrity(self.root, "live.sqlite3", candidate_ref="candidate-H")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("closed consistent copy", report["reason"])


class BoundedEvidenceWindowTests(unittest.TestCase):
    def test_error_context_is_selected_even_when_error_is_not_at_tail(self):
        lines = [f"INFO line {n}" for n in range(1, 101)]
        lines[4] = "Traceback (most recent call last):"
        lines[5] = "ValueError: broken"
        payload = "\n".join(lines).encode()
        report = extract_log_window(payload, context_lines=1, max_output_bytes=2048)
        self.assertEqual(report["selection"], "error-context")
        self.assertEqual(report["matched_error_lines"], [5, 6])
        self.assertIn("[L5]", report["excerpt"])
        self.assertIn("[L6]", report["excerpt"])
        self.assertTrue(report["raw_evidence_preserved"])
        self.assertEqual(report["source_sha256"], hashlib.sha256(payload).hexdigest())

    def test_tail_fallback_is_bounded_and_source_linked(self):
        payload = "\n".join(f"INFO {n}" for n in range(1, 101))
        report = extract_log_window(payload, tail_lines=5, max_output_bytes=1024)
        self.assertEqual(report["selection"], "tail-fallback")
        self.assertEqual(report["line_ranges"], [[96, 100]])
        self.assertIn("[L100]", report["excerpt"])

    def test_excerpt_output_limit_is_enforced(self):
        payload = "\n".join("ERROR " + ("x" * 200) for _ in range(20))
        report = extract_log_window(payload, max_output_bytes=128)
        self.assertLessEqual(report["output_bytes"], 128)
        self.assertTrue(report["truncated"])

    def test_input_limit_and_argument_types_are_enforced(self):
        with self.assertRaises(EvidenceWindowError):
            extract_log_window(b"x" * 20, max_source_bytes=10)
        with self.assertRaises(EvidenceWindowError):
            extract_log_window("ok", tail_lines=True)


class IndependentProcessOrchestratorIntegrationTests(TempDirMixin):
    def test_structured_inconclusive_result_blocks_gate_without_false_failure(self):
        def unavailable(_snapshot):
            return {"status": "INCONCLUSIVE", "reason": "worker timed out"}
        runtime = self.build(
            [grant()],
            verifiers={"AC-1": unavailable},
        )
        final = runtime.orch.execute_task(make_task(), [write_step()])
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        report = runtime.gate.evaluate(final)
        self.assertEqual(report["gates"][0]["status"], "BLOCKED")
        self.assertEqual([ev["result"] for ev in final["evidence"].values()], ["INCONCLUSIVE"])
        self.assertIsNone(final["closure"])

    def test_separate_process_syntax_result_is_candidate_bound_and_can_close(self):
        source = "def add(a, b):\n    return a + b\n"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        verifier = python_syntax_verifier(self.root, "out/probe.py", digest)
        runtime = self.build(
            [grant(resource="file:out/probe.py")],
            verifiers={"AC-1": verifier},
        )
        final = runtime.orch.execute_task(
            make_task(),
            [write_step(path="out/probe.py", content=source)],
        )
        self.assertEqual(final["task"]["state"], "CLOSED_VERIFIED")
        evidence = next(iter(final["evidence"].values()))
        self.assertEqual(evidence["result"], "PASS")
        self.assertIn("separate Python process", evidence["limitations"][0])
        self.assertIn("same OS UID", evidence["limitations"][0])
        self.assertIn("separate-process-same-uid-not-an-os-sandbox",
                      evidence["integrity_metadata"]["detail"])
        self.assertFalse((self.root / "out" / "__pycache__").exists())

    def test_separate_process_hash_mismatch_prevents_closure(self):
        source = "value = 7\n"
        verifier = python_syntax_verifier(self.root, "out/probe.py", "0" * 64)
        runtime = self.build(
            [grant(resource="file:out/probe.py")],
            verifiers={"AC-1": verifier},
        )
        final = runtime.orch.execute_task(
            make_task(),
            [write_step(path="out/probe.py", content=source)],
        )
        self.assertEqual(final["task"]["state"], "UNVERIFIED")
        self.assertIsNone(final["closure"])
        self.assertEqual([ev["result"] for ev in final["evidence"].values()], ["FAIL"])


if __name__ == "__main__":
    unittest.main()
