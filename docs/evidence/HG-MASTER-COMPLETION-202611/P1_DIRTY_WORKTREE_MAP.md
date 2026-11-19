# P1 — dirty worktree reconciliation map (read-only, 2026-11-20 00:04 +07)

Script: `~/hg-v1-evidence/p1-dirty-map-20261120.sh`. It compares against `main` = `47e076e` (`git fetch origin main`, the only write). Each dirty path in each worktree is classified by blob: the working-tree file's `git hash-object` is compared with `main:<path>`.

Full map on the device: `~/hg-v1-evidence/p1-dirty-map-20261120/dirty-map.csv`, 429 rows, sha256 `679f2b83…`. Summary sha256 `21535929…`.

**Totals:**
- 24 dirty worktrees, 429 entries.
- **304 UNIQUE_NOT_ON_MAIN**: the path does not exist on `main`.
- **101 DIFFERS_FROM_MAIN**: the path exists on `main` with different content.
- **24 SAME_AS_MAIN**: the content is already integrated.
- For 17 of the 24 worktrees, HEAD is an ancestor of `main`; for 7 it is not.

| Worktree (~/…) | UNIQUE | DIFFERS | SAME |
|---|---|---|---|
| HG (owner checkout) | 5 | 3 | 0 |
| HG-memory-continuity | 85 | 16 | 0 |
| HG-GO-LIVE-CANDIDATE | 63 | 18 | 13 |
| HG-h1.3.1-review | 29 | 18 | 0 |
| .cache/hg-worktrees/hg-la2-round3 | 36 | 0 | 0 |
| HG-IGYM-CIM-V1-MAIN | 15 | 6 | 6 |
| HG-IGYM-CIM-V1 | 14 | 1 | 0 |
| HG-CIM-POC-INTEGRATION-20261110 | 14 | 0 | 0 |
| HG-FORENSIC-CONSOLIDATION-20261110 | 13 | 0 | 0 |
| .cache/…/hg-fd4-fw1-v1-20261115 | 2 | 9 | 0 |
| .cache/…/hg-ui-stabilization-20261115 | 0 | 6 | 5 |
| HG-MASTER-GO-LIVE-V3-EXECUTION | 6 | 0 | 0 |
| .cache/…/hg-batch1-task-b-ec07 | 0 | 6 | 0 |
| .cache/…/hg-ui-stabilization-rebase-20261118 | 0 | 5 | 0 |
| HG-llama-cpp-candidate | 0 | 5 | 0 |
| .cache/…/hg-rcme-foundation-v1, HG-RCME-INTEGRATION-20261110 | 4 each | 1 each | 0 |
| .cache/…/hg-master-completion-ledger-v1, HG-MODEL-CALL-GATEWAY-V1 | 0 | 3 each | 0 |
| hg-pr77-pidns-blocked-candidate, hg-pr77-pidns-review-c096, HG-PR77-PIDNS-UNAVAILABLE-20261110, HG-S03-STAGING/source | 3 each | 0 | 0 |
| .cache/…/hg-batch1-task-a-v31 | 2 | 0 | 0 |

**Classification rules for the next pass, per row of the device CSV:**
- **SAME_AS_MAIN** → *integrated by another PR*. Safe to drop only after the worktree is bundled.
- **DIFFERS_FROM_MAIN** with HEAD an ancestor of `main` → *conflict / stale candidate*. Diff against `main` and the PR that last touched the path.
- **UNIQUE_NOT_ON_MAIN** → *unique, not yet eligible*. Most are evidence or log files (for example `hg-la2-round3`). Owner scope decision (v1 vs v2) for code paths, such as `HG-memory-continuity`.

Nothing was deleted, reset, stashed or checked out. All 43 worktrees remain PRESERVED.
