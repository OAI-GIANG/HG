# S03 Baseline & Preflight Evidence

Date: 2026-11-03 (Asia/Bangkok)
Scope: READ-ONLY inventory and baseline validation before S03 implementation.

## 1. Repository identity

- Repository: OAI-GIANG/HG
- Canonical remote: origin
- Current default branch: main
- Fetched origin/main: e99c83e8d53cb9fd0b1ab22514a942b7d168db8b
- Candidate branch: stt/s03-independent-verification-20261103
- Candidate worktree: ~/HG-S03
- Candidate HEAD at creation: e99c83e8d53cb9fd0b1ab22514a942b7d168db8b
- Candidate worktree was clean when created.

GitHub compare showed 11 commits between the phone's old origin/main baseline (2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5) and fetched current main. The latest merge was G1 PR #79 (writer admission, cross-process ledger safety and read-only state-copy precheck). The candidate was created from fetched origin/main, not the stale local main ref.

## 2. Original worktree preservation

The original ~/HG worktree was on branch stt/hg-h1.3.1-idempotency-progress at HEAD 2a80f4f26fdb6202d581febfe2922468172e398c. It already contained three modified tracked files before the S03 candidate was created:

| File | SHA-256 observed before/after worktree creation |
|---|---|
| hg/assistant/cli.py | 39e389cbb63eaed1b80793fcc4db277a2efea028fd91675348a54960478572da |
| hg/assistant/config.py | 2eeaddcfbf7cbfe57421f32add501fc6b83d3725272ee83a587543b5eb580a76 |
| hg/brain/providers.py | 7f132b4c450a2ed75ca34355061556a281c135ca559937ad8ecbef2a20783560 |

No reset, checkout, stash, clean, deletion or overwrite was performed on that worktree. The three file hashes remained unchanged after fetching current main and creating the linked worktree. S03 implementation was confined to ~/HG-S03.

## 3. Existing architecture findings

The following existing source files were inspected:

- hg/verification/evidence.py
- hg/brain/orchestrator.py
- hg/runtime.py
- maep/core.py
- maep/ledger.py
- maep/task_store.py
- maep/schemas/evidence.schema.json
- maep/spec/MAEP_EVIDENCE_ACCEPTANCE_V1.md
- maep/spec/THREAT_MODEL_V1.md
- maep/spec/MAEP_CONSTITUTION_V1.md
- docs/architecture/DATA_FLOW_TRUST_BOUNDARY_V1.md
- docs/architecture/ARCHITECTURE_ACCEPTANCE_CHECKLIST_V1.md

Observed existing capabilities:

1. MAEP TaskStore is the task-state and evidence metadata owner.
2. Evidence records bind candidate_ref, source_ref, collector, method, result, time and limitations.
3. AcceptanceGate and closure validation require mandatory criteria and linked evidence.
4. Event and task ledgers are append-only through their APIs and fsynced. The docs explicitly do not claim tamper-proof storage against privileged same-UID writes.
5. G1 writer admission, read-only views and cross-process ledger locks are present on current main.
6. BrainOrchestrator verifiers were in-process callbacks and explicitly labelled as internal checks, not independent review.
7. MAEP-014 already specifies stopping after three meaningful failures; current execution retry tests verify three attempts then BLOCKED.
8. MAEP schema already permits scalar integrity_metadata; no new SQLite evidence database or second metadata owner is required.
9. Search of the fetched repository found no GTEW-1.0 specification or implementation reference.

## 4. Runtime environment observed

- Device: Android 16
- Architecture: aarch64 / ARM64
- Python: 3.14.8
- SQLite library: 3.54.1
- CPU count reported: 8

No new package was installed for S03. The S03 worker and artifact handling use Python standard library only.

## 5. Baseline test evidence on the candidate base

Commands were run from ~/HG-S03 with bytecode writes disabled and output redirected to ~/HG-S03-OUTPUT, outside the repository:

| Baseline command | Result |
|---|---|
| python -B -m unittest discover -s maep/tests -v | 304 tests, OK, 3 skipped |
| python -B -m unittest discover -s hg/tests -t . -v | 470 tests, OK |
| python -B -m hg selfcheck | PASS; all three runtime scenarios matched |
| python -B -m hg bench | PASS; 10/10 regression cases, unauthorized_effects=0, false_closures=0, recovery=1.0 |

Baseline logs:
- ~/HG-S03-OUTPUT/maep-baseline.log
- ~/HG-S03-OUTPUT/hg-baseline.log
- ~/HG-S03-OUTPUT/selfcheck-baseline.log
- ~/HG-S03-OUTPUT/bench-baseline.log

The HG test suite took 93.373 seconds; the total sequence completed in about 100 seconds. The delay was test runtime, not an indefinite process hang.

## 6. P0 conclusion

P0 is accepted for the scoped repository and test baseline. The original dirty worktree was preserved, the current main commit was fetched, the candidate was created from that commit, and baseline test evidence was captured.

Limitations: Git pre/post checks do not observe every filesystem path or every same-UID process. P0 does not claim kernel-enforced read-only isolation or protection against a hostile process with the same UID.
