# P3 Strategy C — real-device staging drill (OPPO PKC110 / Android 17 / Termux, uid 10460)

Driver: `~/hg-staging-p3c-20261119{,b}-drill.sh`. The entrypoint was fetched from GitHub at a pinned commit and checked by sha256 before use. Staging was isolated: its own SVDIR (`~/hg-staging-p3c-20261119b/service`, one dummy service `p3c-dummy`) and a `service-daemon` shim that runs the same `start-stop-daemon` call with a staging pidfile. Every kill targeted a pid whose cmdline proved it belonged to staging. Production was read only.

## Run 1 — commit f372008 (entrypoint sha256 12c1ec35…): FAIL-CLOSED, defect found

- Every call logged `BLOCKED proc_unreadable`. Nothing started.
- Production before/after: identical.
- Cause: procfs files report size 0, so the `-s` test on `/proc/self/cmdline` failed.
- Fixed in e49784d by reading the content. Two new tests use the test host's real /proc; both fail on f372008 for this reason.

## Run 2 — commit e49784d (entrypoint sha256 3acc0785…): all scenarios as expected

| Scenario | Result |
|---|---|
| A1: owner opens Termux (profile), supervisor absent | rc 0, ABSENT_VERIFIED → STARTED, exactly one runsvdir (14691), child up |
| A2: profile again | rc 0, PRESENT 14691, no second supervisor |
| B1: boot path while present | rc 0, PRESENT 14691 |
| C1: service child killed, runsvdir alive | runsv restarted it (14722 → 15906): **runit recovers a dead child** |
| C2: runsv killed, runsvdir alive | runsvdir restarted runsv (14717 → 15936) and the child |
| D1: whole staging tree killed | after 12 s: no supervisor, no runsv. **Nothing restarts it without a trigger.** |
| D2: entrypoint (boot) after the tree loss | rc 0, ABSENT_VERIFIED → STARTED (16964) |
| E1: boot and profile at the same time | both rc 0; one supervisor (18088); profile logged `SKIP locked` |
| F1: production SVDIR, real /proc, start command replaced by a refusing shim | rc 0, `PRESENT pids=2665`; nothing started |
| Wake lock | `WAKE_LOCK_OK` on every call (profile, boot, manual) |
| Production | `prod-before.txt` = `prod-after.txt`, sha256 `1e633cfc…`. Covers pidfile 2665, hg-runtime 2682, ollama 2679, and 7 file hashes, including both current hooks (profile.d `8c8b8c52…`, boot `dc91b241…`). |

Not exercised on the device: `sv up` of the allow-listed services. Staging had none; this is covered by unit tests.

Device evidence: `~/hg-staging-p3c-20261119b/evidence/` (SHA256SUMS: `drill.log 7205a0e2…`, `ensure-staging.log e0c172f2…`, `ensure-prod-detect.log 13387ca0…`, `prod-before.txt = prod-after.txt 1e633cfc…`, `prod-diff.txt` empty `e3b0c442…`).

## Verdict

- Scenarios A, B, C, E and F: **VERIFIED on the real device (staging)**.
- Scenario D, Android killing the whole Termux tree on the same boot: **BLOCKED_WITH_TECHNICAL_EVIDENCE**.
  - Strategy C recovers only when an entrypoint runs, which means the owner opening Termux or a reboot.
  - The external trigger (JobScheduler job 4211) has not run since 2026-11-18 15:18 (RUNTIME_BASELINE F-P3-1).
  - The owner's Android settings (handoff §B, including Termux:API) remain the open strategy.
