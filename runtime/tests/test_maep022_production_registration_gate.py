"""Validate the owner-authorized MAEP-022 follow-on for runtime.service production factory binding registration.

Every gate reference resolves to explicit candidate-bound PASS evidence. This is a code
registration gate; it deliberately does not imply deployment of the separate hg serve runtime.
"""
import copy
import json
from pathlib import Path
import unittest

from maep.core import MAEPError, POLICY_VERSION, validate_capability_evolution_decision

RECORD = Path(__file__).resolve().parents[2] / "docs/architecture/maep022/production-binding-registration-gate-20261026.json"


class ProductionBindingRegistrationGateTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(RECORD.read_text(encoding="utf-8"))
        self.gate = self.doc["gate"]
        self.evidence = {item["evidence_id"]: item for item in self.doc["evidence"]}

    def validate(self, gate=None, evidence=None):
        return validate_capability_evolution_decision(
            gate or self.gate,
            evidence_by_id=self.evidence if evidence is None else evidence,
            candidate_ref=self.gate["candidate_ref"],
            policy_version=POLICY_VERSION,
        )

    def test_registration_gate_passes_for_exact_code_candidate(self):
        self.assertIs(self.validate(), True)
        self.assertEqual(self.gate["candidate_ref"], "git:a10d8d2a7c23c64a7a088eeebbc0a88b5e0ec616")
        self.assertEqual((self.gate["decision"], self.gate["gate_status"]), ("EXTEND_EXISTING", "PASS"))
        self.assertIn("runtime.service production factory binding registration", self.gate["scope"])
        self.assertIn("Owner instruction", self.evidence["EV-REG-OWNER-AUTH"]["source_ref"])
        self.assertIn("explicitly instructed completion", self.evidence["EV-REG-OWNER-AUTH"]["result"])

    def test_missing_nonpassing_or_rebound_evidence_fails_closed(self):
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

    def test_gate_does_not_claim_or_authorize_live_deployment(self):
        impact = self.evidence["EV-REG-IMPACT"]["result"].lower()
        owner_scope = self.evidence["EV-REG-OWNER-AUTH"]["limitations"]
        self.assertIn("no production config/state/session was changed", impact)
        self.assertTrue(any("does not authorize deploying" in item for item in owner_scope))
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        self.assertIn("deployment: **not performed**", readme)


if __name__ == "__main__":
    unittest.main()
