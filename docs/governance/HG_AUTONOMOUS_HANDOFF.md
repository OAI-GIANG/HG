# HG autonomous handoff — device work queue (Master Completion V2.0)

Read `HG_AUTONOMOUS_EXECUTION_STATE.md` first, then work through this queue in order.

Preconditions:
- The phone shows **online** in Desktop Commander.
- Production is read-only until the owner approves production.
- Never run `reset`, `clean`, or `rm` on `~/HG`, on worktrees, or on `recovery/*`.

## A. Read-only forensic collector (Phase 0, Termux)

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
