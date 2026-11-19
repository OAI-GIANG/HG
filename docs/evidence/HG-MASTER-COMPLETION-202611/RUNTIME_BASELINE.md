# Runtime and production baseline — device observation 2026-11-19 23:24 +07

Source: the read-only collector `~/hg-v1-evidence/p0-collector-20261119.sh` (sha256 `0075d429…`). Its output is in `~/hg-v1-evidence/p0-forensic-20261119T162422Z/` (SHA256SUMS kept on the phone), plus the svlogd files listed below. Status: OBSERVED on the device. Nothing was changed, except the single action recorded in §5.

## 1. Device

OPPO PKC110, Android 17 / SDK 37, uid 10460, SELinux `untrusted_app_27`.
- Boot id `1b823ef0-e312-451e-a56c-7ec308c57073`, the same boot as 2026-11-16 16:08:44 (§58). There was no reboot since then.
- `/proc/uptime` is EACCES.
- Disk: 335 GB free. Memory: MemAvailable 5.78 GB of 15.7 GB.

## 2. Production

See `PRODUCTION_BASELINE.md`.

## 3. Production outages (P0) — last log of one life → READY of the next

These are upper bounds: a process can die after its last log line.

| # | Last sign of life (+07) | Next READY (+07) | ≤ Down | Cause |
|---|---|---|---|---|
| 1 | 2026-11-15 15:20:49 (ollama) | 2026-11-16 16:00:05 | 24.7 h | UNKNOWN (§58) |
| 2 | 2026-11-16 16:08:44 (reboot) | 2026-11-17 23:37:43 | 31.5 h | Owner closed the app, then a reboot; Termux:Boot did not run (§59) |
| 3 | 2026-11-18 14:08:44 | 2026-11-18 14:10:35 | 0.03 h | Tree restart (pid 27747 → 20273) |
| 4 | 2026-11-19 02:06:08 (ollama) | 2026-11-19 21:46:18 | **19.7 h** | UNKNOWN; whole tree gone, no reboot (same boot id) |
| 5 | 2026-11-19 22:01:27 (Desktop Commander) | 2026-11-19 22:45:44 | 0.7 h | UNKNOWN; whole tree gone, no reboot |

Window 2026-11-15 00:59 → 2026-11-19 23:24 (118.4 h): production was down ≤ 76.6 h, so observed availability is **≥ 35 %**.

Every recovery since 11-17 came from the owner opening Termux:
- `runsvdir` (pid 2665, PPID 1) and the interactive `bash -l` (pid 2628) started in the same second.
- `$PREFIX/etc/profile.d/start-services.sh` runs `service-daemon start`.

## 4. Root-cause findings (Phase 3)

- **F-P3-1 (CONFIRMED):** nothing restarts Termux after Android kills it on the same boot.
  - Termux:Boot runs only after a reboot.
  - The JobScheduler guard (job 4211, `~/.local/bin/hg-supervisor-guard.sh`) wrote its last `CHECK_OK` at 2026-11-18 15:18:44. The tree stayed alive until ≥ 02:06 the next day, and the guard never ran again. `termux-job-scheduler --pending` now prints "No jobs found".
  - Strategy B (JobScheduler) is therefore **FAILED in practice**. Its status moves from QUALIFIED (§63) to FAILED.
- **F-P3-2 (CONFIRMED):** the recovery paths behave differently.
  - The boot path (`~/.termux/boot/00-start-services`) takes `termux-wake-lock`.
  - The manual-open path (`profile.d/start-services.sh`) does not.
  - Every recovery since 11-17 used the manual path, so the CPU can suspend and the app can be frozen or killed with the screen off. This matches the 48–62 min tick stalls (§58) and Soak 5's 6,935 s gap.
- **F-P3-3 (OBSERVED):** two Desktop Commander remote instances are running: the runit service (pid 2680) and one from the interactive shell (`npm exec … remote`, pid 4042). The second one is not supervised.
- **Cause of the kills: UNKNOWN.** Uid 10460 cannot read `logcat` system buffers, `dumpsys` or `cmd`. External references agree on the likely mechanisms:
  - the Android 12+ phantom-process limit;
  - ColorOS background, freeze and auto-launch policy.

  The owner's device steps are in the handoff, §B. Confirmation needs the reboot test and a new soak.

## 5. Action taken this session (reversible)

`termux-wake-lock` at 2026-11-19 23:27:02 +07, rc 0. This restores the boot-path invariant for the current life only. It does not change any HG release, service or data. Undo with `termux-wake-unlock`.

## 6. Staging / Soak 5 (final)

`soak5-20261117T184629Z`, candidate `bad9bf4` / release `aee6efe4…`. **SOAK_VERDICT=INCOMPLETE**:
- reasons: `unobserved_gap>3600s`, `candidate_unclean_starts=1`, `termux_restarts=1`;
- 42 of 48 expected ticks executed;
- longest gap 6,935 s; unobserved 9,700 s;
- `DONE` present.

`hg-staging-soak` is down.
