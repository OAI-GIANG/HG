# HG v1 deploy on Termux (owner's phone)

Order (each script stops on the first failed check; `set -eu`):

1. `sh build_release.sh <merged main commit>` — private build dir `~/hg-release-build/<commit>`, two builds compared byte for byte, `verify`, and a tree + file-manifest digest to compare with a build made elsewhere (archive bytes may differ across platforms; tree and manifest must not).
2. `sh install_release.sh <commit>` — extracts to `~/hg-releases/<release_id>` (never overwrites), installs the manifest, `verify-root`, points the `hg` command at the release (`~/.config/hg/assistant-release`) and installs the shim as `$PREFIX/bin/hg`. The service is untouched.
3. `sh switch_service.sh <release_id>` — records a recovery point (run script, shared config, status, hashes), writes one config file per release, runs the read-only preflight, stops the service, backs up the whole state directory with hashes (including SQLite `-wal`/`-shm`), writes the new run script and a `finish` script that holds the service down after a fail-closed exit 78 (no restart loop against the GitHub quota), and starts it.
4. `python3 -I -B deploy_smoke.py ready|submit TAG|get TASK_ID` — readiness, a verified write with independent read-back, idempotent replay and a 409 for a changed body.
5. Rollback: `sh switch_service.sh --restore <switch dir>` puts the recorded run script back (the old release reads the state the new one wrote); roll forward by running step 3 again with the new release id.

Never run these from `~/HG` expecting them to use that checkout: the owner's checkout is not a release.
