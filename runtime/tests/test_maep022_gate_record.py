"""The fs.write/acceptance MAEP-022 gate record passes the fail-closed gate validator.

The record is the change-plan entry for this capability (MAEP_EXECUTION_PROTOCOL_V1:
use existing records only). Every referenced evidence item must resolve, be bound to
the record's candidate and carry an explicit PASS, or validation fails.
"""
import copy
import json
from pathlib import Path
import unittest

from maep.core import MAEPError, POLICY_VERSION, validate_capability_evolution_decision

RECORD = Path(__file__).resolve().parents[2] / "docs/architecture/maep022/fs-write-acceptance-gate-20261026.json"


class FsWriteAcceptanceGateRecordTests(unittest.TestCase):
    def setUp(self):
        doc = json.loads(RECORD.read_text(encoding="utf-8"))
        self.gate = doc["gate"]
        self.evidence = {item["evidence_id"]: item for item in doc["evidence"]}

    def validate(self, gate=None, evidence=None):
        return validate_capability_evolution_decision(
            gate or self.gate, evidence_by_id=evidence or self.evidence,
            candidate_ref=self.gate["candidate_ref"], policy_version=POLICY_VERSION)

    def test_record_passes_the_gate_validator(self):
        self.assertIs(self.validate(), True)
        self.assertEqual((self.gate["decision"], self.gate["gate_status"]), ("EXTEND_EXISTING", "PASS"))
        self.assertNotIn("retire_candidates", self.gate)       # nothing is retired

    def test_unresolved_unpassing_or_rebound_evidence_fails_closed(self):
        for evidence_id in self.evidence:
            with self.subTest(missing=evidence_id):
                evidence = dict(self.evidence)
                evidence.pop(evidence_id)
                with self.assertRaises(MAEPError):
                    self.validate(evidence=evidence)
            with self.subTest(not_passing=evidence_id):
                evidence = copy.deepcopy(self.evidence)
                evidence[evidence_id]["result"] = "NOT_RUN — " + evidence[evidence_id]["result"]
                with self.assertRaises(MAEPError):
                    self.validate(evidence=evidence)
            with self.subTest(other_candidate=evidence_id):
                evidence = copy.deepcopy(self.evidence)
                evidence[evidence_id]["candidate_ref"] = "git:" + "0" * 40
                with self.assertRaises(MAEPError):
                    self.validate(evidence=evidence)
        for changes in ({"gate_status": "NOT_RUN"}, {"decision": "UNKNOWN"}, {"inventory_status": "PARTIAL"},
                        {"candidate_ref": "git:" + "1" * 40}, {"superiority_basis": {"correctness": "x"}}):
            with self.subTest(changes=changes):
                with self.assertRaises(MAEPError):
                    self.validate(gate=dict(self.gate, **changes))


if __name__ == "__main__":
    unittest.main()
