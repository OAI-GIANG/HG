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
   installs the manifest, `verify-root`, points the `hg` command at the release
   (`~/.config/hg/assistant-release`, previous pointer kept as `.prev`) and installs the shim as
   `$PREFIX/bin/hg`. The service is untouched.
3. `sh switch_service.sh --install-finish` — backs up the current `hg-runtime/finish` and installs
   `hg-runtime.finish`: it returns at once, counts short failed runs (exit 78, crash, Android kill) per
   boot, and after 5 holds the service down with a log line, a marker file and an Android notification.
   The wait between attempts is at the top of `./run` (`hg-runtime.run.in`), polls the free
   `/rate_limit` endpoint, and is cut short by `sv down`.
4. `sh switch_service.sh <release_id>` — while the old release keeps serving: recovery point (run
   script, shared config, finish, status, hashes), one config file per release (fields checked if it
   already exists), GitHub quota ≥ 20, `verify-root`, read-only `serve --check`, the config matches the
   shared one in state_dir/port/token/host/body limit, the reviewed finish is installed, free space, the
   rendered run script parses. Only then a graceful `sv down` (never SIGKILL), a state backup under the
   service's own writer lock with both trees hashed, and `state_precheck.py` proving the new release
   reads that state. Then the new run script, start, READY on the expected release with a stable pid.
   Any failure or interruption after the stop runs the EXIT trap: the previous run script goes back and
   the service is started again.
5. `python3 -I -B deploy_smoke.py ready|ready-wait RID SECONDS|submit TAG|get TASK_ID` — readiness, a
   verified write on a task id that did not exist (`replayed: false`) with independent read-back,
   idempotent replay and a 409 for a changed body.
6. Rollback: `sh switch_service.sh --restore <switch dir>` refuses if the shared config changed, checks
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
