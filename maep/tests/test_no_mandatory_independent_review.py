"""OD-IR-20261109: no HG task, gate or lifecycle stage requires an independent reviewer.

The owner decision sets INDEPENDENT_REVIEW_REQUIRED = false globally. These tests prevent old
review mandates from returning in governing instructions, including nested schedules and workflow
files, while preserving technical verification and truthful review labeling.
"""
import re
import unittest
from pathlib import Path

from maep.core import MAEPError, validate_policy_change, validate_review_label

ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "docs" / "governance" / "OWNER_DECISION_OD-IR-20261109.md"
CHECKLIST = ROOT / "maep" / "spec" / "ACCEPTANCE_CHECKLIST_V1.md"

ROOT_FILES = ("CLAUDE.md", "README.md", "AGENTS.md", "CONTRIBUTING.md")
ROOT_GLOBS = ("*.md", "*.mdx", "*.rst", "*.txt", "*.yml", "*.yaml", "*.json", "*.toml")
GOVERNING_DIRS = ("maep", "docs", "deploy", ".claude", ".github")
TEXT_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".yml", ".yaml", ".json", ".toml", ".sh"}

# Immutable dated records and evidence retain their historical wording; they do not govern.
RECORD = re.compile(
    r"^(OWNER_DECISION_OD-IR-\d{8}\.md|HG_MASTER_COMPLETION_LEDGER_V1"
    r"(_RECONCILIATION_\d{8}[A-Z]?)?\.md)$"
)

# These exact evaluation artifacts were recorded on 2026-11-02. The owner decision
# OD-IR-20261109 superseded their former review gate; preserve them as history, not policy.
HISTORICAL_EVALUATION_RECORDS = {
    "docs/architecture/evaluation/r3.1/R3_1_ACCEPTANCE_CROSSWALK_K1-K8.md",
    "docs/architecture/evaluation/r3.1/R3_1_REMEDIATION_REPORT.md",
}

_REVIEW = r"(?:review|reviewer|reviewers|approval|approver|party)"
_KIND = r"(?:independent|external|second|separate|another|different)"
_QUAL = r"(?:human|security|technical|formal|github)"
_KIND_REVIEW = rf"\b{_KIND}\W+(?:{_QUAL}\W+)?{_REVIEW}\b"

# Match affirmative conditions. "Do not merge until ..." is a positive gate on review,
# not a negation of the review requirement.
MANDATE = re.compile(
    r"\b(?:must|shall|requires?|required|requiring|needs?|pending|waiting|waits?\s+for|wait\s+for|until|"
    r"without|chờ|bắt\s+buộc|phải|cần|do\s+not\s+(?:merge|deploy|close|release)|"
    r"cannot\s+(?:merge|deploy|close|release))\b"
    rf"[^.\n|]{{0,60}}?{_KIND_REVIEW}"
    rf"|{_KIND_REVIEW}\W+(?:must|is\s+required|are\s+required|still\s+required|required|"
    r"is\s+mandatory|must\s+be\s+completed|bắt\s+buộc)"
    r"|\bformal\W+independent\W+review\b"
    r"|\b(?:review|reviewer)\W+độc\s+lập\b"
    r"|\b(?:login|reviewer|account)\s+other\s+than\b"
    r"|\btwo[- ]person\b|\bfour[- ]eyes\b",
    re.IGNORECASE,
)

# Exempt only explicit statements that review is NOT required or is merely a label.
# Do not treat "do not merge until independent review" as a negation of review.
EXPLICITLY_NOT_REQUIRED = re.compile(
    r"\bno\s+(?:(?:mandatory|required)\s+)?"
    r"|\b(?:requires?|needs?)\s+no\s+(?:mandatory\s+)?(?:independent|external|second|separate)\W+(?:review|reviewer|approval)\b"
    r"|\bno\s+mandatory\s+independent\s+review\b"
    rf"{_KIND}\W+(?:{_QUAL}\W+)?{_REVIEW}\s+(?:is\s+)?"
    r"(?:required|mandatory|needed|claimed)\b"
    r"|\bno\s+tasks?\b[^.\n|]{0,100}\b(?:require|requires|needs?|need|must)\b"
    r"[^.\n|]{0,60}\b(?:review|reviewer|approval|approver)\b"
    r"|\b(?:independent|external|second|separate)\W+(?:review|reviewer|approval)\b"
    r"[^.\n|]{0,40}\b(?:is|are|was|were)?\s*"
    r"(?:not\s+(?:required|mandatory|needed|a\s+condition)|never\s+required)\b"
    r"|\bnot\s+(?:described|called|labelled|labeled|claimed|considered)\s+"
    r"(?:as\s+)?independent\W+review\b"
    r"|\b(?:không\s+phải|không\s+bắt\s+buộc|không\s+cần)\s+(?:là\s+)?(?:review|reviewer)\s+độc\s+lập\b"
    r"|\b(?:review|reviewer)\W+độc\s+lập\b[^.\n|]{0,40}"
    r"\b(?:không\s+(?:bắt\s+buộc|cần|yêu\s+cầu)|không\s+phải)\b",
    re.IGNORECASE,
)


def governing_files():
    """Enumerate nested policy/instruction/config sources, not only top-level markdown."""
    found = set()
    for name in ROOT_FILES:
        path = ROOT / name
        if path.is_file():
            found.add(path)
    for pattern in ROOT_GLOBS:
        found.update(path for path in ROOT.glob(pattern) if path.is_file())
    for directory in GOVERNING_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith("docs/evidence/"):
                continue
            if RECORD.match(path.name) or relative in HISTORICAL_EVALUATION_RECORDS:
                continue
            found.add(path)
    return sorted(found)


def mandates(text):
    """Return (line number, excerpt) for every line imposing independent review."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        # Evaluate each clause separately. A negative statement earlier in the same line
        # must not hide a later contradictory positive gate after "but", ";" or a sentence end.
        clauses = re.split(r"(?<=[.!?;])\s+|\s*;\s*|\b(?:but|however|nevertheless|yet)\b",
                           line, flags=re.IGNORECASE)
        for clause in clauses:
            if EXPLICITLY_NOT_REQUIRED.search(clause):
                continue
            for match in MANDATE.finditer(clause):
                found.append((number, clause[max(0, match.start() - 40):match.end() + 20].strip()))
    return found


class MandateScannerTests(unittest.TestCase):
    """Recognise historic blockers and do not misclassify explicit exemptions."""

    def test_recognises_the_wordings_that_held_work(self):
        cases = (
            "A different party must perform it",
            "Merge requires a formal independent review of the exact head",
            "stays Draft pending independent review",
            "a formal APPROVED review by a login other than OAI-GIANG",
            "không merge khi chưa có review độc lập",
            "independent review still required",
            "two-person rule before deploy",
            "Do not merge until an independent review is complete",
            "Do not deploy without a separate technical reviewer",
            "A task cannot close without an independent reviewer",
            "The gate waits for another reviewer before release",
            "No independent review is required, but do not merge until an independent reviewer approves",
            "No independent approval is required; however, release waits for a different reviewer",
            "Independent review is not required. Do not deploy without a separate security reviewer",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(mandates(text), text)

    def test_ignores_explicitly_non_mandatory_review_language(self):
        cases = (
            "MAEP-021 MUST: internal critique is not described as independent review.",
            "Internal checks only; no independent review is claimed.",
            "No independent review is required.",
            "Independent review is not required for any task.",
            "No task requires a second reviewer.",
            "No task needs an independent reviewer to close.",
            "phê bình nội bộ, KHÔNG phải review độc lập",
            "review độc lập không bắt buộc",
            "Require CLOSED_VERIFIED and independently read the file back.",
            "the adapter enforces scope independently",
            "clean independent holdout set",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(mandates(text), [], text)


class NoMandatoryIndependentReviewTests(unittest.TestCase):
    def test_decision_record_sets_the_rule(self):
        text = DECISION.read_text(encoding="utf-8")
        self.assertIn("INDEPENDENT_REVIEW_REQUIRED = false", text)
        self.assertIn("OD-IR-20261109", text)

    def test_no_governing_document_requires_an_independent_review(self):
        files = governing_files()
        self.assertIn(ROOT / "CLAUDE.md", files)
        self.assertIn(ROOT / "maep" / "spec" / "MAEP_CONSTITUTION_V1.md", files)
        offenders = [
            f"{p.relative_to(ROOT)}:{n}: {excerpt}"
            for p in files
            for n, excerpt in mandates(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "independent review is not required (OD-IR-20261109)")

    def test_acceptance_checklist_ac14_is_not_applicable(self):
        rows = [
            line for line in CHECKLIST.read_text(encoding="utf-8").splitlines()
            if line.startswith("| AC-14 |")
        ]
        self.assertEqual(len(rows), 1)
        cells = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
        self.assertTrue(cells[2].startswith("NOT_APPLICABLE"), cells[2])
        self.assertIn("OD-IR-20261109", rows[0])

    def test_claude_md_states_the_decision_and_supersession(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("OD-IR-20261109", text)
        self.assertIn("INDEPENDENT_REVIEW_REQUIRED = false", text)
        self.assertIn("older task prompt", text)


class RetainedControlsTests(unittest.TestCase):
    """What OD-IR-20261109 deliberately kept."""

    def test_maep021_still_refuses_a_false_independent_label(self):
        with self.assertRaises(MAEPError):
            validate_review_label("INDEPENDENT", independent_evidence=False)
        self.assertTrue(validate_review_label("INTERNAL_CRITIQUE"))

    def test_maep017_owner_authority_over_policy_is_unchanged(self):
        with self.assertRaises(MAEPError):
            validate_policy_change("1.0", "1.1", authorized=True, self_approval=True)
        with self.assertRaises(MAEPError):
            validate_policy_change("1.0", "1.1", authorized=False)
        self.assertTrue(validate_policy_change("1.0", "1.1", authorized=True))


if __name__ == "__main__":
    unittest.main()
