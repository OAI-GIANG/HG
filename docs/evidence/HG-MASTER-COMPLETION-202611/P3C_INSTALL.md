# P3 Strategy C — install on the phone (2026-11-20 00:10 +07, from merged main 2201ab9)

Script: `~/hg-v1-evidence/p3c-install-20261120.sh`. Log: `~/hg-v1-evidence/p3c-install-20261120/install.log` (sha256 `a79af46f…`).

| Item | Before (backed up) | After |
|---|---|---|
| `~/.termux/boot/00-start-services` | `dc91b241…`, mode 700, mtime 2026-11-18 00:25 | `618f5856…` (= `deploy/termux/hg-start-services.boot.sh`) |
| `$PREFIX/etc/profile.d/start-services.sh` | `8c8b8c52…`, mode 700, mtime 2022-12-27 (termux-services 0.13) | `e1fd7e2e…` (= `deploy/termux/hg-start-services.profile.sh`), mode kept |
| `~/.local/bin/hg-ensure-services.sh` | absent | `3acc0785…`, mode 700 |

The files were fetched from `raw.githubusercontent.com/OAI-GIANG/HG/2201ab9…`, and each sha256 was checked before install. Backups are in `~/hg-v1-evidence/p3c-install-20261120/backup/`. The rollback command is recorded in `install.log`.

**Verification:**
- Boot hook run by hand: rc 0, `PRESENT pids=2665 source=boot`.
- New login shell: `PRESENT pids=2665 source=profile`.
- Exactly 1 production runsvdir.
- Production `prod-before` = `prod-after` (`prod-diff.txt` empty): pidfile 2665, hg-runtime 2682, ollama 2679, 5 file hashes.

**Not verified yet (owner):**
- A real reboot through Termux:Boot.
- The Android settings in handoff §B (Termux, Termux:Boot, Termux:API).
- `termux-api` package 0.60.0 is installed from the signed mirror (dpkg). The `com.termux.api` app is installed, but its installer source is UNVERIFIED (not readable as uid 10460).
