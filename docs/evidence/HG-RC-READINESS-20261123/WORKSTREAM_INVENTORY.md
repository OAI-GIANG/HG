# Unfinished workstreams on the owner's phone — inventory and plan (2026-11-23)

Owner decision 2026-11-23: preserve every dirty worktree. Nothing was deleted, reset, cleaned, moved or
overwritten. This inventory only read the evidence files.

- Source: `~/hg-evidence/P1-REFRESH-20261122/P1_DIRTY_CLASSIFICATION.json`, classified against main `07b2bcd`.
- Inventory script: `~/hg-evidence/P5-READINESS-20261123/inventory.py`. Output: `WORKSTREAM_INVENTORY.json`
  in the same directory.
- Content backup: `~/hg-evidence/P0-BASELINE-20261122/P1_DIRTY_CONTENT_BACKUP.tar.gz`, sha256 `9c9aedec…`.

**Totals.**
- 24 worktree/branch groups, 429 uncommitted entries.
- By class: UNIQUE 304 (content not on main), DIVERGED 100 (file differs from main), SAME_AS_MAIN 25
  (already on main, byte-identical).
- Since that classification, main moved from `07b2bcd` to `4b1f311`, which changed `hg/assistant` files.
  The classes of those files may have shifted, so re-classify before porting anything.

**How to read "Completeness".** It cannot be measured without a content review. The indicator used here is
the class mix: a group that is mostly SAME_AS_MAIN is largely merged; a group that is mostly UNIQUE has not
been integrated.

## Workstreams

| # | Workstream | Worktrees (branch @ head) | Entries (D/U/S) | Main content | Status | Dependencies | Risk | Next step |
|---|---|---|---|---|---|---|---|---|
| A | Memory continuity V2 | `~/HG-memory-continuity` (`feature/memory-continuity-v2` @ `2f00a62`) | 101 (16/85/0) | design docs 31, build outputs `dist/r3*` 45, tests 9, assistant 4, UI 4, memory 2 | Not integrated; feature | assistant layer, `hg/memory` (3 files on main) | Conflicts with RC-3 and RC-14…17 in `hg/assistant`; `dist/` outputs must not be committed | Deferred until GO-LIVE is accepted. Then re-base the design on current main and port the code under an admission record. |
| B | GO-LIVE candidate and certification evidence | `~/HG-GO-LIVE-CANDIDATE` (`stt/hg-go-live-certification-20261111` @ `e465db2`); `~/HG-MASTER-GO-LIVE-V3-EXECUTION` (6); `~/HG-FORENSIC-CONSOLIDATION-20261110` (13); `~/HG-S03-STAGING/source` (3) | 94 (18/63/13) + 22 UNIQUE | evidence 56, `android/cim-broker` 21, tests 6, assistant 5, CI workflow 1; governance docs | Partly merged: `android/cim-broker` is on main (28 files) | GO-LIVE gates in the ledger | Stale evidence could be cited as current | Diff the 21 broker files and the workflow against main. Port only evidence a GO-LIVE gate cites, inside a fix PR. Treat the rest as historical. |
| C | CIM / IGYM | `~/HG-IGYM-CIM-V1` (15), `~/HG-IGYM-CIM-V1-MAIN` (27), `~/HG-CIM-POC-INTEGRATION-20261110` (14) | 56 (7/43/6) | `docs/cim` 7 and `experiments/cim_poc` 6 in each copy; broker 11 | Experimental; three overlapping copies; not on main | Android broker | Duplicates; no acceptance criteria | Deferred (stabilization mode). Later, with owner approval, keep one preserved copy as the reference. |
| D | h1.3.1 review and idempotency | `~/HG-h1.3.1-review` (detached `4c1aa9d`, 47); `~/HG` (`stt/hg-h1.3.1-idempotency-progress` @ `2a80f4f`, 8) | 55 (21/34/0) | architecture docs 20, tests 10, assistant 4, UI 4, memory 2 | Unknown merge state | runtime idempotency | Possibly superseded | Diff against main. If superseded, record that; otherwise make it a finding with an admission record. |
| E | UI stabilization | `~/.cache/hg-worktrees/hg-ui-stabilization-20261115` (11), `…-rebase-20261118` (5) | 16 (11/0/5) | UI, chat, HTTP API, tests | Largely merged (evidence `HG-UI-STABILIZATION-20261118` on main) | — | Low | Confirm the DIVERGED files are older versions, then mark the group superseded. |
| F | RCME foundation | `hg-rcme-foundation-v1` (5), `~/HG-RCME-INTEGRATION-20261110` (5) | 10 (2/8/0) | `hg/brain` 2, `__main__`, implementation doc, test | Not on main; new architecture | brain/orchestrator | Architecture change | Deferred (stabilization mode). |
| G | PR #77 pid-namespace | 3 worktrees, 3 entries each | 9 (0/9/0) | architecture doc, assistant, test | Paused by owner decision | — | — | Keep unchanged (owner decision). |
| H | Model adapters | `~/HG-llama-cpp-candidate` (5), `~/HG-MODEL-CALL-GATEWAY-V1` (3) | 8 (8/0/0) | assistant, brain, chat, tests | Not on main | a live model (BLOCKED_EXTERNAL) | Conflicts with the assistant layer | Deferred until a model decision. |
| I | Earlier stabilization batches | FD4-FW1 (11), batch1 task A (2) and B (6), ledger worktree (3), LA2 round 3 (36: evidence 30) | 58 (17/40/1) | tests, assistant, ledger, evidence | Probably superseded by later merges | — | Low | Diff against main to confirm superseded, then record that. |

## Plan (no step deletes anything)

1. Re-classify all 429 entries against main `4b1f311`. This is read-only, done with the same script.
2. Work through groups B, D, E and I: diff, then decide port / superseded / historical, one group at a time.
   Each decision gets a recovery point. Ports go in a fix PR with an admission record.
3. Groups A, C, F and H stay deferred until the owner accepts GO-LIVE (stabilization mode). G stays
   unchanged (owner decision).
4. Do not reclaim any space and do not consolidate worktrees without an explicit owner decision for that
   action.
