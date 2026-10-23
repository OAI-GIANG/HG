"""RT-03: AcceptanceGate statuses come from the task store's candidate-bound evidence (MAEP-008, 011, 013, 024)."""
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.verification.evidence import AcceptanceGate, EventLog
from hg.tests.support import Clock, TempDirMixin, make_task


def evidence(evidence_id, *, candidate="sha256:good", result="PASS", evidence_type="TEST_RESULT",
             criteria=("AC-1",)):
    return {"evidence_id": evidence_id, "evidence_type": evidence_type, "source_ref": "verifier:AC-1",
            "candidate_ref": candidate, "collected_at": "2026-10-23T08:00:00+00:00",
            "collector": "test", "method": "unit", "result": result, "limitations": [],
            "test_ids": list(criteria)}


def snapshot(*records, candidate="sha256:good"):
    return {"task": make_task(), "result": {"result_ref": "r", "candidate_ref": candidate} if candidate else None,
            "evidence": {e["evidence_id"]: e for e in records}}


class GateStatusTests(unittest.TestCase):
    def setUp(self):
        self.gate = AcceptanceGate(clock=Clock())

    def status(self, snap):
        return self.gate.gates(snap)[0]

    def test_no_evidence_is_not_run(self):
        gate = self.status(snapshot())
        self.assertEqual((gate["status"], gate["evidence_refs"]), ("NOT_RUN", []))
        self.assertFalse(self.gate.evaluate(snapshot())["passed"])

    def test_no_result_is_not_run(self):
        self.assertEqual(self.status(snapshot(evidence("EV-1"), candidate=None))["status"], "NOT_RUN")

    def test_evidence_for_other_candidate_is_not_counted(self):
        gate = self.status(snapshot(evidence("EV-1", candidate="sha256:old")))
        self.assertEqual((gate["status"], gate["evidence_refs"]), ("NOT_RUN", []))

    def test_wrong_evidence_type_is_not_counted(self):
        self.assertEqual(self.status(snapshot(evidence("EV-1", evidence_type="OBSERVATION")))["status"], "NOT_RUN")

    def test_evidence_for_other_criterion_is_not_counted(self):
        self.assertEqual(self.status(snapshot(evidence("EV-1", criteria=("AC-2",))))["status"], "NOT_RUN")

    def test_evidence_without_criterion_link_is_not_counted(self):
        record = evidence("EV-1")
        del record["test_ids"]
        self.assertEqual(self.status(snapshot(record))["status"], "NOT_RUN")

    def test_failing_evidence_fails_even_beside_a_pass(self):
        snap = snapshot(evidence("EV-1"), evidence("EV-2", result="FAIL"))
        self.assertEqual(self.status(snap)["status"], "FAIL")
        self.assertFalse(self.gate.evaluate(snap)["passed"])

    def test_matching_pass_passes_and_closes(self):
        snap = snapshot(evidence("EV-1"))
        gate = self.status(snap)
        self.assertEqual((gate["status"], gate["evidence_refs"]), ("PASS", ["EV-1"]))
        self.assertTrue(self.gate.evaluate(snap)["passed"])
        self.assertEqual(self.gate.build_closure(snap)["evidence_refs"], ["EV-1"])

    def test_closure_refused_without_mandatory_criterion(self):
        snap = snapshot(evidence("EV-1"))
        snap["task"]["acceptance_criteria"][0]["mandatory"] = False
        with self.assertRaises(MAEPError):
            self.gate.build_closure(snap)


class EventLogTests(TempDirMixin):
    def test_non_contiguous_sequence_rejected(self):
        log = EventLog(Path(self.tmp) / "actions.jsonl")
        log.append("X", "T-1", {})
        log.append("X", "T-1", {})
        path = Path(log.path)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[1] + "\n", encoding="utf-8")     # first event deleted
        with self.assertRaisesRegex(MAEPError, "not contiguous"):
            EventLog(path)

    def test_event_visible_only_after_disk_write(self):
        log = EventLog(Path(self.tmp) / "actions.jsonl")
        log.append("X", "T-1", {"a": 1})
        self.assertEqual(len(EventLog(log.path).events()), 1)


if __name__ == "__main__":
    unittest.main()
