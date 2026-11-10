# HG Memory Continuity V2 — R3 implementation and verification record

**Date:** 2026-11-01 (Asia/Bangkok)
**Candidate:** `feature/memory-continuity-v2`
**Canonical base:** `main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`
**Runtime:** Android / Termux ARM64, Python 3.14.8, Node.js 26.12.1
**Status:** `ENGINEERING_COMPLETE / READY_FOR_INTEGRATION_REVIEW`

## 1. Scope and authority boundary

R3 was implemented only in `~/HG-memory-continuity`. The primary `~/HG` checkout was not modified. Real private `HG_HOME` ledger content was not read or written. No dependency installation, commit, push, merge, integration or deployment occurred.

The controlling `R3 TASK — REQUIRED FIXES` and owner-confirmed `R3 TASK ADDENDUM — OWNER DECISION & MISSING ACCEPTANCE GATES` were supplied by the owner in this conversation. The previous package draft incorrectly described those inputs as unavailable; that statement is withdrawn. The exact D-K4 choice used here is: **REQUIRE A NEW ASK RECEIPT AND FRESH OWNER CONFIRMATION AFTER RETRACTION OR SUPERSESSION**. The K1–K8 crosswalk is recorded in `evaluation/r3/R3_ACCEPTANCE_CROSSWALK_K1-K8.md`.

## 2. R3 findings, fixes and tests

### R3-F01 — Episodic cross-subject false conflicts
- `hg/memory/curation.py` limits semantic conflict checks to FACT, DECISION, NOTE and PREFERENCE. EPISODIC/EVENT cross-subject results require exact normalized content and exact structured-value match.
- `BrainEpisodeCurationTests` exercises five terminal Brain episodes through `MemoryStore.record_task_outcome`; different task episodes yield no conflict and exact matches remain visible.

### R3-F02 — Incomplete durable writer serialization
- `MemoryStore.remember`, `promote`, `retract` and `record_task_outcome` use an instance RLock plus the ledger-wide `fcntl.flock` sidecar and reload-before-write.
- Notebook add/forget/trust uses the same sidecar; Notebook operations also use the HOME lock. `trusted_ids` reads under the sidecar lock. `hg repair` takes the same per-ledger sidecar lock while inspecting or repairing.
- Tests cover four-process task-outcome concurrency, a deterministic unlocked negative control, generic concurrent remember/retract, ambiguous append outcomes and repair behavior.

### R3-F03 — MODEL_DERIVED provenance was forgeable
- Preview accepts only an exact excerpt of the immutable ANSWERED ASK output. The source reference binds receipt ID, answer digest, excerpt offsets, content digest and owner-confirmation digest.
- MemoryStore independently reopens and verifies the ASK receipt and exact excerpt for new writes. Caller-authored/rephrased text and direct Notebook forgery are rejected. Legacy records remain replay-compatible; new writes require proof fields.

### R3-F04 — ASK receipt replay could change save identity
- Notebook reloads the durable ledger while holding the sidecar lock and binds a receipt to subject, canonical content and provenance identity.
- Changed/rebound receipt use is rejected. Exact retry after retract/supersede returns `NoteInactive` and HTTP 409. A fresh ASK receipt and fresh owner confirmation are required for a new save. CLI reports the owner action distinctly from ledger corruption.

### R3-F05 — UI async preview and save races
- `hg/ui/memory-save-flow.js` is a shared behavioral controller used by `app.js` and Node tests. It validates generation and subject/content snapshots, verifies server preview identity, locks editable inputs during save, prevents duplicate submit and unlocks after failure.
- UI and server enforce 4,000 content characters and an 80-character subject.

### R3-F06 — New controller asset was not allowlisted
- HTTP static asset allowlist includes `/ui/memory-save-flow.js`; tests cover delivery, MIME/body and route behavior.

### R3-F07 — Inactive ASK receipt CLI message was misleading
- CLI catches `NoteInactive` explicitly and tells the owner that a new ASK receipt and confirmation are required.

### R3-F08 — Repair could race direct memory writers
- `hg repair` takes the same per-ledger sidecar lock as MemoryStore writers while inspecting/repairing the ledger.

## 3. Verification

### 3.1 Full suite

Command: `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v`

- **787 tests, 0 failures, 3 skipped, exit code 0**.
- Runtime: 85.931 seconds.
- Environment: Android/Termux ARM64, Python 3.14.8, Node.js 26.12.1.
- Skips: two tests require hard-link support; one requires root to `chown` another owner.
- Full log: `evaluation/r3/FULL_SUITE_FINAL_PREPACKAGE.log`.
- A preliminary full-suite run exposed a legacy E2E fixture submitting rewritten owner prose as `MODEL_DERIVED`. The server correctly rejected it; the fixture was corrected to use the exact ASK answer excerpt. The specific E2E test and final full suite then passed. Diagnostic log: `evaluation/r3/PRELIM_FULL_SUITE.log`.

### 3.2 Focused and behavioral tests

- Focused Python group: **132 tests, 0 failures, exit code 0**.
- Node save-flow behavior: **7 tests, 0 failures**.
- UI behavior includes delayed-preview invalidation on content/subject change, stale confirmation rejection, save lock/unlock, double-submit prevention, 4,000/4,001 boundary and mismatched server preview.

### 3.3 Static checks

- Python AST parse: **20/20 changed/new Python files PASS**.
- `node --check hg/ui/app.js`: PASS.
- `node --check hg/ui/memory-save-flow.js`: PASS.
- `node --test hg/tests/test_memory_save_flow.js`: 7/7 PASS.
- `git diff --check`: PASS.
- Log: `evaluation/r3/STATIC_CHECKS_R3.log`.

### 3.4 Synthetic accuracy and resource checks

- 64 labelled Vietnamese synthetic cases across five classes; precision/recall 1.00 per class; no fixture errors. This is synthetic fixture performance, not a claim of real-world semantic accuracy.
- Same-subject, distinct-subject and Brain-like 800-record Termux profiles are captured as JSON in `evaluation/r3/`.
- Brain-like 10,000-record stress: exactly 20,000 comparisons, zero false conflicts, zero near duplicates, zero cross-subject suggestions, `truncated=true`, 29.8 MiB peak RSS, 0.452 s analysis, exit 0.
- Stress log: `evaluation/r3/STRESS_10000_BRAIN_R3.log`.

## 4. K1–K8 disposition

The owner-supplied requirements have been mapped individually in `evaluation/r3/R3_ACCEPTANCE_CROSSWALK_K1-K8.md`. K1, K2, K3, K5 and K7 pass. K4 passes the selected D-K4 behavior with an identity qualification: the stored principal is the `OWNER` role plus a confirmation digest, not a unique authenticated account ID. K6 passes for all append-capable paths to the shared memory ledger; separate ASK/model/action/evidence journals are inventoried with their separate lock/store boundaries and are not silently covered by the memory lock. K8 passes with command, baseline, timestamp, environment, output and exit data; package manifest binds the final patch and evidence hashes.

## 5. Candidate boundary and execution attribution

- Candidate branch remains `feature/memory-continuity-v2`, based on `2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`.
- Candidate source changes remain unstaged in the repository Git index. Patch generation uses a temporary Git index outside the worktree.
- Primary `~/HG` was not modified; real private `HG_HOME` ledger content was not read or written.
- No commit, push, merge, integration, deployment or production operation occurred.
- DeepSeek CLI was not installed in Termux. The code/test work in this candidate was performed directly by STT via Remote Desktop Commander; this record does not attribute execution to DeepSeek.

## 6. Handoff decision

**`ENGINEERING_COMPLETE / READY_FOR_INTEGRATION_REVIEW`** — candidate patch and evidence package are prepared for independent review. This is not approval to merge, deploy or write into the primary checkout. Reviewers should pay particular attention to the K4 principal-identity qualification and K6 memory-ledger scope boundary documented in the crosswalk.
