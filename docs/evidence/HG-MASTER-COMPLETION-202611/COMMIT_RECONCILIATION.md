# Commit reconciliation — first pass (2026-11-19)

**Scope:** the 17 remote branches that are not ancestors of `main` (`UNMERGED_IMPLEMENTATION_MAP.csv`), plus 2 phone-only commits. Method: GitHub compare from the merge base to each branch head, then a per-file blob comparison with `main` `13a56be`. Squash merges explain most "diverged" counts: a PR's branch commits never become ancestors of `main`.

| Branch / PR | Disposition (evidence) |
|---|---|
| `stt/maep-v1-20261022` (#2) | MERGED by squash; leftover pre-squash history |
| `probe/failing-ci-20261023` (#6) | CLOSED probe, intentionally unmerged |
| `stt/execution-host-audit-only-20261024` (#11) | Guard part on `main` (#191); execution-host deferred P4 (D3) |
| `stt/claude-setup-20261026` (#55) | CLOSED by the owner |
| `stt/policy-resource-templates-20261028` (#64) | DEFERRED_V2 |
| `feat/listener-attestation-hg-la-2-20261031` (#77) | HOLD (D2). 62 files absent on `main` = unique L5/attest work, preserved |
| `fix/pr77-l5-partial-scope-20261118` (#205) | Draft on top of #77. Fail-closed for PARTIAL scope. Real-kernel gate red = BLOCKED by design |
| `feat/ui-stabilization-main-20261118` (#204) | READY_TO_MERGE at `027b450` (Chromium 25/25, CI green); merge blocked by session permission |
| `ci/g3-root-owned-dir-oracle-20261118` (#206) | CI-only, green. Merge after #204 with a ledger line |
| `stt/hg-capability-convergence-v1-20261110` | G4 admission source `0feca8a`. Do not touch |
| `stt/hg-master-go-live-v3-execution-20261111` | 4 files absent on `main` (go-live v3 records). UNKNOWN: compare with ledger §53 |
| `stt/hg-memory-continuity-r3.1-port-20261111` | 47 absent / 18 differing files. UNKNOWN: memory work not on `main`; needs an owner scope decision (v1 vs v2) |
| `recovery/*` with ahead > 0 (5 branches) | Recovery points. Never delete (CLAUDE.md) |
| `ff77455`, `1709af6` (phone only) | OFFLINE by D1, bundled |

**Duplicates confirmed:**
- `hg-*` legacy branches (5) all point at `d71b771`, which is behind `main`.
- PR #77 has two refs: the remote feature branch is stale at `c096cbf`; the PR head is `73a45f0` (§64).

**Open (Phase 1):** a history-based patch-id comparison for the two UNKNOWN rows, before any integration.
