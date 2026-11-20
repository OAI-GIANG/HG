# HG autonomous execution state — Master Completion V2.0

The single resume point for this mission. Update it in place at each milestone; history lives in git and in the ledger. On resume:
1. Read this file.
2. Verify `main`, the branches and the device yourself.
3. Never repeat a side-effecting step whose result is unknown.

## Checkpoint 4 — 2026-11-20 ~12:30 +07 (owner decisions D-03..D-05; waiting on device and owner)

| Field | Value |
|---|---|
| `main` | `2201ab9` (unchanged; CI green) |
| Device | **OFFLINE**, last seen ~05:00 +07. Cause UNKNOWN until it is online: possibly P3-D again, the owner's reboot, or the phone being off. |
| Owner confirmation of §B + reboot | **NOT RECEIVED**. P3-B checks (handoff §D) prepared, NOT_RUN. |

| Item | Status |
|---|---|
| P3-A, manual open | VERIFIED (staging A + installed profile hook) |
| P3-B, Termux:Boot after reboot | UNVERIFIED (waiting on the owner) |
| P3-C, child dies while runsvdir lives | VERIFIED (staging) |
| P3-D, whole tree killed on the same boot | BLOCKED_WITH_TECHNICAL_EVIDENCE. Options B1/B2/C2 in handoff §G. |
| P4 | Candidate source VERIFIED in the cloud (`RC_CLOUD_BUILD_2201ab9.md`). Device build ×2, rehearsal and soak NOT_STARTED (D-04 gate: P3-B). |
| P1 | Second-pass rules and the preservation archive defined (handoff §E). NOT_RUN (device offline). |
| L3 | 0.40.16 BINARY_PROVENANCE_QUALIFIED candidate. Explicit gpgv chain (handoff §F) NOT_RUN. Production L3 BLOCKED; upgrade and trust registry NOT APPROVED (D-05). |
| Production | `030a88d5`; last read-only check 2026-11-20 00:10 UNCHANGED. Not observed since. |

## Checkpoint 3 — 2026-11-20 ~00:15 +07 (owner decisions D-01/D-02, 2026-11-19 23:53)

| Field | Value |
|---|---|
| `main` | `2201ab9`: #207 squash on `47e076e`, which is #204 squash on `13a56be` |
| Recovery points | `recovery/main-pre-204-20261119` → `13a56be`; `recovery/main-pre-207-20261120` → `47e076e` (both checked with ls-remote) |
| CI | #204 head `027b450` 6/6; main `47e076e` unittest 3.13/3.14 success; #207 head `26ecd6c` 6/6 |
| Production | `030a88d5`, pids 2665/2682/2679. Hashes unchanged across every device step (5 before/after diffs, all empty). |

| Phase | Status |
|---|---|
| P5 UI | #204 MERGED (`47e076e`): Chromium 25/25. On-phone browser check NOT_RUN. |
| P3 Strategy C | #207 MERGED (`2201ab9`). Device staging A/B/C/E/F VERIFIED. Installed and VERIFIED (`P3C_INSTALL.md`). Whole-tree kill on the same boot: **BLOCKED_WITH_TECHNICAL_EVIDENCE**. Reboot and owner Android settings UNVERIFIED. |
| P1 | Dirty map done (`P1_DIRTY_WORKTREE_MAP.md`): 304 unique / 101 differ / 24 same. Per-row disposition pending. |
| P2 L3 | Candidate 0.40.16 QUALIFIED in staging (`L3_UPGRADE_CANDIDATE_ASSESSMENT.md`). Production upgrade needs an owner decision. |
| P4 | Not started. Waits for P3 acceptance: owner settings, then a reboot test. |

## Checkpoint 2 — 2026-11-19 ~23:40 +07 (same mission; the phone came online 23:23)

| Field | Value |
|---|---|
| `main` | `13a56be` (unchanged) |
| PR #204 | Open, ready, head `027b450`, CI green. Still **not merged**: the session permission refused the merge in checkpoint 1 and the merge was not retried. |
| Device | Online. Boot `1b823ef0` (no reboot since 11-16). Runit tree restarted at 22:45:39 after the owner opened Termux. |
| Production | `030a88d5`, pid 2682, READY line 22:45:44. Pointer and shim hashes equal §56/§57: **UNCHANGED (VERIFIED read-only)**. |
| Device action | `termux-wake-lock` at 23:27:02 (reversible). No other device change. |

| Phase | Status |
|---|---|
| P0 | **VERIFIED**: GitHub, cloud and device sides (`docs/evidence/HG-MASTER-COMPLETION-202611/`). Per-worktree content classification moved to P1. |
| P2 L3 | BLOCKED for the running 0.40.14. A signed-index candidate exists for 0.40.16 (`5809c69d…`); adopting it needs owner approval (`docs/evidence/HG-LISTENER-ATTESTATION-202611/L3_PROVENANCE.md`). |
| P3 | Root-cause findings F-P3-1..3 CONFIRMED/OBSERVED (`RUNTIME_BASELINE.md`). Strategy B (JobScheduler) FAILED in practice. Next: Strategy C, one idempotent ensure-services entry point used by both the boot and manual paths, and it takes the wake lock. This is a repo change under `deploy/termux/` with tests. Strategy A: owner settings (handoff §B). |
| P4 | Soak 5 final = INCOMPLETE (42/48, gap 6,935 s). A new window only after P3. |

## Checkpoint 1 — 2026-11-19 ~23:30 +07 (cloud session)

| Field | Value |
|---|---|
| Mission | HG — Master Autonomous Completion, Real-World Operationalization & Reliability Mission V2.0 (2026-11-19 22:18 +07) |
| `main` | `13a56be` (unchanged in this session) |
| Integration branch | `stt/hg-master-completion-v2-20261119` (this branch), based on `13a56be` |
| Recovery points | `recovery/main-pre-204-20261119` → `13a56be` (verified with ls-remote) |
| Device | Phone (`localhost`) OFFLINE all session. No device, staging or production action. |
| Production | `030a88d5` per ledger §57–§65. **UNVERIFIED** this session. |

### Phase status

| Phase | Status | Evidence / blocker |
|---|---|---|
| P0 forensic | PARTIAL | GitHub side and cloud test baseline VERIFIED (`docs/evidence/HG-MASTER-COMPLETION-202611/`). Termux side BLOCKED_DEVICE_OFFLINE. Collector in the handoff, §A. |
| P1 reconcile | NOT_STARTED | First-pass blob map in `UNMERGED_IMPLEMENTATION_MAP.csv`. A history-based check is next. |
| P2 listener L1–L5 | BLOCKED_WITH_TECHNICAL_EVIDENCE | §64. #205 fail-closed (draft; real-kernel gate red = BLOCKED). L3 has no trust anchor. Owner D2 accepts BLOCKED for v1. |
| P3 Termux reliability | RCA hypothesis ready; owner device actions pending | Handoff §B: phantom-process toggle, ColorOS auto-launch/battery/freeze, reboot test |
| P4 soak 24 h | BLOCKED | Soak 5 INCOMPLETE (gap 6,935 s, ENVREC=1). A new window only after P3 actions. |
| P5 UI | READY_TO_MERGE (#204) | Real Chromium 25/25 PASS. CI 6/6 green on `027b450`. Ready for review. **Merge was refused by the session's permission system.** |
| P6 Android | BLOCKED (G7 needs an APK, signing key and issue #197); G8 AC1–AC5 DEFERRED P4 (owner G8-A) | §55–§57 |
| P7 MAEP matrix | NOT_STARTED | — |
| P8–P10 | NOT_STARTED | Gated on P3/P4 |

### Open PR dispositions
- **#204:** READY_TO_MERGE. The owner, or a session with merge permission, squash-merges head `027b450` only.
- **#206:** CI-only, green, still draft. Merge after #204, then add one ledger line in the same PR.
- **#205:** DRAFT. It targets #77; its real-kernel gate is red by design. HOLD.
- **#77:** HOLD.
- **#64:** DEFERRED_V2.

### Conflict for the owner to resolve

Mission V2.0 §XI.11.3 and AC-18 ask for an independent verifier. Owner decision OD-IR-20261109 sets `INDEPENDENT_REVIEW_REQUIRED = false`, and `maep/tests/test_no_mandatory_independent_review.py` enforces it. Until the owner versions a new decision, independent checks are run as **advisory** only and never block a gate.
