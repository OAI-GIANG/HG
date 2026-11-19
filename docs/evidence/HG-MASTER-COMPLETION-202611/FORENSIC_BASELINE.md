# HG Master Completion V2.0 — Phase 0 forensic baseline (PARTIAL)

Mission: *HG — Master Autonomous Completion, Real-World Operationalization & Reliability Mission V2.0* (owner, 2026-11-19 22:18 +07).
Session: cloud (Linux x86_64, Python 3.13.18), started 2026-11-19 22:18 +07.
Status: **PARTIAL**. The GitHub side is VERIFIED. The Termux side is **BLOCKED_DEVICE_OFFLINE**: the Desktop Commander device `localhost` (the owner's phone) was offline for the whole session, last seen 17 min before it started.

## 1. GitHub (read directly through the API, 2026-11-19 ~22:25 +07) — VERIFIED

| Item | Value |
|---|---|
| Repository | `OAI-GIANG/HG` (public), default branch `main` |
| `main` HEAD | `13a56be75a62a56f2123c755aea97a6d1c9cd79a` (#203). This equals the historical baseline from the mission's §4.3. |
| CI on `main` | Last 10 runs `success`, including `13a56be` (run 44198114065) |
| Ruleset | `main-maep` (25706034), active, target branch |
| Branches | 99. 80 are `recovery/*`. Status vs `main`: 81 behind, 15 diverged, 2 ahead. See `BRANCH_INVENTORY.csv`. |
| Pull requests | 205. 197 merged, 3 closed unmerged (#6 probe, #11, #55), 5 open (#77 HOLD, #64 DEFERRED_V2, #204/#205/#206 draft). See `PR_INVENTORY.csv`. |
| Issues | 1 open: #197, the G7 O4 admission record |
| Tags / releases | 0 / 0. The session proxy refuses tag pushes; releases are built on the device. |

`UNMERGED_IMPLEMENTATION_MAP.csv` covers the 17 branches that are not plain ancestors of `main`. For every file each branch changed since its merge base, it compares the blob with `main`. "absent_on_main" can also mean that `main` later moved or removed the path. The history-based per-commit check is Phase 1 work.

Dispositions already recorded in the ledger (§53–§65):
- #2: merged (squash).
- #6: probe.
- #11: guard part ported (#191); execution-host part deferred P4.
- #55: closed by the owner.
- #64: DEFERRED_V2.
- #77: HOLD; G2/G5 BLOCKED for v1 (D2).
- `stt/hg-capability-convergence-v1-20261110`: G4 admission source; do not touch `0feca8a`.

## 2. Cloud test baseline on `13a56be` — VERIFIED (cloud only, not the device)

| Suite | Command | Exit | Result |
|---|---|---|---|
| MAEP | `python3.13 -m unittest discover -s maep/tests` | 0 | 385 OK |
| HG | `python3.13 -m unittest discover -s hg/tests -t .` | 0 | 1,030 OK, 6 skipped (root-only) |
| Hooks | `python3.13 -m unittest discover -s .claude/hooks -p "test_*.py"` | 0 | 42 OK |
| Selfcheck | `python3.13 -m hg selfcheck` | 0 | PASS |
| Bench | `python3.13 -m hg bench` | 0 | PASS |
| Root-skipped tests as uid `nobody` | `python3.13 -B -m unittest hg.tests.test_deploy_scripts hg.tests.test_fs_write_permission_oracle hg.tests.test_release` | 0 | 68 OK, 0 skipped |
| Release build ×2 | `python3.13 -B -m hg.release build/verify --commit 13a56be…` | 0 | Byte-identical; `VERIFIED`, 387 files, tree `9cb74a45`, cloud release id `10a1710e8ae4…` (zlib differs from the phone) |
| Web UI in real Chromium | `python3.13 -m hg.tests.ui_browser_e2e` (Chrome for Testing 153, Playwright 1.63) | 0 | 14/14 PASS |

Python 3.14 is not installed in this cloud workspace. CI covers 3.13 and 3.14 on GitHub.

## 3. Termux / production / runtime — OBSERVED 2026-11-19 23:24 +07 (device came online at 23:23)

- `WORKTREE_INVENTORY.csv`: 43 worktrees, 24 dirty, all preserved.
- `DIRTY_WORKTREE_PRESERVATION.md`: `~/HG` is unchanged from mission §4.3; 2 phone-only commits are bundled offline (D1).
- `PRODUCTION_BASELINE.md`: release `030a88d5`, pointer and shim hashes equal the ledger, so production is UNCHANGED.
- `RUNTIME_BASELINE.md`: outage table (≥ 35 % availability over 118 h), findings F-P3-1..3, Soak 5 final INCOMPLETE.
- Collector: `~/hg-v1-evidence/p0-collector-20261119.sh`. Output: `~/hg-v1-evidence/p0-forensic-20261119T162422Z/` (SHA256SUMS on the device).

Status update: the header says PARTIAL (cloud session start). P0 is now **VERIFIED** on both sides, except per-worktree content classification. That classification is listed under Phase 1 in `DIRTY_WORKTREE_PRESERVATION.md`.

## 4. Risks

See `RISK_REGISTER.md`.
