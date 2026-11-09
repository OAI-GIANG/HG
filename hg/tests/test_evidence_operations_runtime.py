"""EC07 part 2 through the HG runtime path: BrainOrchestrator -> TaskWriter -> TaskStore -> ledger.

A caller that loses the acknowledgement of an evidence append retries with the same
operation_id; the runtime replays the committed record instead of appending a second one.
Fixtures are synthetic runtimes in temporary directories.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hg.runtime import build_runtime
from hg.tests.test_independent_verification import _task
from maep.core import MAEPError
from maep.ledger import append_event, read_events
from maep.task_store import LedgerOutcomeUnknown, TaskStore

TASK = "S03-EVIDENCE-1"


class RuntimeEvidenceOperationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workdir = Path(directory.name) / "runtime"
        self.runtime = build_runtime(self.workdir, [], allow_fixture_grants=True)
        self.runtime.orch.submit_task(_task())
        self.runtime.orch.assess(TASK)

    def evidence_events(self):
        return [e for e in read_events(self.workdir / "tasks.jsonl")
                if e["type"] == "EVIDENCE_RECORDED" and e["task_id"] == TASK]

    def artifact(self, raw, *, operation_id, result="CAPTURED"):
        return self.runtime.orch.record_artifact_evidence(
            TASK, raw, evidence_type="ARTIFACT", source_ref="test://ec07/raw", candidate_ref="candidate:sha256:ec07",
            method="test_evidence_operation", result=result, payload_kind="text/plain",
            limitations=["synthetic fixture; not production evidence"], operation_id=operation_id,
        )

    def test_lost_ledger_acknowledgement_then_retry_links_the_artifact_once(self):
        raw = b"evidence appended, acknowledgement lost\n"

        def append_then_fail(path, event):
            append_event(path, event)
            raise OSError("fsync failed after the write")

        with mock.patch.object(self.runtime.store, "_append", side_effect=append_then_fail):
            with self.assertRaises(LedgerOutcomeUnknown):
                self.artifact(raw, operation_id="ec07-artifact-1")

        evidence_id = self.artifact(raw, operation_id="ec07-artifact-1")

        (event,) = self.evidence_events()
        self.assertEqual(event["data"]["evidence"]["evidence_id"], evidence_id)
        self.assertEqual(event["data"]["operation_id"], "ec07-artifact-1")
        record = self.runtime.store.snapshot(TASK)["evidence"][evidence_id]
        checked = self.runtime.orch.verify_artifact_evidence(record)
        self.assertEqual(checked["status"], "PASS")
        self.assertEqual(self.runtime.evidence_artifacts.get(checked["payload_ref"]), raw)
        self.assertEqual(self.runtime.evidence_artifacts.find_orphans([checked["payload_ref"]]), [])

        restored = TaskStore.restore(self.workdir / "tasks.jsonl", policy_evaluator=self.runtime.evaluator)
        self.assertEqual(list(restored.snapshot(TASK)["evidence"]), [evidence_id])

    def test_same_operation_with_different_content_is_refused_and_its_blob_is_an_orphan(self):
        first = self.artifact(b"first bytes\n", operation_id="ec07-artifact-2")
        with self.assertRaisesRegex(MAEPError, "operation_id .*conflict"):
            self.artifact(b"other bytes\n", operation_id="ec07-artifact-2")
        self.assertEqual(len(self.evidence_events()), 1)
        # The refused bytes were published first (two-step protocol): a discoverable orphan, never linked.
        linked = self.runtime.store.snapshot(TASK)["evidence"][first]["integrity_metadata"]["payload_ref"]
        orphans = self.runtime.evidence_artifacts.find_orphans([linked])
        self.assertEqual(len(orphans), 1)
        self.assertEqual(self.runtime.evidence_artifacts.get(orphans[0]), b"other bytes\n")

    def test_observation_retry_with_same_operation_returns_the_committed_id(self):
        first = self.runtime.orch.record_observation(TASK, source_ref="test://ec07/obs", method="observe",
                                                     result="SEEN", operation_id="ec07-obs-1")
        again = self.runtime.orch.record_observation(TASK, source_ref="test://ec07/obs", method="observe",
                                                     result="SEEN", operation_id="ec07-obs-1")
        self.assertEqual(again, first)
        self.assertEqual(len(self.evidence_events()), 1)

    def test_without_an_operation_each_call_is_a_new_record(self):
        first = self.runtime.orch.record_observation(TASK, source_ref="test://ec07/obs", method="observe",
                                                     result="SEEN")
        second = self.runtime.orch.record_observation(TASK, source_ref="test://ec07/obs", method="observe",
                                                      result="SEEN")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.evidence_events()), 2)
        self.assertTrue(all("operation_id" not in e["data"] for e in self.evidence_events()))


if __name__ == "__main__":
    unittest.main()
