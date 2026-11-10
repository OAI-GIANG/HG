# HG Memory Continuity V2 — Internal Adversarial Review R2

Date: 2026-11-01 (Asia/Bangkok)
Candidate: feature/memory-continuity-v2
Base: main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5
Review type: internal source-level adversarial review by STT; NOT an independent third-party review.

## Findings detected and remediated

### R2-IAR-001 — global finding cap excluded staleness candidates
- Severity: HIGH (resource contract violation; no data mutation).
- Location: hg/memory/curation.py — analyze_memories().
- Scenario: a synthetic request with max_findings=3 and 12 independently expired records emitted 12 staleness findings but reported truncated=false. This contradicted the global max-findings contract and made the response larger than declared.
- Fix: apply a global cap across all five finding categories using deterministic round-robin trimming. Emit findings_emitted; set truncated=true whenever any class is cut.
- Regression: test_max_findings_caps_staleness_candidates_and_reports_truncation; test_max_findings_is_global_across_staleness_and_duplicate_classes.
- Verification: 10,000-record stress fixture emits exactly 500 total findings, evaluates at most 20,000 comparisons and sets truncated=true.

### R2-IAR-002 — a new ASK receipt could be reported as saving an old note
- Severity: HIGH (provenance correctness).
- Location: hg/assistant/notes.py — Notebook.add(); hg/assistant/ask_archive.py — save_model_derived_content().
- Scenario: a new ASK receipt with same subject/content as an existing ACTIVE note could receive the old note through generic same-content deduplication. The saved record still carried the old ask_receipt_id/source_ref, so the caller could mistakenly believe the new receipt had been bound.
- Fix: when an explicit new source_ref is supplied and same-subject content already exists under a different source_ref, raise NoteConflict rather than returning the old record. Retries of the same source_ref now require exact content equality rather than whitespace/case equivalence.
- Regression: test_new_ask_receipt_cannot_claim_existing_note_with_old_provenance; test_source_ref_retry_requires_exact_content_not_case_or_whitespace_equivalence.
- Verification: targeted ASK archive tests passed; expanded focused suite later passed 157/157.

### R2-IAR-003 — transitive interval grouping could conflate non-overlapping records
- Severity: HIGH (temporal curation correctness).
- Location: hg/memory/curation.py — exact duplicate detection.
- Scenario: intervals A=[Jan,Mar), B=[Feb,May), C=[Apr,Jun) were put in one connected component because A overlaps B and B overlaps C, despite A and C being disjoint. The resulting group could imply all members describe one overlapping validity period.
- Fix: remove transitive component grouping; emit exact-duplicate review pairs only when that pair's valid-time intervals actually overlap. Keep original records and provenance.
- Regression: test_exact_duplicate_candidates_do_not_chain_disjoint_valid_intervals.
- Verification: 64-case synthetic corpus, 64 unique pair fingerprints, precision/recall 1.00 in each fixture class; full suite 776/0/3 skipped.

### R2-IAR-004 — preview race and request/ledger content limit mismatch
- Severity: MEDIUM (stale preview / preventable user-facing error).
- Locations: hg/http_api.py — _chat_memory_save(); hg/ui/app.js — attachExplicitMemorySave().
- Scenario: API accepted up to 5,000 text chars while Notebook clean_text accepts 4,000; UI could also accept a preview response after the user changed the text while the async request was outstanding.
- Fix: align API/UI at 4,000 chars; re-check exact input snapshot when preview returns; disable subject/content/preview controls while save is in flight and re-enable only on failure.
- Regression: HTTP route rejects >4,000 before dispatch; UI source contract test checks limit and stale-input/save-in-flight guards.
- Verification: HTTP/UI focused suite passed; final combined focused suite 157/157.

## Final R2 evidence
- Focused regression: 157 tests, 0 failures, exit 0 (22.608 s).
- Full repository discovery: 776 tests, 0 failures, 3 skipped, exit 0 (81.815 s).
- 3 skips: environment-dependent SQLite no-follow tests (2 require hardlinks; 1 requires root ownership change).
- Python AST: 18/18; node --check; git diff --check all PASS.
- Synthetic 64-case Vietnamese corpus: 64 unique fingerprints, no errors; all five classes precision/recall 1.00. Fixture metrics only, not production semantics.
- 800-record synthetic benchmark: peak RSS 18.7–19.9 MiB; all profiles explicitly capped at 500 findings.
- 10,000-record resource test: exactly 500 findings, max 20,000 comparisons, truncated=true.

## Scope and caveats
This is an internal adversarial pass, not a separate model/vendor/human audit. It does not replace independent read-only review (Claude or another reviewer). No production private ledger was accessed. No code was merged/deployed. No retention, secure erasure, sensitive-data policy or cross-principal ACL decisions were made for the owner.
