# HG v1 deploy on Termux (owner's phone)

Every script stops on the first failed check (`set -eu`). Run the long ones detached, so a dropped
remote session cannot cut them short:

    nohup sh switch_service.sh <args> > ~/hg-v1-evidence/switch-$(date +%s).log 2>&1 &

0. **Read-only checks first**: `sv status hg-runtime ollama`; `cat $PREFIX/var/service/hg-runtime/{run,finish}`;
   `/proc/sys/kernel/random/boot_id` readable; `df -Pk ~`; GitHub quota
   (`curl -s https://api.github.com/rate_limit`, which itself costs nothing); `deploy_smoke.py ready`.
   Phone on the charger, preferably on Wi-Fi (a mobile carrier's NAT can share the 60/hour quota).
1. `sh build_release.sh <merged main commit>` — private build dir `~/hg-release-build/<commit>`, two
   builds compared byte for byte, `verify`, and a tree + per-file manifest digest to compare with a build
   made elsewhere. Archive bytes and therefore `release_id` may differ between platforms (zlib); tree
   and manifest must not.
2. `sh install_release.sh <commit>` — extracts to `~/hg-releases/<release_id>` (never overwrites),
   installs the manifest, `verify-root`, then `assistant_precheck.py <root>`: the release's own readers
   (`repair.inspect`, `Notebook`, `config.load`) must accept a private copy of the owner's assistant
   home (`notes.jsonl`, `config.json`, receipts; the live home is only read, its `.lock` held shared,
   never created), or the install stops before any pointer changes; then points the `hg` command at the release
   (`~/.config/hg/assistant-release`, previous pointer kept as `.prev`) and installs the shim as
   `$PREFIX/bin/hg`. The service is untouched.
3. `sh switch_service.sh --install-finish` — backs up the current `hg-runtime/finish` and installs
   `hg-runtime.finish`: it returns at once, counts short failed runs (exit 78, crash, Android kill) per
   boot, and after 5 holds the service down with a log line, a marker file and an Android notification.
   The wait between attempts is at the top of `./run` (`hg-runtime.run.in`), polls the free
   `/rate_limit` endpoint, and is cut short by `sv down`.
3b. **Rehearse in staging before every production switch** (G6, G8-A):
   `nohup sh staging_rehearsal.sh ~/hg-staging-<name> <candidate commit> [port] > /dev/null 2>&1 &`.
   It refuses (exit 2, `STAGING_REFUSED`, nothing created) a staging dir that is not an absolute plain
   path inside `$HOME`, overlaps a live HG path or exists without its `.hg-staging` marker, the
   production port, a port already in use, and a short commit. The staging dir gets its own `HOME`,
   `PREFIX`, runsvdir, token, state and port (default 18867); the production release is rebuilt there
   from its manifest commit and must reproduce the same release id; the owner's assistant `config.json`
   is copied for the model settings, never the notes or receipts. With the candidate's own scripts it
   runs traffic → `switch_service.sh <candidate>` (`SWITCH_OK`) → G8-A J2 (`/v1/tasks`, pre-authored
   `fs.write`, `CLOSED_VERIFIED`, file hash = observed hash) and J1 (`/v1/chat` → `ModelRouter` → the
   local model, no task or action) → `--restore` over the state the candidate wrote (`RESTORED`) →
   traffic → a switch interrupted with TERM after the stop (`ROLLBACK_READY_VERIFIED`) → traffic, then
   tears staging down. Production is only read (absolute-path `sv status`, file hashes, GET ready) and
   must be equal before and after. `<staging dir>/rehearsal-<UTC>/rehearsal.log` ends with
   `REHEARSAL_RESULT …` and `REHEARSAL_PASS` (exit 0) or `REHEARSAL_FAIL`; evidence has `SHA256SUMS`.
   A full rehearsal used 16 of the phone's 60 GitHub calls per hour on 2026-11-13 (each start and each
   decision after 5 minutes reads the trust root): start it with the quota at 30 or more, or wait for the reset.
4. `sh switch_service.sh <release_id>` — while the old release keeps serving: recovery point (run
   script, shared config, finish, status, hashes), one config file per release (fields checked if it
   already exists), GitHub quota ≥ 20, `verify-root`, read-only `serve --check`, the new release reads
   the assistant home chat opens (`assistant_precheck.py`, report kept in the switch dir), the config matches the
   shared one in state_dir/port/token/host/body limit, the reviewed finish is installed, free space, the
   rendered run script parses, and the running run script names the config and release a rollback would
   return to. Only then a graceful `sv down` (never SIGKILL), a state backup under the service's own
   writer lock with both trees hashed, and `state_precheck.py` proving the new release reads that state.
   Then the new run script, start, READY on the expected release with a stable pid.
   The writer lock is held on the switch shell's own descriptor (`state_lock.py acquire`), not by a
   helper process, and ownership is proven through that descriptor (`state_lock.py verify`) before the
   backup, after it, around the precheck and before every rename and run-script swap; if the lock is
   no longer the switch's, it stops before the next change (PR #87 review F-01).
   Only one switch runs at a time: the script first takes `~/hg-v1-evidence/.switch.lock` on its own
   fd 7 and a second run refuses before touching anything (review A-01). From the stop until a verified
   start it keeps runit's `hg-runtime/down` marker, so a reboot mid-cutover does not auto-start whatever
   pair is on disk; identities for a manual recovery are in `<switch dir>/cutover.env` (A-09). READY
   counts only from the supervised pid running `hg serve --config <that config>` (A-08). Once the new
   pair is proven READY the switch is committed: a later failure is reported
   (`COMMITTED_SWITCH_EXIT_<rc>`) and never rolled back (A-04).
   Any failure or interruption before that runs the EXIT trap, which ignores further HUP/INT/TERM
   until it is done. It first proves the service DOWN (`sv down` must succeed and `sv status` must say
   down with no `want up`, A-07), then reads what really changed from the filesystem — the
   live/incoming state directory identities (dev:ino) and the run-script hash — never from flags,
   because a signal can land after a rename and before the next command (review F-05). It puts back the
   run script and the state directory that ran before (state renames only under a proven lock),
   re-reads both, and starts only that pair. If a release that started wrote to the live state, the
   trap first copies it under the lock and proves the previous release reads it; otherwise it stays
   DOWN with `ROLLBACK_STATE_CHANGED_SERVICE_DOWN` and keeps everything, so `--restore-state <switch
   dir>` can return to the backup (A-03). If another process holds the state lock it does not start
   (`ROLLBACK_LOCK_CONTENDED_SERVICE_DOWN`). A verified start prints `ROLLBACK_READY_VERIFIED
   release=<id>`. If READY is not reached it stops the service again so runit cannot restart-loop it:
   `ROLLBACK_READY_UNVERIFIED release=<id>` followed by `SERVICE_DOWN_VERIFIED` or
   `SERVICE_STATE_UNKNOWN` (review F-06). A state layout or run script this switch did not produce is
   left exactly as found (the other component may still be put back) and nothing is started:
   `ROLLBACK_INCOMPLETE_SERVICE_DOWN` (or `..._SERVICE_STATE_UNKNOWN` when DOWN cannot be proven).
   `ROLLED_BACK_AFTER_FAILURE` only says the trap ran; it is not rollback evidence (review F-04).
   `HG_READY_WAIT_SECONDS` (default 180) bounds each wait for READY.
5. `python3 -I -B deploy_smoke.py ready|ready-wait RID SECONDS|submit TAG|get TASK_ID` — readiness, a
   verified write on a task id that did not exist (`replayed: false`) with independent read-back,
   idempotent replay and a 409 for a changed body.
5b. Web UI and chat (release with `hg/ui/`): `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18766/ui/` → `200` without a token, `POST /v1/chat` without a token → `401`; then the on-device UI check, which runs the release's own `app.js` against the live service and the real local model (jsdom is installed once into a private evidence directory, never into the release):

       npm install --prefix ~/hg-v1-evidence/ui-smoke jsdom@26
       HG_JSDOM_DIR=~/hg-v1-evidence/ui-smoke node <release_root>/deploy/termux/ui_smoke.mjs 18766 ~/hg-v1-evidence/ui-smoke-$(date +%s).json "Thủ đô của Pháp là gì?" general

   It reads the token itself (never printed, never in argv or the report) and exits 0 only if the page showed READY and an ANSWERED reply.
6. Rollback: `sh switch_service.sh --restore <switch dir>` refuses if the shared config changed, takes the
   release and config to return to from the recorded `run.old` (not from the shared config, whose
   `release_id` the forward switch never updates — finding F-W2), checks
   the old release (quota, verify-root, preflight), stops, backs up the current state, proves the OLD
   release reads it, puts the recorded run script back and waits for READY. If the old release could
   not read the state, `--restore-state <switch dir>` also puts back the backed-up state after checking
   its hashes (the replaced copy is kept). On failure the trap returns to the release that was running.
   Roll forward by running step 4 again.

`python3 -I -B eval_resumable.py <release_root> <spec.json> <workdir> <out.json>` runs the fixed
evaluation with the release's own `ask()` and `evaluate.score()`, appending each receipt to
`<workdir>/receipts.jsonl` as soon as it exists, so a run killed by Android (F-D2) is started again with
the same arguments and continues at the first unanswered question. Notes go to `<workdir>/home`, never
the owner's notes. `hg/tests/test_eval_resumable.py` checks it scores like `hg eval`.

`state_precheck.py <release_root> <state copy>` loads a COPY of the state with a release's own loaders
(tasks, actions, memory, idempotency); never point it at the live directory.

Never run these from `~/HG` expecting them to use that checkout: the owner's checkout is not a release.
