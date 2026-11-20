# HG autonomous handoff — device work queue (Master Completion V2.0)

Read `HG_AUTONOMOUS_EXECUTION_STATE.md` first, then work through this queue in order.

Preconditions:
- The phone shows **online** in Desktop Commander.
- Production is read-only until the owner approves production.
- Never run `reset`, `clean`, or `rm` on `~/HG`, on worktrees, or on `recovery/*`.

## A. Read-only forensic collector (Phase 0, Termux) — DONE 2026-11-19 23:24 (`~/hg-v1-evidence/p0-forensic-20261119T162422Z/`; script `p0-collector-20261119.sh`, sha256 `0075d429…`). Re-run it the same way for later snapshots.

Run it detached. It only reads and writes one new directory under `~/hg-v1-evidence/`.

```sh
out=~/hg-v1-evidence/p0-forensic-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$out"; cd "$out" || exit 1
{ date -Is; cat /proc/sys/kernel/random/boot_id; cat /proc/uptime; getprop ro.build.version.release; getprop ro.build.version.sdk; id; } > device.txt 2>&1
{ git -C ~/HG remote -v; git -C ~/HG rev-parse --abbrev-ref HEAD HEAD; git -C ~/HG status --porcelain=v1 --branch --untracked-files=all; } > home-checkout.txt 2>&1
git -C ~/HG worktree list --porcelain > worktrees.txt 2>&1
git -C ~/HG for-each-ref --format='%(refname) %(objectname) %(upstream:track)' refs/heads > local-branches.txt 2>&1
git -C ~/HG worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r w; do printf '== %s\n' "$w"; git -C "$w" rev-parse --abbrev-ref HEAD HEAD 2>&1; git -C "$w" status --porcelain=v1 2>&1 | head -50; done > worktree-status.txt
{ for s in "$PREFIX"/var/service/*; do sv status "$s"; done; } > services.txt 2>&1
{ readlink -f ~/.config/hg/assistant-release; sha256sum ~/.config/hg/assistant-release* "$PREFIX/bin/hg" "$PREFIX/var/service/hg-runtime/run" "$PREFIX/var/service/hg-runtime/finish"; } > production-pointers.txt 2>&1
ls -la ~/hg-releases > releases.txt 2>&1
ls -d ~/hg-staging-* ~/.cache/hg-worktrees/* > staging-and-cache-dirs.txt 2>&1
termux-job-scheduler --pending > jobs.txt 2>&1; find ~/.local ~/hg-v1-evidence -maxdepth 4 -name guard.log 2>/dev/null | while read -r f; do echo "== $f"; tail -n 20 "$f"; done >> jobs.txt 2>&1
sha256sum ./*.txt > SHA256SUMS; echo "P0_FORENSIC_DONE $out"
```

Next steps after the collector:
1. Read `services.txt` and `production-pointers.txt`.
2. Take the production state dir from `$PREFIX/var/service/hg-runtime/run` and run `python -m hg availability --state-dir <that dir>` with the production release's own `hg`. This is read-only.
3. Run `deploy_smoke.py ready` against production with its token file. Do not print the token.
4. Compare the hashes with §57/§62. Report every difference as a finding; never fix production in place.

## B. Termux reliability RCA (Phase 3). The owner must do these steps on the phone.

The ledger evidence: the whole Termux tree vanished for 23.8 h (§58), there were 48–62 min tick stalls (§58), and Soak 5 had a 6,935 s gap (§65). This pattern fits Android/ColorOS killing or freezing the app, not an HG crash.

External references (2026-11-19 search):
- Android 12+ has a "phantom process killer". It kills background child processes of an app beyond 32, or ones that use too much CPU.
- Android 14 and later have a Developer options toggle, **"Disable child process restrictions"**, that turns it off. It survives a reboot.
- ColorOS has its own controls: auto-launch, battery optimisation, background activity, "sleep standby optimisation" and "app quick freeze".
- termux-app issue #5150 reports kills on Android 15 even with a wake lock and unrestricted battery.

Device findings, 2026-11-19 (see `RUNTIME_BASELINE.md`):
- The JobScheduler guard stopped after 2026-11-18 15:18 (F-P3-1).
- The manual-open recovery path takes no wake lock (F-P3-2).
- Step 3 below therefore also applies to **Termux:API** (`com.termux.api`), which owns the job: background allowed, battery not optimised.

Owner actions, one at a time. Read each value before changing it, and take a screenshot as evidence:
1. Settings → Developer options → **Disable child process restrictions** = ON.
2. Settings → Apps → **Auto-launch**: Termux = ON, Termux:Boot = ON.
3. Battery → app battery management → Termux and Termux:Boot: allow background activity / Don't optimise. Turn off sleep standby optimisation, and turn off app quick freeze for both apps.
4. Open Termux:Boot once. Then reboot the phone **without opening Termux** and wait 5 minutes.
5. Then, from Desktop Commander, run the read-only checks:
   - `sv status $PREFIX/var/service/hg-runtime` must show it running with an uptime close to the time since boot.
   - `python -m hg availability --state-dir <prod state>` must show a start record with `since_boot_s` and a previous-end class of `DEVICE_REBOOT`.

Acceptance for R-01/R-02:
- After a reboot, `hg-runtime` is READY without anyone opening Termux.
- A new 24 h staging soak window, started only after steps 1–5, has no gap over 3,600 s and ENVREC=0.
- If gaps remain, record `hg availability` stalls (measured suspend vs. suspected freeze) for the next RCA strategy. Strategy B is the JobScheduler guard already registered as job 4211. Strategy C is to keep HG off the critical path of Termux UI lifetime. **Do not** fall back to `nohup`/`setsid` alone.

## C. Other device-only items (later)

- Soak 5 final files: archive and hash them only. Its verdict stays INCOMPLETE (§65).
- PR #204 UI check in a browser on the phone itself, after merge, against an isolated staging release (G6 pattern, own port). Never against production.
- G7 real-device Binder: BLOCKED. It needs a new APK, the owner's signing key and issue #197.

## D. P3-B reboot acceptance — read-only (owner decision D-03). Run ONLY after the owner confirms that §B 1–5 are done and the phone was rebooted without opening Termux.

```sh
out=~/hg-v1-evidence/p3b-reboot-acceptance-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$out"; chmod 700 "$out"; cd "$out" || exit 1
OLD_BOOT=1b823ef0-e312-451e-a56c-7ec308c57073; CFG=$(ls ~/.config/hg/runtime-service-030a88d5*.json)
{ echo "now=$(date -Is) boot_id=$(cat /proc/sys/kernel/random/boot_id) old=$OLD_BOOT"
  echo "C1_boot_changed=$([ "$(cat /proc/sys/kernel/random/boot_id)" != "$OLD_BOOT" ] && echo yes || echo NO)"
  echo "C2_C3_ensure_log:"; grep -E "source=boot" ~/.local/state/hg-ensure-services/ensure.log | tail -5
  echo "C4_prod_runsvdir=$(ps -A -o args= | awk -v s="$PREFIX/var/service" '$1 ~ /runsvdir$/ && $2 == s' | wc -l) pidfile=$(cat $PREFIX/var/run/service-daemon.pid)"
  ps -A -o pid,ppid,etime,args | grep -E "runsvdir|runsv |hg serve|ollama serve|desktop-commander" | grep -v grep
  echo "C5_runit:"; sv status $PREFIX/var/service/hg-runtime $PREFIX/var/service/ollama
  echo "C5_ready:"; HG_SERVICE_CONFIG="$CFG" python3 -B ~/hg-releases/030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5/deploy/termux/deploy_smoke.py ready
  echo "C6_release=$(ps -A -o args= | grep -o 'runtime-service-[0-9a-f]*' | sort -u)"
  echo "C7_hashes:"; sha256sum ~/.config/hg/assistant-release ~/.config/hg/assistant-release.prev $PREFIX/bin/hg $PREFIX/var/service/hg-runtime/run $PREFIX/var/service/hg-runtime/finish $PREFIX/var/service/ollama/run
  echo "C8_dc_instances=$(ps -A -o args= | grep -c '[d]esktop-commander/dist/index.js remote')"
} > acceptance.txt 2>&1; sha256sum acceptance.txt > SHA256SUMS; cat acceptance.txt
```

Expected values:

| Check | Expected |
|---|---|
| C1 | `yes` |
| C2/C3 | `WAKE_LOCK_OK source=boot`, then `STARTED` or `PRESENT source=boot`, timestamped after boot |
| C4 | `1` |
| C5 | Both services `run`; ready HTTP 200 |
| C6 | `runtime-service-030a88d5…` |
| C7 | `6739742c…` `14f681a5…` `d17b5c0c…` `50a162a7…` `c200ca09…` `ecbd836c…` |
| C8 | `1` (runit only) |

Do not judge from the log alone. Cross-check the pids, the etime against the boot time, `sv status` and the readiness result. Any mismatch → BLOCKED/UNVERIFIED, and stop any later side-effecting step (no soak start).

## E. P1 second pass — per-row disposition (read-only)

For each row of `~/hg-v1-evidence/p1-dirty-map-20261120/dirty-map.csv`, compare three blobs: the working-tree file (`git hash-object`), the worktree `HEAD:<path>`, and `main:<path>`.

| Class | Rule |
|---|---|
| INTEGRATED | worktree file = main |
| LOCAL_ON_MAIN_BASE | HEAD blob = main blob; the dirty change sits on top of an unchanged base |
| CONFLICT | HEAD ≠ main and worktree ≠ both |
| UNTRACKED_COLLISION | untracked file whose path exists on main with other content |
| UNIQUE_CODE / UNIQUE_DOC_EVIDENCE | path absent on main; split by type |
| LOCAL_DELETION | file deleted in the worktree |

Preservation before any plan: `tar` the dirty files of each worktree, together with `git diff` / `git diff --cached` patches, into `~/HG-OFFLINE-BACKUP-<date>/dirty-<worktree>.tar` with a SHA256 manifest. Worktrees and branches stay untouched.

## F. L3 provenance chain, explicit (keep 0.40.16 evidence; production BLOCKED, D-05)

In `~/hg-v1-evidence/l3-provenance-20261119/`:
- copy `$PREFIX/var/lib/apt/lists/*termux-main*InRelease` and the `Packages` file;
- run `gpgv --keyring <termux keyring in $PREFIX/etc/apt/trusted.gpg.d> InRelease` and record the result;
- check that the `SHA256` line for `main/binary-aarch64/Packages` in InRelease equals `sha256sum Packages`;
- check that the Packages stanza `SHA256` equals the `.deb` (`66b5ec8b…`), and that the extracted binary is `5809c69d…`;
- write MANIFEST + SHA256SUMS.

Label the result `BINARY_PROVENANCE_QUALIFIED`. It is never `VERIFIED_LISTENER`; L5 stays BLOCKED.

## G. P3-D options (whole Termux tree killed on the same boot) — research 2026-11-20. Owner decision required for B2/C2.

| Option | What | Cost / risk | Status |
|---|---|---|---|
| B1 | Re-register the existing JobScheduler guard (job 4211) **after** the owner sets Termux:API to unrestricted and opens it once. Android does not run jobs of an app in the restricted standby bucket on their own, which is the likely cause of F-P3-1. The guard calls the boot hook, then the entrypoint, so it shares the single flock. | Free. No new code. Needs §B step 3 first. | Ready to try after §B |
| B2 | An automation app (Tasker / MacroDroid) sends the RUN_COMMAND intent. It needs the `com.termux.permission.RUN_COMMAND` grant and `allow-external-apps=true` (which widens who can run commands in Termux), and Android may refuse background service starts. | Third-party app, possibly paid; security boundary change | OWNER_DECISION_REQUIRED |
| C2 | A small companion APK with a foreground service plus BOOT_COMPLETED that restarts Termux | New architecture, signing key, P4/V2 | DEFERRED (owner) |
