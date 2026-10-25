"""Candidate-bound MAEP-022 capability gate for the Memory implementation."""
import hashlib
import json
from pathlib import Path
import unittest

from maep.core import POLICY_VERSION, validate_capability_evolution_decision


ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = ROOT / "memory"
GATE_PATH = MEMORY_ROOT / "MAEP-022-GATE.json"
EVIDENCE_PATH = MEMORY_ROOT / "MAEP-022-GATE-EVIDENCE.json"
EXCLUDED_GATE_ARTIFACTS = {
    "MAEP-022-GATE.md",
    "MAEP-022-GATE.json",
    "MAEP-022-GATE-EVIDENCE.json",
    # Investigation/report artifact is not an executable candidate input. Excluding
    # it prevents the report's candidate_ref field from self-invalidating its hash.
    "MAEP-022-RUNTIME-BINDING-RECONCILIATION.json",
}


def candidate_fingerprint():
    """Hash the full MAEP-022 integration path, not Memory in isolation.

    The gate/evidence artifacts are excluded to avoid circularity. All source,
    tests, schemas, and policy/architecture contracts across MAEP, Native Authority,
    Brain, Memory, Runtime and Tools & Automation are included so a change to any
    linked contract invalidates the review instead of silently drifting.
    """
    paths = [ROOT / "README.md"]
    for package in ("maep", "brain", "memory", "runtime", "tools_automation"):
        paths.extend(
            path for path in (ROOT / package).rglob("*")
            if path.is_file()
            and path.name not in EXCLUDED_GATE_ARTIFACTS
            and "__pycache__" not in path.parts
            and path.suffix in {".py", ".json", ".md"}
        )
    paths.extend(
        path for path in (ROOT / "docs/architecture/native-authority-v1").rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".md"}
    )
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


class MAEP022CandidateGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))
        cls.evidence_doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.evidence = cls.evidence_doc["evidence_by_id"]

    def test_historical_gate_and_evidence_remain_bound_to_their_original_candidate(self):
        current = candidate_fingerprint()
        self.assertEqual(self.gate["candidate_ref"], self.evidence_doc["candidate_ref"])
        self.assertNotEqual(self.gate["candidate_ref"], current)

    def test_historical_pass_is_not_current_authorization(self):
        self.assertEqual(self.gate["policy_version"], POLICY_VERSION)
        self.assertEqual(self.gate["decision"], "EXTEND_EXISTING")
        self.assertEqual(self.gate["gate_status"], "PASS")  # historical result only
        self.assertEqual(self.gate["inventory_status"], "COMPLETE")
        self.assertTrue(self.gate["overlap_detected"])
        self.assertNotEqual(self.gate["candidate_ref"], candidate_fingerprint())
        self.assertEqual(
            self.gate["chronology_disposition"],
            "RETROSPECTIVE_CANDIDATE_REVIEW_NOT_PREAUTHORIZATION",
        )

    def test_evidence_is_resolved_and_candidate_bound(self):
        # Historical evidence still matches the historical gate, but neither is current.
        self.assertEqual(self.evidence_doc["candidate_ref"], self.gate["candidate_ref"])
        refs = (
            self.gate["inventory_evidence_refs"]
            + self.gate["comparison_evidence_refs"]
            + self.gate["impact_analysis_refs"]
            + self.gate["regression_test_refs"]
        )
        self.assertTrue(refs)
        for evidence_id in refs:
            with self.subTest(evidence_id=evidence_id):
                evidence = self.evidence[evidence_id]
                self.assertEqual(evidence["evidence_id"], evidence_id)
                self.assertEqual(evidence["candidate_ref"], self.gate["candidate_ref"])
                self.assertTrue(evidence["result"].upper().startswith("PASS"))

    def test_validator_accepts_a_candidate_bound_gate_fixture(self):
        # Validate the schema/logic with an isolated fixture; do not relabel old
        # evidence as if it covered the current worktree candidate.
        record = json.loads(json.dumps(self.gate))
        evidence = json.loads(json.dumps(self.evidence))
        candidate_ref = "candidate:test-fixture"
        record["candidate_ref"] = candidate_ref
        for item in evidence.values():
            item["candidate_ref"] = candidate_ref
        self.assertTrue(validate_capability_evolution_decision(
            record, evidence_by_id=evidence,
            candidate_ref=candidate_ref, policy_version=POLICY_VERSION,
        ))

    def test_historical_gate_is_stale_for_current_candidate(self):
        # The artifact digest excludes gate files to avoid circularity, but includes
        # source/tests/contracts. A code change invalidates the historical gate.
        self.assertNotEqual(self.gate["candidate_ref"], candidate_fingerprint())

    def test_missing_gate_evidence_is_rejected_by_maep(self):
        evidence_id = self.gate["comparison_evidence_refs"][0]
        broken = dict(self.evidence)
        broken.pop(evidence_id)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            validate_capability_evolution_decision(
                self.gate,
                evidence_by_id=broken,
                candidate_ref=self.gate["candidate_ref"],
                policy_version=POLICY_VERSION,
            )


if __name__ == "__main__":
    unittest.main()
