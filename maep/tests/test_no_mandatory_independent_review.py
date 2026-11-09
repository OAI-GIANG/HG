"""OD-IR-20261109: no HG task, gate or lifecycle stage requires an independent reviewer.

Owner decision `docs/governance/OWNER_DECISION_OD-IR-20261109.md` sets
`INDEPENDENT_REVIEW_REQUIRED = false` for every task, gate and lifecycle stage. These tests keep
that decision from coming back under another name in the governing text, and keep the parts
that were deliberately not removed:

- MAEP-021 is a labeling rule (self-review must not be *called* independent). It never required
  an independent review, so it stays, and `validate_review_label` still refuses a false label.
- MAEP-017 (owner authority over policy) stays: owner approval is not independent review.

The scan reads the governing documents as text. Dated records that preserve history verbatim
(the 2026-11-06 ledger snapshot and the dated ledger reconciliations) and the decision record
itself (which lists what was removed) are excluded on purpose; they record, they do not govern.
"""
import re
import unittest
from pathlib import Path

from maep.core import MAEPError, validate_policy_change, validate_review_label

ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "docs" / "governance" / "OWNER_DECISION_OD-IR-20261109.md"
CHECKLIST = ROOT / "maep" / "spec" / "ACCEPTANCE_CHECKLIST_V1.md"

GOVERNING = ("CLAUDE.md", "README.md", "maep/README.md", "maep/spec/*.md", "docs/*.md",
             "docs/governance/*.md", "docs/architecture/*.md", "docs/architecture/adr/*.md",
             ".github/workflows/*.yml", ".claude/settings.json", "deploy/termux/README.md")

# Records kept verbatim as provenance; superseded by OD-IR-20261109 and ledger reconciliation C.
RECORD = re.compile(r"^(OWNER_DECISION_OD-IR-\d{8}\.md|HG_MASTER_COMPLETION_LEDGER_V1(_RECONCILIATION_\d{8}[A-Z]?)?\.md)$")

_REVIEW = r"(?:review|reviewer|reviewers|approval|approver|party)"
_KIND = r"(?:independent|external|second|separate|another|different)"
_QUAL = r"(?:human|security|technical|formal|github)"
MANDATE = re.compile(
    r"\b(?:must|shall|requires?|required|requiring|needs?|pending|waiting|wait\s+for|until|chờ|bắt\s+buộc|phải|cần)\b"
    rf"[^.\n|]{{0,60}}?\b{_KIND}\W+(?:{_QUAL}\W+)?{_REVIEW}\b"
    rf"|\b{_KIND}\W+(?:{_QUAL}\W+)?{_REVIEW}\W+(?:must|is\s+required|are\s+required|still\s+required|required|is\s+mandatory|bắt\s+buộc)\b"
    r"|\bformal\W+independent\W+review\b"
    r"|\b(?:review|reviewer)\W+độc\s+lập\b"
    r"|\b(?:login|reviewer|account)\s+other\s+than\b"
    r"|\btwo[- ]person\b|\bfour[- ]eyes\b",
    re.IGNORECASE)
# A negation inside the match or among the four words just before it ("not described as
# independent review", "KHÔNG phải review độc lập") is not a mandate.
# "không merge khi chưa có review độc lập" is: its negation is five words away and governs "merge".
NEGATION = re.compile(r"\b(?:not|no|never|without|nor|không|chẳng)\b", re.IGNORECASE)


def _negated(line, match):
    before = " ".join(line[:match.start()].split()[-4:])
    return bool(NEGATION.search(match.group(0)) or NEGATION.search(before))


def governing_files():
    seen = []
    for pattern in GOVERNING:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and not RECORD.match(path.name) and path not in seen:
                seen.append(path)
    return seen


def mandates(text):
    """(line number, excerpt) for every line that imposes an independent review."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in MANDATE.finditer(line):
            if _negated(line, match):
                continue
            found.append((number, line[max(0, match.start() - 30):match.end() + 10].strip()))
    return found


class MandateScannerTests(unittest.TestCase):
    """The scanner must recognise the wordings that held HG work, and ignore labeling rules."""

    def test_recognises_the_wordings_that_held_work(self):
        for text in ("A different party must perform it",
                     "Merge requires a formal independent review of the exact head",
                     "stays Draft pending independent review",
                     "a formal APPROVED review by a login other than OAI-GIANG",
                     "không merge khi chưa có review độc lập",
                     "independent review still required",
                     "two-person rule before deploy"):
            self.assertTrue(mandates(text), text)

    def test_ignores_labeling_and_technical_independence(self):
        for text in ("MAEP-021 MUST: internal critique is not described as independent review.",
                     "Internal checks only; no independent review is claimed.",
                     "phê bình nội bộ, KHÔNG phải review độc lập",
                     "Require CLOSED_VERIFIED and independently read the file back.",
                     "the adapter enforces scope independently",
                     "clean independent holdout set"):
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
        offenders = [f"{p.relative_to(ROOT)}:{n}: {excerpt}"
                     for p in files for n, excerpt in mandates(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [], "independent review is not required (OD-IR-20261109)")

    def test_acceptance_checklist_ac14_is_not_applicable(self):
        rows = [line for line in CHECKLIST.read_text(encoding="utf-8").splitlines()
                if line.startswith("| AC-14 |")]
        self.assertEqual(len(rows), 1)
        cells = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
        self.assertTrue(cells[2].startswith("NOT_APPLICABLE"), cells[2])
        self.assertIn("OD-IR-20261109", rows[0])

    def test_claude_md_states_the_decision(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("OD-IR-20261109", text)
        self.assertIn("INDEPENDENT_REVIEW_REQUIRED = false", text)


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
