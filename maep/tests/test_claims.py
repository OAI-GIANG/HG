import unittest
from maep.core import MAEPError, validate_claim


class ClaimClassificationTests(unittest.TestCase):
    def test_fact_requires_evidence(self):
        with self.assertRaises(MAEPError):
            validate_claim({"claim_id": "C1", "claim_type": "FACT", "statement": "observed",
                            "evidence_refs": [], "limitations": []})

    def test_inference_requires_limitations(self):
        with self.assertRaises(MAEPError):
            validate_claim({"claim_id": "C2", "claim_type": "INFERENCE", "statement": "likely",
                            "evidence_refs": ["E1"], "limitations": []})

    def test_proposal_is_explicitly_classified(self):
        self.assertTrue(validate_claim({"claim_id": "C3", "claim_type": "PROPOSAL", "statement": "try X",
                                        "evidence_refs": [], "limitations": ["not implemented"]}))


if __name__ == "__main__":
    unittest.main()
