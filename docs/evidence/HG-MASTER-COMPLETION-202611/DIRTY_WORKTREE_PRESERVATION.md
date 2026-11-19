# Dirty worktree and phone-only work preservation — 2026-11-19

Policy: nothing was reset, cleaned, moved, stashed, committed or deleted. Every dirty or unique item below is **PRESERVED / UNKNOWN** until it is classified with its owner.

- **43 git worktrees** in total (list in `WORKTREE_INVENTORY.csv`):
  - 24 have uncommitted entries, 1 to 30 each;
  - 19 are clean.
- **`~/HG`** (owner checkout):
  - branch `stt/hg-h1.3.1-idempotency-progress` @ `2a80f4f`;
  - modified: `hg/assistant/cli.py` (6 lines), `hg/assistant/config.py` (13), `hg/brain/providers.py` (+84);
  - untracked: 5 files under `docs/governance/` (incl. `HG-PR77-PROC-EXIT-CHURN-CANDIDATE.patch`).

  This matches mission §4.3, plus the untracked file names now listed.
- **Unpushed commits** (`git log --branches --not --remotes`):
  - `ff77455` and `1709af6`, both "feat(brain): wire compatible provider into ModelPlanner";
  - both are kept OFFLINE by owner decision D1 (2026-11-13);
  - bundles exist at `~/HG-OFFLINE-BACKUP-20261113/HG-CONVERGENCE-INTEGRATION-20261110{,B}.bundle`.
- **Other recovery archives on the phone:**
  - `~/HG-CLEANUP-ARCHIVE-20261107/*.bundle`;
  - `~/HG-RECOVERY-SNAPSHOTS/HG-MASTER-GO-LIVE-V3-20261111T021511+0700/execution-branch-cp01.bundle`.
- **Next (Phase 1):**
  - For each dirty worktree, diff its changes against `main` and against the PR that superseded them. Record SUPERSEDED / UNIQUE / UNKNOWN.
  - Only after that, and with a bundle plus its hash, may any worktree be retired.
