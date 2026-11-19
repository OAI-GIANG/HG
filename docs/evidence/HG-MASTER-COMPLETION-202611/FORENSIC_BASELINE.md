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

## 3. Termux / production / runtime — BLOCKED_DEVICE_OFFLINE (not observed in this session)

These items still need observation on the device. The read-only collector is in `docs/governance/HG_AUTONOMOUS_HANDOFF.md`.
- `~/HG` branch/HEAD/dirty files.
- 33 worktrees.
- Unpushed commits.
- `hg-runtime` / `ollama` / staging service status.
- Production pointer and shim hashes.
- `hg availability` of production.
- Soak 5 final state. Its window ended 2026-11-19 01:46:30 +07, and its verdict is already deterministically INCOMPLETE (§65).
- Boot id.
- JobScheduler job 4211 log.

The last ledger facts are §60–§65 (2026-11-18): production `030a88d5` (from `4eaac81`), pid 27786, READY. These are **not re-verified** here, and the production status is UNVERIFIED.

## 4. Risk register (P0/P1 open items)

| ID | Risk | Evidence | Status |
|---|---|---|---|
| R-01 | The Termux process tree dies or freezes, so no 24 h soak can pass. Soak 3 gap was 23.8 h; Soak 5 had a 6,935 s gap and ENVREC=1. | §58, §65 | OPEN, P0. Owner device settings plus an on-device reboot test are needed (handoff §B). |
| R-02 | Termux:Boot autostart after reboot is unproven. | §58, §59 | OPEN, P1, owner device action |
| R-03 | L5 listener ownership cannot be proven on Android 17 as uid 10460: `/proc/net/tcp` gives EACCES and hidepid applies. L3 has no trust anchor. | §64, #205 CI l5-capability-gate red = BLOCKED | BLOCKED_WITH_TECHNICAL_EVIDENCE; accepted for v1 by D2 |
| R-04 | Model readiness must not be shown without `VERIFIED_LISTENER`. | #204 `model_status` fail-closed. Chromium check: `CHƯA ĐỦ ĐIỀU KIỆN`. | Mitigated in #204 (pending merge) |
| R-05 | Production state has not been observed since 2026-11-18. | Device offline | UNVERIFIED |
| R-06 | GitHub quota and network dependency of the trust root (RT-06 fails closed without GitHub). | §59 | Accepted by design |
| R-07 | G7 real-device Binder needs a new APK and the owner's signing key. | §56, §57, issue #197 | BLOCKED (owner) |
