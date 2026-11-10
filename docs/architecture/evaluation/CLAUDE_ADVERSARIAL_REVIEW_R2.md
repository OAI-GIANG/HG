# CLAUDE — HG MEMORY CONTINUITY V2 — R2 INDEPENDENT ADVERSARIAL REVIEW

## Review mandate

Perform an independent, skeptical, READ-ONLY adversarial review of the exact R2 candidate patch against the supplied canonical baseline. Do not edit source, run formatters, change configuration, install packages, create commits, push, merge, deploy, or inspect any real/private HG_HOME ledger. Do not treat the internal STT review as independent approval.

## Source coordinates

- Repository: OAI-GIANG/HG
- Canonical baseline: main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5
- Candidate branch: feature/memory-continuity-v2
- Patch: ../patch/HG-MEMORY-CONTINUITY-V2-R2.patch
- Canonical source archive: ../baseline/HG-CANONICAL-BASELINE-2f00a62.tar.gz
- Implementation report: ../docs/HG_MEMORY_CONTINUITY_V2_IMPLEMENTATION.md
- R2 evidence folder: ../evidence/
- Patch SHA-256: supplied in README.md and SHA256SUMS.txt

Use only a disposable checkout based exactly on the baseline if a worktree is needed. Never inspect/modify the owner's primary ~/HG checkout.

## Binding owner decisions

### D-8.1 — inactive source references
- A source_ref linked to RETRACTED or SUPERSEDED note is not a successful save/retry.
- Return stable memory_save_inactive HTTP 409 for same-source inactive retries.
- Do not reactivate, overwrite, or report success.
- A new save after retraction/supersession requires a new ASK receipt and fresh digest confirmation.
- Retries of a single source operation must not create duplicate records.

### D-8.2 — MODEL_DERIVED provenance vs authorization
- Explicit owner-confirmed saving of model-originated content, including verbatim model output, is allowed.
- Keep provenance and authority separate:
  - content_origin=MODEL_DERIVED
  - authorized_by=OWNER
  - owner_confirmed=true
  - ask_receipt_id=<ASK_RECEIPT_ID>
- Preserve receipt identity, answer digest and confirmation digest in source provenance.
- owner_confirmed is not verified_truth.
- Never label model content USER_AUTHORED merely because the owner approved storage.
- A distinct new ASK receipt must not silently receive an old note whose source_ref points to a prior receipt.

### D-8.3 — cross-subject curation
- Cross-subject review is suggestion-only.
- Preserve original subjects, IDs and provenance.
- Compare only context-compatible records with relevant temporal overlap.
- Preserve numeric/time/unit/polarity distinctions.
- No automatic merge/delete/supersede/canonical truth choice.

### DATA-003 and CONC-001
- After append error, reload durable ledger before retry classification.
- Use UNKNOWN_IF_WRITTEN when durability cannot be proven.
- Multiprocess atomic check-and-append must not depend on threading.Lock alone.
- Verify process restart, duplicate source references, contiguous sequence and no replay of actions/tools.

## R2 fixes requiring independent challenge

The internal pass reported four fixes. Verify them from source and tests; do not assume they are correct:
1. Global max_findings now covers every output category, including staleness. It reports findings_emitted and truncated correctly; the implementation uses deterministic round-robin trimming.
2. New ASK receipt + same subject/content cannot receive an old note carrying a different source_ref. Same source_ref retry requires exact content equality.
3. Exact duplicate candidates are pairwise and must satisfy actual valid-time overlap; there must be no transitive interval grouping that conflates disjoint endpoints.
4. Chat save UI/API limits are aligned to Notebook's 4,000-character limit. Async preview must not be accepted after input changes, and save-in-flight UI state must not permit stale edits/double submissions.

## Required adversarial review

### A. Authorization, HTTP boundary and provenance
- Trace bearer token, Host/loopback, request-body limits, strict JSON, VERIFIED release gate and all save routes.
- Try forged/missing/duplicate/ambiguous ASK receipt IDs; malformed digest; digest prefix variations; uppercase hex; Unicode normalization; control/bidi characters; empty and over-limit input.
- Examine receipt uniqueness, month-boundary receipt lookup, append-only assumptions, symlink/path safety, lock boundaries and TOCTOU.
- Verify that MODEL_DERIVED cannot be relabelled USER_AUTHORED and that a new receipt cannot falsely claim old memory provenance.
- Inspect HTTP 409/400/503 distinctions and confirm no error turns into success.
- Test duplicate submissions, preview invalidation and request timeouts where a write may have committed.

### B. Notebook semantics and idempotency
- Challenge source_ref uniqueness, same-source retries, changed content, retracted/superseded notes, same-content dedup and concurrent saves.
- Confirm a new ASK receipt with same text is either truly stored with its own provenance or rejected; it must never return a different provenance record as if newly saved.
- Assess source_ref length and receipt-ID validation.

### C. Curation correctness
- Challenge NFC, casefolding, tokenization, negation, short Vietnamese words, diacritics, synonym/paraphrase, polarity, numeric tokens and unit/time changes.
- Verify [Jan,Mar), [Feb,May), [Apr,Jun) yields only overlapping pairs, never a single transitive group claiming Jan–Jun overlap.
- Verify valid_to/expires_at and valid_from boundaries, unknown timezone handling, equal boundaries and missing endpoints.
- Test max_findings across exact, near, conflict, stale and cross-subject categories; total output must never exceed configured cap and truncated must be true when output is cut.
- Inspect total worst-case work at 10,000 records and 20,000 comparisons.

### D. Brain / TaskStore consistency
- Check deterministic task-version source refs, terminal-state enforcement, fsync ambiguity, reload, process-lock behavior and reconstruction.
- Verify reconciliation changes only MemoryStore episodes; no TaskStore action, tool or side effect is replayed.
- Verify durable ACTION_COMPLETED count is unchanged by reconciliation.

### E. Mobile resource and operational design
- Evaluate memory/RSS, output size and runtime on Android ARM64. Treat measurements as device-specific, not SLA.
- Challenge hidden quadratic loops, memory materialization and result truncation.
- Ensure no production/home ledger scans occur through curation commands.

### F. Evidence and patch integrity
- Independently relate each claimed test and report to the exact R2 patch.
- The full suite reported 776 tests, 0 failures, 3 environment-dependent skips.
- Focused suite reported 157 tests, 0 failures.
- Synthetic corpus: 64 distinct cases / 64 pair fingerprints; all five fixture classes had precision/recall 1.00. This is not real-world semantic accuracy.
- 800-record peaks: 18.7–19.9 MiB. 10,000-record stress: 500 total findings, 20,000 comparisons, truncated=true.
- Static checks: Python AST 18/18, node --check, git diff --check.
- Patch apply-check must be reproducible against the exact baseline.

## Required output structure

1. Executive verdict: ACCEPT / ACCEPT WITH CONDITIONS / REJECT.
2. Findings ordered BLOCKER, HIGH, MEDIUM, LOW. For each:
   - exact file/function/line;
   - concrete failure or exploit;
   - severity/impact;
   - reproducible test/proof;
   - minimal remediation and acceptance criterion.
3. Invariants demonstrably preserved, with evidence.
4. Missing adversarial coverage and test matrix.
5. Unresolved owner-policy questions; do not decide retention/erasure/sensitive-data/ACL policy.
6. Recommendation: keep isolated / revise / reject.
7. Explicit statement whether any BLOCKER/HIGH finding prevents integration review closure.

No generic praise. No production-readiness claims unsupported by evidence. Clearly distinguish confirmed defects from speculative risks.
