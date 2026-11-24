# HG MASTER COMPLETION LEDGER V1 — RECONCILIATION 2026-11-10 (B): N-01 closed, running release identified, N-02 blocked

**Repository:** `OAI-GIANG/HG`
**Observed:** 2026-11-10 04:13–04:25 +07 (2026-11-09 21:13–21:25 UTC), git, GitHub REST, Desktop Commander on the owner's phone (device `22e6ee74-…`)
**Relation:** ADDITIVE to `…_20261110.*`. Rows not in the CSV are unchanged.

**Labels:** FACT = observed here; INFERENCE = derived; UNVERIFIED = not established.

## 1. N-01 — CLOSED

FACT: PR #92 merged as `82cfd5ac126db2283a4a51c7f3e2cb3ae4cc4df5` (2026-11-09T20:23Z). PR CI on `d95b869` (runs 42691338725, 42691367692, 42691367678) and push CI on the merge SHA (run 42692567152) success. The test asserts SEALED first and skips only under euid 0; non-root runs keep the full assertion.

## 2. Running release ↔ commit (closes the UNVERIFIED in `…_20261110.md` §2)

FACT (phone): `$PREFIX/var/service/hg-runtime/run` (mtime 2026-11-09 13:21) names release `54547829c939…`. `~/hg-v1-evidence/deploy-f57c7e7-20261109T062009Z-retry/release-metadata.json`: release `54547829c939…` = commit `f57c7e76799e…`, tree `acdaa529…`; `progress.log` ends `DEPLOY_FIX_COMPLETE` at 13:22:07 +07. `sv status`: up since ≈01:34 +07 (same run script, so the same release restarted; restart cause UNVERIFIED).

So production runs `f57c7e7`, which predates PR #87 (`163be5d`) and PR #88 (`d7b94d8`). The previous record's guess that it might be `163be5d` is wrong.

FACT: the capability-convergence session built a release from `163be5d` (`8ab1a888…`, `wp4-release-build-20261110/build.log`, `WP4_BUILD_FINISH` 02:09 +07) but did not install it (absent from `~/hg-releases`). No phone activity from it after 02:09. Branch `stt/hg-capability-convergence-v1-20261110` still at `0feca8a`, no PR.

## 3. N-02 — BLOCKED_EXTERNAL_ACTION

Prepared (FACT): `~/hg-v1-evidence/deploy-82cfd5a-20261110/` holds `PLAN.md`, a clean clone at `~/hg-deploy-control/82cfd5a…/repo` (HEAD `82cfd5a`, tree `4d63a72a…`), and `run-deploy.sh` — the proven `deploy-f57c7e7…/run-deploy.sh` with only commit, tree, prior-evidence directory and rollback-copy paths changed (diff checked).

NOT_EXECUTED: launching `run-deploy.sh` was refused by the cloud session's permission control. Nothing was built, installed or switched; `hg-runtime` kept pid 30715. `RESULT` in that directory says so. The hourly lock was taken and then released with a note.

Unblock: the owner runs, on the phone, `cd ~/hg-v1-evidence/deploy-82cfd5a-20261110 && nohup bash ./run-deploy.sh > orchestrator.log 2>&1 &`, or allows the hourly session to launch it. The script stops if `main` has moved past `82cfd5a`; then rebuild it for the new head.

Risk while blocked: the phone runs without the #87 ledger-admission / state-swap locks and the #88 reconcile-exception → UNKNOWN fix.

## 4. Workstreams and G1

Denominator 15 unchanged. DONE 0. G1 BLOCKED (unchanged).

## 5. Addendum 2026-11-10 07:13–07:35 +07 (hourly run, cloud only, no phone access)

FACT: WS-04 false-accept oracle work after this record — PR #94 (`925bd77`, header-less SQLite), PR #95 (`f61f3e5`, PEP 263/BOM compile), PR #96 (`d0a1f01`, SQLite result bound to snapshot digest: an altered payload byte or appended bytes passed `integrity_check`; `verify_sqlite_integrity(expected_sha256=…)` now FAILs a mismatch). PR #96 CI runs 42727470987, 42727471114, 42727441581 success; local MAEP 362, HG 587 (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr96-20261110` = `f61f3e5`.

N-02: still BLOCKED_EXTERNAL_ACTION; `main` has moved past `82cfd5a`, so the prepared `run-deploy.sh` will stop by design and must be rebuilt for the current head. Not attempted (no phone access in this run).

Remote branch `stt/ws04-sqlite-digest-binding-20261110` (merged) could not be deleted: push `--delete` refused by the session proxy. Harmless; delete when convenient.

WS-04 cross-store contract T0–T9 / R-00–R-13 remains BLOCKED_SOURCE (contract document absent from repository).

## 6. Addendum 2026-11-10 08:13–08:30 +07 (hourly run, phone reachable) — N-02 CLOSED

FACT: deploy prepared for current `main` `ad42ad8` (tree `4d606773…`, CI unittest 3.13/3.14 success on that SHA) in `~/hg-v1-evidence/deploy-ad42ad8-20261110/`: clean clone at `~/hg-deploy-control/ad42ad8…/repo`; `run-deploy.sh` = the `deploy-82cfd5a…` script with only `C`, `MAIN`, `TREE` and the smoke tag prefix changed (`diff.log`). `deploy/` and `hg/release.py` unchanged between `82cfd5a` and `ad42ad8`.

FACT: launched 08:15 +07 by this session; `RESULT=PASS`, `progress.log` ends `DEPLOY_FIX_COMPLETE` 08:26:27. Gates passed: source HEAD/tree/clean, main == C, CI on C, prior deploy evidence and both rollback copies, old runtime READY, double build (release `423730c92905…`), sealed install + `verify_root`, Termux suites (MAEP 362 OK skip 3; HG 587 OK), switch (`switch-20261110T012614Z`, rollback point), new runtime READY / integrity VERIFIED / trust LOADED / `trust_commit` `ad42ad8`, write/readback/replay/409 smoke. `evidence-selfcheck.log` all OK. Independent re-read after the run: `sv status` pid 12146 up, `ready` returns the same; `~/.config/hg/assistant-release` points to release `423730c9…`.

So production now includes #87, #88 and #94–#96. The risk recorded in §3 is closed. Rollback: `sh deploy/termux/switch_service.sh --restore ~/hg-v1-evidence/switch-20261110T012614Z`.

## 7. Addendum 2026-11-10 09:17–09:35 +07 (hourly run, cloud only, no phone access) — WS-04 evidence-store read oracle

FACT: `hg/tests/test_evidence_store_false_accept_oracle.py` damages a blob committed through the runtime (flipped/truncated/empty/appended/other bytes, swapped blob, hardlink, symlink, directory, FIFO, non-private file and directory modes) or its metadata (size, ref/digest disagreement, malformed digests and refs, absent blob) and asserts that no read (`Orchestrator.verify_artifact_evidence`, `EvidenceArtifactStore.get`, read-only view) returns bytes or PASS, within 5 s. Every damage case except FIFO was already refused.

FACT (defect, reproduced before the fix): a FIFO at a blob path blocked `get`, `verify_metadata`, `verify_artifact_evidence` and `put` until a writer opened it; the verification worker returned INCONCLUSIVE only after its timeout. Fix: `O_NONBLOCK` on both opens, so the existing regular-file check rejects it at once (FIFO candidate now BLOCKED).

FACT: PR #99 squash-merged as `227881f59d644cd2ce2dd8a10efe97fd3c861478`; PR CI on `65acc33` (runs 42742555498, 42742591860 unittest 3.13/3.14; 42742592102 rt06-anchor) success. Local: MAEP 362 OK, HG 599 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr99-20261110` = `f86ac2b`.

Deploy: NOT_EXECUTED (no phone access in this run). Production stays on `ad42ad8` (release `423730c9`); the change is a robustness fix to a fail-closed path, not a false-accept, so no urgency. Install with the next runtime batch.

## 8. Addendum 2026-11-10 10:13–11:40 +07 (hourly run, phone reachable) — WS-04 ledger read oracle; #99/#101/#102 deployed

FACT: `hg/tests/test_ledger_read_false_accept_oracle.py` damages `tasks.jsonl` and `actions.jsonl` written through the runtime (symlink, directory, writable modes, FIFO, torn tail, truncation, blank line, invalid JSON, non-UTF-8, BOM, non-object, missing `event_id`, duplicated record, duplicate JSON keys, removed or reordered records, rewritten identity or sequence) and asserts that `read_events`, runtime restart and the read-only TaskStore/EventLog views refuse within 5 s.

FACT (defects, reproduced before the fix, 18 subcases): (1) a FIFO at a ledger path blocked `read_events` and so runtime start, `TaskStore.restore` and `EventLog` until a writer opened it; (2) a record repeating a JSON key was read last-value-wins. Fix in `maep/ledger.py`: open `O_NONBLOCK` (blocking restored after the regular-file check); refuse duplicate keys. Every other case was already refused. Not covered by design: no hash chain or anchor, so removing whole tail records or a consistent rewrite is not detectable from the file alone.

FACT: PR #101 squash-merged as `f774734969c2…`; PR CI on `6d604d9` (runs 42748875733, 42748913250 unittest 3.13/3.14; 42748913491 rt06-anchor) success. Local: MAEP 362 OK, HG 607 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr101-20261110` = `bf1802f`.

FACT: deploy of `f774734` (`~/hg-v1-evidence/deploy-f774734-20261110/`, `RESULT=FAILED`) stopped before the switch: on Termux `test_hardlink_to_another_blob_is_never_accepted` (from #99) raised `AttributeError: module 'os' has no attribute 'link'` (Android has no hard links). Script restored the assistant pointer; service untouched (pid 12146, release `423730c9`). Fixed by PR #102 (`7698097ef3d6…`): the case is skipped only where `os.link` is absent, same guard as `maep/tests/test_sqlite_nofollow.py`. PR CI (runs 42755282458, 42755308840, 42755308596) and push CI on `7698097` success. Recovery branch `recovery/main-pre-pr102-20261110` = `f774734`.

FACT: deploy of `7698097` (`~/hg-v1-evidence/deploy-7698097-20261110/`, script = `deploy-ad42ad8…` with only `C`, `MAIN`, `TREE`, smoke tag changed) `RESULT=PASS`, `DEPLOY_FIX_COMPLETE` 11:33:45 +07: release `13c335cc05d5…`, Termux MAEP 362 OK (skip 3), HG 607 OK (skip 1, the hardlink case), switch `switch-20261110T043332Z`, smoke write/readback/replay/409 PASS. Independent re-read: `sv status` pid 15043 up; `ready` 200 READY / integrity VERIFIED / trust LOADED / `trust_commit` `7698097`; `~/.config/hg/assistant-release` → `13c335cc…`. Rollback: `sh deploy/termux/switch_service.sh --restore ~/hg-v1-evidence/switch-20261110T043332Z`.

So production now includes #99 (evidence-store FIFO) and #101 (ledger FIFO, duplicate keys).

## 9. Addendum 2026-11-10 12:12–12:25 +07 (hourly run, cloud, no phone access) — WS-04 assistant home read oracle (#104)

FACT: `hg/tests/test_assistant_home_read_false_accept_oracle.py` damages a home written through the assistant (notes by the Notebook, settings by `config.save`) and asserts that `hg repair` rewrites a ledger only when its sole defect is an unterminated last record, leaves every other refused file byte-for-byte unchanged, returns within 5 s, and that `config.load` refuses unsafe or ambiguous `config.json`. Controls: an intact ledger is OK, a genuine torn tail is still repaired, a saved config still loads.

FACT (defects, reproduced before the fix, 19 failing cases): (1) `repair` blocked on a FIFO `*.jsonl` while holding the home's exclusive lock (hangs every `ask`/`note`/chat) and crashed on a directory `*.jsonl`; (2) it followed a symlink and adopted a torn file from outside `HG_HOME`, and rewrote a group/world-writable ledger as 0600 (laundering a refusal); (3) a terminated invalid last record was dropped as if torn; (4) with a damaged earlier record (duplicate key, blank line, non-UTF-8, duplicate `event_id`, sequence gap) it rewrote the file before failing; (5) `config.json` accepted duplicate keys (last value wins) and group/world-writable modes. Fix in `hg/assistant/repair.py` (open like `maep.ledger`, torn = unterminated only, validate the kept prefix before writing, backup `O_EXCL` from the inspected bytes) and `hg/assistant/config.py` (same open rules, duplicate keys refused).

FACT: PR #104 squash-merged as `dc55ba08906086db12367cc9cb9c05d9643e7e47` (tree identical to head `b816bb3`); PR CI on `b816bb3` success (runs 42761364540, 42761335488 unittest 3.13/3.14; 42761364672 rt06-anchor 3.13/3.14). Local: oracle 19 OK, MAEP 362 OK, HG 626 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr104-20261110` = `6f9daa7`.

Deploy: NOT_EXECUTED (no phone access in this run). The change affects the owner's `hg repair` / config loading, not the runtime service; install with the next runtime batch. Production stays `7698097` (release `13c335cc`).

## 10. Addendum 2026-11-10 13:17–13:40 +07 (hourly run, phone reachable, deploy deferred) — WS-04 release read oracle (#106)

FACT: `hg/tests/test_release_read_false_accept_oracle.py` builds a release from a real Git commit and damages the installed tree (14 cases: flipped/truncated/appended/emptied/swapped bytes, missing/extra file, injected bytecode, exec bit added/removed, FIFO, file→directory, symlinked file/directory), the root (symlink, wrong release id), the manifest (13 cases) or the archive (7 cases), and asserts that `verify_root` / `verify_archive` raise `ReleaseError` within 5 s and never return VERIFIED. Control: the intact release verifies. Every installed-tree case was already refused.

FACT (defects, reproduced before the fix, 7 failing subcases): (1) a FIFO at the manifest or archive path blocked `verify_root`/`verify_archive` until a writer opened it — `verify_root` runs on every `/ready` and `/v1/integrity`, so the request thread never answered; (2) a symlinked manifest or archive was followed, while service preflight refuses a symlinked manifest; (3) a directory archive escaped as `IsADirectoryError`. Fix in `hg/release.py`: `_read_regular_file` (`O_NOFOLLOW|O_NONBLOCK`, `S_ISREG`, blocking restored, every failure → `ReleaseError`). Not covered by design: owner write bits on installed files (deploy verifies before sealing), extra empty directories.

FACT: PR #106 squash-merged as `09a131d0b13c354f1ff039bad1527f3f58acc61c` (tree `69e05f8b…` identical to head `612d65d`); PR CI on `612d65d` success (runs 42768572097, 42768541704 unittest 3.13/3.14; 42768571991 rt06-anchor 3.13/3.14). Local: oracle + `test_release` 23 OK (skip 2, euid 0), MAEP 362 OK, HG 633 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr106-20261110` = `ea90bd8`.

FACT (phone, read-only): `hg-runtime` pid 9512 up since ≈12:06 +07 (log `HG_RUNTIME_READY` 05:06:24 UTC), same release `13c335cc…`; the restart since pid 15043 (§8) has an UNVERIFIED cause. `.autonomous-run.lock` is in RELEASED state.

Deploy: NOT_EXECUTED by choice. Another session was running tests on the phone at 13:18 +07 (`~/HG-RCME-INTEGRATION-20261110`, evidence `audit-rcme-integration-20261110`, `audit-pr77-*`); a deploy runs the Termux suites (5 s oracle deadlines) and switches the service, so it was not started concurrently. #104 and #106 are fail-closed robustness fixes, not false accepts; install them together with the next batch when the phone is idle. Production stays `7698097` (release `13c335cc`).


## 11. Addendum 2026-11-10 14:21–14:35 +07 (hourly run, phone reachable) — #104/#106 deployed (main `5476315`)

FACT: phone idle before the run (no test or deploy process; only `hg serve` pid 9512, release `13c335cc`). Push CI on `5476315` success (run 42769583663). `deploy/` unchanged since `7698097`; `hg/release.py` changed by #106, covered by the Termux suites before the switch and by READY/integrity after it.

FACT: deploy of `5476315` (`~/hg-v1-evidence/deploy-5476315-20261110/`, clean clone `~/hg-deploy-control/5476315…/repo`, HEAD/tree `498e280a…` checked; script = `deploy-7698097…` with only `C`, `MAIN`, `TREE`, smoke tag changed, `diff.log`) `RESULT=PASS`, `DEPLOY_FIX_COMPLETE` 14:28:18 +07: release `adff9c8dae20…`, Termux MAEP 362 OK (skip 3), HG 633 OK (skip 1), switch `switch-20261110T072805Z`, smoke write/readback/replay/409 PASS. `SHA256SUMS` re-checked, 0 mismatches; `evidence-selfcheck.log` 24 OK.

FACT (independent re-read after the run): `sv status` pid 20590 up; `ready` 200 READY / integrity VERIFIED / trust LOADED / `trust_commit` `5476315`; `~/.config/hg/assistant-release` → `adff9c8d…`. Rollback: `sh deploy/termux/switch_service.sh --restore ~/hg-v1-evidence/switch-20261110T072805Z`.

So production now includes #104 (assistant repair/config) and #106 (release manifest/archive reads). No merged runtime change is left undeployed.

## 12. Addendum 2026-11-10 15:15–15:35 +07 (hourly run, phone reachable, deploy launch refused) — WS-04 verifier backlog (a): pinned worker bytes (#109)

FACT (defect, reproduced before the fix): `IndependentVerifier` re-checked the worker digest, then ran `worker.py` by path. A swap between the re-check and the exec ran unpinned code: a forging worker turned a Python syntax error into PASS (`test_worker_swapped_after_pin_check_still_runs_pinned_bytes`, `'PASS' != 'FAIL'`). Fix in `hg/verification/independent.py`: the bytes hashed at construction run via `python -I -B -c`; a worker that cannot be pinned as one argv string (> 64 KiB, NUL, non-UTF-8) is refused at construction; the change-before-call check still returns INCONCLUSIVE. Added guards: change before the call → INCONCLUSIVE; a `json.py` planted in the candidate root is not imported. Boundary unchanged (separate process, same UID; same-UID attackers out of scope, Q3).

FACT: PR #109 squash-merged as `b2a2ad3f6d419bc8c402085c861583112d27787c` (tree `3640eb96…` identical to head `535fca2`); PR CI on `535fca2` success (runs 42781679937, 42781707666 unittest 3.13/3.14; 42781707592 rt06-anchor 3.13/3.14); push CI on `b2a2ad3` unittest 3.13/3.14 success (run 42782208529). Local (Linux, uid 0): verification 36 OK, MAEP 362 OK, HG 637 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr109-20261110` = `c9e0394`.

Deploy: BLOCKED_EXTERNAL_ACTION. Prepared on the phone (FACT): `~/hg-v1-evidence/deploy-b2a2ad3-20261110/` with `PLAN.md`, clean clone `~/hg-deploy-control/b2a2ad3…/repo` (HEAD/tree checked, 0 dirty), `run-deploy.sh` = `deploy-5476315…` script with only `C`, `MAIN`, `TREE`, smoke tag changed (`diff.log`). Phone idle (only `hg serve` pid 20590). NOT_EXECUTED: the launch was refused by the cloud session's permission control; nothing built, installed or switched. Production stays `5476315` (release `adff9c8d`). Unblock: on the phone, `cd ~/hg-v1-evidence/deploy-b2a2ad3-20261110 && nohup bash ./run-deploy.sh > orchestrator.log 2>&1 &` (stops by design if `main` has moved past `b2a2ad3`), or allow the hourly session to launch it. Risk while blocked: low — the race needs a same-UID writer to the installed worker, and the installed tree is sealed read-only (a same-UID writer could unseal it; out of scope, Q3).

## 13. Addendum 2026-11-10 16:12–16:35 +07 (hourly run, phone reachable, deploy launch refused again) — WS-04 trust-root read oracle (#111)

FACT (phone, read-only, device `19e2e2a5-…` `localhost`, Termux aarch64): only `hg serve` pid 20590 running (release `adff9c8d`, main `5476315`); `.autonomous-run.lock` RELEASED. Relaunching the prepared `deploy-b2a2ad3-20261110/run-deploy.sh` was refused again by the cloud session's permission control; nothing ran, the lock was not written. The prepared script pins `MAIN=36de1b3`, so after #111 it stops by design at the main check; the next deploy must be re-prepared for the new `main`.

FACT: `maep/tests/test_trust_root_read_oracle.py` gives the RT-06 trust-root path ambiguous inputs and asserts they deny. Defects reproduced before the fix (16 failing subcases + 1 `url.read` case): (1) `authorize()` matched manifest scope by string prefix, so `file:out/../x`, `repo:OAI-GIANG/HG/../HG2` and `%2e%2e` forms were ALLOWed by the manifest check (file adapters already refused `..` at the effect); (2) GitHub API responses repeating a JSON key were read last-value-wins; (3) manifest base64 decoded with `validate=False`; (4) a negative cache age (clock stepped back) counted as fresh, extending the revocation window past `max_age_s`; (5) `url.read` let `docs/../page` pass the `docs/` scope prefix. Fix in `maep/authority/trust_anchor.py`, `maep/authority/canonical_source.py`, `hg/tools/code.py`. Not covered: `%2f` (no HG consumer decodes it).

FACT: PR #111 squash-merged as `d5673b82e8699b6d305c69d6a771aad073045c04` (tree `f781ff3c…` identical to head `1d9991a`); PR CI on `1d9991a` success (runs 42790074860, 42790110861 unittest 3.13/3.14; 42790111309 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 8 OK, MAEP 370 OK, HG 638 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr111-20261110` = `36de1b3`.

Deploy: BLOCKED_EXTERNAL_ACTION (same cause as §12). Undeployed merged runtime changes: #109, #111. Production stays `5476315` (release `adff9c8d`). Unblock: allow the hourly session to launch deploys on the phone, or launch a deploy of the current `main` there (re-prepare from `deploy-b2a2ad3-20261110` with `C`/`MAIN`/`TREE` updated). Risk while blocked: low — the authority gap was closed at the effect boundary by the adapters; the clock-step window is bounded by the size of the step.

## 14. Addendum 2026-11-10 17:13–17:35 +07 (hourly run, cloud only, deploy not attempted) — WS-04/WS-03 file adapter path oracle (#113)

FACT: `hg/tests/test_file_adapter_path_oracle.py` runs the rooted file adapters through the runtime path (orchestrator → gateway → adapter) with symlinks inside an allowed scope (final component, relative link, symlinked parent, symlinked scope directory, symlinked search start, symlinked files inside and outside the root in a walked directory) and FIFOs (walked, as search start, as fs.read / code.diff target), and asserts no effect succeeds on, and no output contains, the out-of-scope target, within 5 s. Controls: regular write/read/search/diff still succeed.

FACT (defects, reproduced before the fix, 11 of 15 cases failing): (1) the gateway authorizes and scope-checks `file:<lexical path>` but `_RootedFileAdapter` resolved symlinks and acted on the target: with grant `file:out/hello.txt` and `out/hello.txt -> ../secret/key.txt` (or a symlinked parent/scope directory), `fs.write` overwrote `secret/key.txt` and the task closed CLOSED_VERIFIED; `fs.read`, `code.diff`, `code.search` returned such targets; (2) `code.search`/`code.symbols` read symlinked files pointing outside the adapter root; (3) a FIFO in a walked directory blocked the adapter thread; a FIFO search start returned SUCCEEDED with 0 files. Fix in `hg/tools/gateway.py` (`_rel` refuses a path whose resolved location differs from its lexical location → INVALID_INPUT before any effect; `read_regular_file`: `O_NOFOLLOW|O_NONBLOCK`, `S_ISREG`, blocking restored) and `hg/tools/code.py` (walk via `lstat`, reads through `read_regular_file`). Not covered by design: same-UID racers between check and effect (Q3).

FACT: PR #113 squash-merged as `4eaac81132ae57028cf2432eec911a01b6ecf1fd` (tree `e2144894…` identical to head `b448ccc`); PR CI on `b448ccc` success (runs 42798868753, 42798901032 unittest 3.13/3.14; 42798901359 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 15 OK, MAEP 370 OK, HG 653 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr113-20261110` = `5ef8054`.

Deploy: BLOCKED_EXTERNAL_ACTION (same cause as §12–§13; not retried this run — two consecutive launch refusals by the session's permission control). Undeployed merged runtime changes: #109, #111, #113. Production stays `5476315` (release `adff9c8d`). Risk while blocked: the running service still follows symlinks inside a granted file scope; exploitation needs a symlink placed in the adapter root (untrusted workspace content or a same-UID writer). Unblock: launch a deploy of current `main` on the phone (re-prepare from `deploy-b2a2ad3-20261110` with `C`/`MAIN`/`TREE` updated), or allow the hourly session to launch it.

## 15. Addendum 2026-11-10 18:14–18:30 +07 (hourly run, phone reachable) — #109/#111/#113 deployed (code `4eaac81`, main `34c10fb`)

FACT: phone idle before the run (only `hg serve` pid 20590, release `adff9c8d`; lock RELEASED). Push CI on `4eaac81`: unittest 3.13/3.14 success. `4eaac81..34c10fb` touches only the ledger 20261110B files; `deploy/` and `hg/release.py` unchanged since `5476315`.

FACT: deploy prepared in `~/hg-v1-evidence/deploy-4eaac81-20261110/` (clean clone `~/hg-deploy-control/4eaac81…/repo`, HEAD `4eaac81` / tree `e2144894…`, 0 dirty; `run-deploy.sh` = `deploy-b2a2ad3…` script with only `C`, `MAIN`, `TREE`, smoke tag changed, `diff.log`). This time the launch was not refused. `RESULT=PASS`, `DEPLOY_FIX_COMPLETE` 18:22:22 +07: release `030a88d534bd…`, Termux MAEP 370 OK (skip 3), HG 653 OK (skip 1), switch `switch-20261110T112210Z`, smoke write/readback/replay/409 PASS. `SHA256SUMS` re-checked, 0 mismatches.

FACT (independent re-read after the run): `sv status` pid 30577 up; `ready` 200 READY / integrity VERIFIED / trust LOADED / `trust_commit` `34c10fb`; `~/.config/hg/assistant-release` → `030a88d5…`. Rollback: `sh deploy/termux/switch_service.sh --restore ~/hg-v1-evidence/switch-20261110T112210Z`.

So production now includes #109 (pinned verifier worker bytes), #111 (trust-root read oracle) and #113 (file adapter path oracle). The symlink risk recorded in §14 is closed. No merged runtime change is left undeployed.

## 16. Addendum 2026-11-10 19:18–19:40 +07 (hourly run, phone not responding) — WS-04 HTTP request parse oracle (#116)

FACT: `hg/tests/test_http_request_parse_oracle.py` sends exact bytes to a real `HGHTTPServer` and asserts that an ambiguous request is not 200, returns within 5 s, writes no file and claims no idempotency key. Controls: canonical POST (plain, `charset=utf-8`, mixed case) and GET still succeed.

FACT (defects, reproduced before the fix, 15 failing subcases — the task executed and the key was claimed): (1) absolute-form / scheme-prefixed targets (`http://attacker.example/v1/tasks`, `http://127.0.0.1:<port>/v1/tasks`, `x:/v1/tasks`) and an empty `?` or `#` reached `/v1/tasks` and the GET routes (`urlsplit` drops authority, scheme and empty query/fragment); (2) `Transfer-Encoding:` empty, or empty then `chunked`, passed (`headers.get` returned the first, empty value); (3) `Content-Type` with `charset=latin-1`/`iso-8859-1`/`utf-16`/a second charset was accepted while the body is decoded as UTF-8, so bytes valid in both encodings became a different task than declared. Fix in `hg/http_api.py`: `_origin_path()` (origin-form, not `//`, no `?`/`#`), any `Transfer-Encoding` field refused, only `charset=utf-8` accepted. Already refused: `//host/...` (http.server collapses it), `Transfer-Encoding: identity`.

FACT: PR #116 squash-merged as `7dac72c697bad15bdf81ccca7909f7cc995fc682` (tree `95c3254e…` identical to head `eee3f93`); PR CI on `eee3f93` success (runs 42815414340, 42815453334 unittest 3.13/3.14; 42815453359 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 6 OK, MAEP 370 OK, HG 659 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr116-20261110` = `8fa4bc3`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Online but last seen 15 min ago; two commands timed out with no response. Nothing was run on the phone. Undeployed merged runtime change: #116. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked: low — every affected request still needs the bearer token, a loopback client and a loopback Host; the defects let a token holder's ambiguous request be executed under one reading. Unblock: next run with the phone responding prepares `deploy-<main>-20261110` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 17. Addendum 2026-11-11 11:13–11:35 +07 (hourly run, cloud only, phone offline) — #118 recorded; WS-04 AC-READBACK byte oracle (#120)

FACT (not recorded before): PR #118 merged as `e465db2` (2026-11-10 20:30 +07): chat names the receipts ledger it actually wrote (a month-boundary chat named a file never written); `private_file` refuses notes/asks ledgers with a second hard link. Recovery branch `recovery/main-pre-pr118-20261110`.

FACT: `hg/tests/test_readback_bytes_oracle.py` runs `fs.write` tasks through the runtime path with the production AC-READBACK verifier (`planned_write_readback_verifier`, used by `hg serve`). Defects reproduced before the fix (6 failing subcases): `read_text()` translates CRLF/CR to LF, so (1) a file whose bytes differed from the plan only in line endings (CRLF or CR on disk, LF planned) closed CLOSED_VERIFIED — false accept; (2) a correct write of content containing CR (CR, CRLF, mixed) ended UNVERIFIED — false reject. Fix in `hg/http_api.py`: read with `read_regular_file` (`O_NOFOLLOW|O_NONBLOCK`, regular file only) bounded to the planned length and compare with `content.encode("utf-8")`, the bytes `fs.write` writes. Already refused (now covered): longer file with the planned prefix, non-string content, lone surrogate, FIFO (no block). Not covered: `hg selfcheck`, `hg bench` cases and the test helper `content_verifier` still compare text (harness verifiers, no CR content).

FACT: PR #120 squash-merged as `4b45ff6779740669aa53767e51fb6a2430db85d3` (tree `407bacc9…` identical to head `a56ce1c`); PR CI on `a56ce1c` success (runs 42958630441, 42958664226 unittest 3.13/3.14; 42958664048 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 7 OK, MAEP 370 OK, HG 674 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr120-20261111` = `e465db2`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈2 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked: low–medium — the running service can accept a write whose on-disk line endings were changed between effect and read-back (needs a writer in the state root), and refuses correct writes containing CR. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

Other sessions: branches `stt/hg-android-broker-ci-v1-20261111` (draft PR #119), `stt/hg-memory-continuity-r3.1-port-20261111`, `stt/hg-master-go-live-v3-execution-20261111` were active overnight; not touched by this run (no shared files with #120).

## 18. Addendum 2026-11-11 12:12–12:35 +07 (hourly run, cloud only, phone offline) — WS-04 model response read oracle (#122)

FACT: `hg/tests/test_model_response_oracle.py` serves exact bytes from a real loopback HTTP server standing in for Ollama (stream and non-stream `/api/chat`, `/api/tags`), gives the Anthropic adapter scripted bodies, and drives `ModelRouter` with a second provider; each malformed case must raise `ProviderError(INVALID_RESPONSE)` within 5 s, and after any shown text the router must not call another provider. Controls: canonical stream, body and tags still succeed; a provider bug before any text still falls back.

FACT (defects, reproduced before the fix: 23 tests, 21 failures + 16 errors): (1) repeated JSON keys read last-value-wins in answer bodies, stream lines and `/api/tags` (the model digest pin reads it); (2) non-UTF-8 bytes, non-object stream lines, non-string `content`, list `message`, non-bool `done` raised raw exceptions or were accepted; (3) token counts `true`/`-1`/`"3"`/`1.5`/`null` accepted or crashed (negative counts → negative cost); (4) data after a stream's final message was shown and returned, a second final message merged; (5) unbounded reads — an oversized line/body waited for EOF (socket timeout), an endless well-formed stream was accepted; (6) a non-`ProviderError` after text was shown fell back to the next provider (a second answer). Fix in `hg/brain/providers.py`: bounded reads (8 MiB body, 1 MiB line, 64 MiB stream, 64 KiB error body), UTF-8 only, `parse_json` (no repeated keys), shape checks, `token_count`, nothing after the final message, a bad final line refused before acceptance, router crash path keeps "stopped part-way". Not covered: `maep/authority/canonical_source.py` reads GitHub API bodies unbounded (repeated keys already refused, #111).

FACT: PR #122 squash-merged as `694318f6dce5932f60bd421326afea677c686883` (tree `b1ee5a7e…` identical to head `6f0ca63`); PR CI on `6f0ca63` success (runs 42965139710, 42965173597 unittest 3.13/3.14; 42965173632 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 23 OK, MAEP 370 OK, HG 697 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr122-20261111` = `bfd6f65`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈3 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120, #122. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#122): low — the model server is the owner's verified loopback Ollama; the defects need it to answer malformed bytes. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 19. Addendum 2026-11-11 13:18–13:40 +07 (hourly run, cloud only, phone offline) — WS-04 trust-root transport oracle (#124)

FACT: `maep/tests/test_trust_root_transport_oracle.py` drives the production trust-root reader (`canonical_source.urllib_get` through `_get_json`) against a real loopback HTTP server serving exact bytes. Controls: canonical body with and without Content-Length, body exactly at the limit, 404 denies.

FACT (defects, reproduced before the fix): (1) a 301/302/303/307/308 from the API URL was followed to another host, which received `Authorization: Bearer <token>`, and its body was accepted as the trust-root response (5 failing subcases; token forwarding shown with a fake token); (2) an endless body was read until the process was killed; (3) the 10 s timeout is per socket read, so a slow drip had no total bound. Fix in `maep/authority/canonical_source.py`: `HTTP_MAX_BODY` 16 MiB (Content-Length or while reading), `HTTP_DEADLINE_S` 30 s over the whole response, redirects never followed (3xx returned as status → denied). This closes the "Not covered" item of §18.

FACT: PR #124 squash-merged as `4efb2d036803972c0f81fd2452f9d2e2727da056` (tree `60a381be…` identical to head `5bf3696`); PR CI on `5bf3696` success (runs 42972338718, 42972365652 unittest 3.13/3.14; 42972365662 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 9 OK, MAEP 379 OK, HG 697 OK (skip 3), hooks OK, selfcheck 0, bench 0; `python -m hg authority-check` (live read of `main`) exit 0 through the new reader. Recovery branch `recovery/main-pre-pr124-20261111` = `8d90280`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈4 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120, #122, #124. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#124): low — the URL is a constant on `api.github.com`; exploitation needs GitHub (or the network path) to answer with a redirect, an oversized or a dripping response. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 20. Addendum 2026-11-11 14:14–14:30 +07 (hourly run, cloud only, phone offline) — WS-04 harness read-back oracle (#126)

FACT: `hg/tests/test_harness_readback_oracle.py` gives the CI gates' own verifiers (regression case verifier used by `hg bench`, the `hg selfcheck` read-back, the bench recovery check, `hg/tests/support.content_verifier`) files with CRLF/CR, exact CR content, a symlinked file, a symlinked parent, a FIFO, a longer file and a missing file, each within 5 s; and `load_cases` a case file repeating a key. Controls: exact content matches; the shipped case file loads.

FACT (defects, reproduced before the fix with `read_back` present and the old verifiers unchanged: 17 failing subcases): (1) `read_text()` turned CRLF/CR into LF, so a file differing from the expectation only in line endings matched (false accept) and exact CR content did not (false reject); (2) symlinks (final component or parent) were read through; (3) `load_cases` read a repeated key last-value-wins. Fix: `hg/verification/regressions.read_back()` (exact UTF-8 bytes via `read_regular_file`, no symlink in parents, bounded); all four harness verifiers use it; `load_cases` refuses repeated keys, non-UTF-8 and a non-list document. This closes the "Not covered" item of §17. Harness only: no runtime path change, so nothing to deploy.

FACT: PR #126 squash-merged as `06eae2c539e39b613ad0d19773839d26d6924898` (tree `fcd3d2c1…` identical to head `5153e88`); PR CI on `5153e88` success (runs 42978652769, 42978673709 unittest 3.13/3.14; 42978673707 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 10 OK, MAEP 379 OK, HG 707 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr126-20261111` = `66a00ce`.

Deploy: unchanged — BLOCKED_EXTERNAL_ACTION, Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈5 h before this run. Undeployed merged runtime changes: #116, #118, #120, #122, #124. Production stays `4eaac81` (release `030a88d5`, §15).

## 21. Addendum 2026-11-11 15:13–15:35 +07 (hourly run, cloud only, phone offline) — WS-04 verifier verdict oracle (#128)

FACT: `hg/tests/test_verifier_verdict_oracle.py` gives `IndependentVerifier` a pinned stand-in worker that prints exact bytes and exits with a chosen code; each ambiguous or unbound answer must not be PASS and must return within 5 s (floods within 3 s). Controls: canonical PASS for both operations, PASS with `expected_sha256`, FAIL stays FAIL, the real pinned worker still passes a valid candidate.

FACT (defects, reproduced before the fix: 20 failing subcases + 1 error): (1) repeated `status`/`check`/`sha256`/nested keys read last-value-wins (`"status":"FAIL",…,"status":"PASS"` → PASS); (2) a PASS naming another check, or without a 64-hex lowercase `sha256` or a non-negative integer `bytes`, was accepted; (3) `NaN`/`Infinity`/`-Infinity` and non-UTF-8 bytes (`errors="replace"`) accepted; (4) a list `status` raised `TypeError`; (5) `subprocess.run` buffered stdout until the worker exited and stderr had no bound (a stderr flood still returned PASS). Already refused: BOM, a second JSON document. Fix in `hg/verification/independent.py`: `_read_answer` (strict UTF-8, one object, no repeated key, no non-standard numbers), `_pass_problem` (PASS must name the requested check and carry digest and size, else INCONCLUSIVE), `_run_bounded` (stdout+stderr ≤ `max_output_bytes`, overall deadline, worker killed past either). The TOCTOU test swaps the worker at `Popen`, the new exec point; its assertion is unchanged.

FACT: PR #128 squash-merged as `495271dd68f000aac08d3224454a29e5c4b92a4b` (tree `34a10970…` identical to head `6fc42be`); PR CI on `6fc42be` success (runs 42986136282, 42986163079 unittest 3.13/3.14; 42986163148 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 5 OK, MAEP 379 OK, HG 712 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr128-20261111` = `65c56a0`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈6 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120, #122, #124, #128. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#128): low — the worker is HG's own pinned code and never emits these answers; the fix is defence in depth on the verdict channel plus a memory/time bound. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 22. Addendum 2026-11-11 16:12–16:30 +07 (hourly run, cloud only, phone offline) — WS-04 model plan read oracle (#130)

FACT: `hg/tests/test_model_plan_oracle.py` feeds exact text from a scripted provider through `ModelPlanner`, `execute_goal` (fixture grants), `StructuredGoalPlanner`, `proposals_from_model` and `strict_json`; each ambiguous or unwritable plan must be `PlanRejected` (or 400 `invalid_json`) within 5 s, and through `execute_goal` end ASSESSED with PLAN_REJECTED evidence and no file written. Controls: canonical plan, exact CR and non-ASCII content, a paired surrogate escape, a clean revision accepted after a rejection, a clean plan closing CLOSED_VERIFIED.

FACT (defects, reproduced before the fix: 16 failures + 8 errors): (1) repeated keys read last-value-wins in a model plan (an `fs.read` step with a repeated `"tool":"fs.write"` became a write; repeated `steps` and params likewise); (2) `NaN`/`-Infinity` accepted; (3) a lone surrogate escape in `content` was accepted and `execute_goal` crashed with a raw `UnicodeEncodeError` at the ledger write (`record_plan`; task left ASSESSED, nothing written, no evidence); (4) NUL in a path, a lone surrogate in a path or an invalid URL port raised raw `ValueError`/`UnicodeEncodeError` instead of `PlanRejected` (recorded PLANNER_UNAVAILABLE, no feedback to the model; `StructuredGoalPlanner` too); (5) `proposals_from_model` read repeated keys, NaN and lone surrogates; (6) `strict_json` accepted a lone surrogate, so `/v1/tasks` answered 500 `internal_error` (at `canonical_json`, before the idempotency ledger) instead of 400. Fix: `hg/brain/providers.parse_model_json` (no repeated key, no non-standard number, valid Unicode text) used by `ModelPlanner` and `proposals_from_model`; adapter `validate_params` refuses str params UTF-8 cannot encode; rooted paths refuse NUL; `url.read` maps an invalid URL/port to `AdapterInputError`; `strict_json` refuses lone surrogates. Not covered: `TaskStore.submit_task` with a lone surrogate in a task field still raises a raw `UnicodeEncodeError` at the ledger write (fail closed: nothing written, no task created).

FACT: PR #130 squash-merged as `6de6111f5434aeeac556510cdffdc664db3cf220` (tree `a427d804…` identical to head `a16e0c0`); PR CI on `a16e0c0` success (runs 42994165970, 42994210230 unittest 3.13/3.14; 42994210234 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 10 OK, MAEP 379 OK, HG 722 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr130-20261111` = `cd3e79a`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈7 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120, #122, #124, #128, #130. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#130): low — `ModelPlanner` is not wired in production (no live model); on the running `/v1/tasks` a lone surrogate is answered 500 instead of 400, before any effect or idempotency record. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 23. Addendum 2026-11-11 17:12–17:35 +07 (hourly run, cloud only, phone offline) — WS-04 ledger event encoding oracle (#132)

FACT: `maep/tests/test_ledger_event_encoding_oracle.py` appends events through `append_event`, `append_generated` and `TaskStore` (`create_task`, `record_blocker`) carrying a lone surrogate (value, nested value, key) or `NaN`/`Infinity`/`-Infinity`; each must be refused with no byte written, and `TaskStore` must report `MAEPError` "state unchanged" (never `LedgerOutcomeUnknown`, never a raw exception) and stay usable. Controls: non-ASCII, CRLF, an astral character and a finite float append and read back unchanged.

FACT (defects, reproduced before the fix: 13 failures + 9 errors): (1) a lone surrogate raised a raw `UnicodeEncodeError` from `_append_unlocked` inside the ledger lock (nothing written — the encode precedes the write — but the caller got no `MAEPError`); (2) `NaN`/`Infinity` were written to the ledger as non-standard tokens (`{"event_id":"E1","v":NaN}`), and `TaskStore.create_task` accepted a task carrying one. Fix in `maep/ledger.py`: `_encode_event` (`allow_nan=False`, UTF-8) computed before the lock and the write; `append_event` refuses with `LedgerAppendRefused`, `append_generated` with `MAEPError`. This closes the "Not covered" item of §22.

FACT: PR #132 squash-merged as `dde3b8b532868d261fa9b1d8083a2e04c8a04a28` (tree `93d513bf…` identical to head `0a2a3d2`); PR CI on `0a2a3d2` success (runs 43002415557, 43002440915 unittest 3.13/3.14; 43002440888 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 6 OK, MAEP 385 OK, HG 722 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr132-20261111` = `bd71030`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈8 h before this run. Nothing was run on the phone. Undeployed merged runtime changes: #116, #118, #120, #122, #124, #128, #130, #132. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#132): low — on the running service a NaN in a task field can reach the ledger as a non-standard token (the reader still accepts it); a lone surrogate is refused by `strict_json` only after #130. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 24. Addendum 2026-11-11 18:19–18:40 +07 (hourly run, cloud only, phone offline) — WS-04 CLI input read oracle (#134)

FACT: `hg/tests/test_cli_input_read_oracle.py` gives `hg bench --baseline` (`load_baseline`, `verdict`, and the CLI in a subprocess), `hg eval --set` (`evaluate.run` with a recording router factory, `load_spec`) and `hg repair` (`inspect` on a notes ledger) owner-supplied files that are ambiguous or unusable. Controls: a numeric baseline with a null metric passes, a higher baseline reports the regression, the shipped `eval_vi.json` loads, a garbage line is listed.

FACT (defects, reproduced before the fix with the code unchanged): (1) baseline `{"pass_rate":2.0,"pass_rate":0.5}`, `NaN` and `true` gave no problem (NaN hides every regression); `"1"` and `[]` raised `TypeError` — through the CLI only after the whole benchmark ran, as a traceback; (2) eval file with a repeated threshold key was accepted (reached scoring), non-UTF-8 raised raw `UnicodeDecodeError`; (3) `hg repair` reported `bad_lines: []` for a line with a repeated key, non-UTF-8 bytes (decoded with `errors="replace"`) or a duplicate `event_id`, all refused by the ledger reader. Fix: `benchmark.load_baseline` (via `parse_model_json`; `metrics` object; numbers or null) checked before the benchmark, `baseline unusable` exit 1; `evaluate.load_spec`, checked by the CLI before the model (`EXIT_INPUT`); `repair._bad_lines` uses `maep.ledger._check_line` plus the EventLog kind/seq types.

FACT: PR #134 squash-merged as `1e800f4b928264a94c640b486d04d6b013a9db5b` (tree `a7058110…` identical to head `e61dda2`); PR CI on `e61dda2` success (runs 43011854700, 43011890521 unittest 3.13/3.14; 43011890591 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 8 OK, MAEP 385 OK, HG 730 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0, `hg bench --baseline <own report>` 0. Recovery branch `recovery/main-pre-pr134-20261111` = `1ed162a`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈9 h before this run. Nothing was run on the phone. #134 changes the owner's CLI (`hg bench`, `hg eval`, `hg repair`), not the `hg-runtime` service; it reaches the phone with the next release. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#134): low — the files are the owner's own. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 25. Addendum 2026-11-11 19:16–19:35 +07 (hourly run, cloud only, phone offline) — WS-04 url.read redirect oracle (#136)

FACT: `hg/tests/test_url_read_transport_oracle.py` runs `url.read` tasks through the gateway against real loopback HTTP servers with task scope `http://127.0.0.1:P/docs/`; a redirect (301/302/303/307/308 to an out-of-scope path, 302/307 to another host, 301 to an in-scope path) must end as a known failure, with no request reaching the redirect target and the target body in no outcome or ledger event. Controls: an in-scope 200 closes CLOSED_VERIFIED; a 404 stays BLOCKED.

FACT (defect, reproduced before the fix with the code unchanged: 8 failing subcases): `UrlReadAdapter` used `urllib.request.urlopen`, which follows redirects. The gateway authorized and scope-checked only the requested URL; a 302 from `/docs/go` to `/secret` made the adapter request `/secret` and return its body as `observed.text` under `url = …/docs/go`, and the task closed CLOSED_VERIFIED (another host likewise). Fix in `hg/tools/code.py`: an opener whose redirect handler declines, so a 3xx is `HTTPError` → `AdapterFailure("HTTP 3xx")` (same pattern as `providers._NoRedirect` and #124).

FACT: PR #136 squash-merged as `aea638b6e4569262a5fc49925c5cb929da59ff5b` (tree `f1a0a7e6…` identical to head `811fbd4`); PR CI on `811fbd4` success (runs 43019792815, 43019826368 unittest 3.13/3.14; 43019826371 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 5 OK, MAEP 385 OK, HG 735 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr136-20261111` = `e1a7ea5`. The feature branch could not be deleted from the session (push refused); it is merged and unreferenced.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈10 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#136): low in production — no live model plans `url.read` there and no manifest grant lists a `url:` scope; with such a grant, a redirecting in-scope server could make HG read an unauthorized URL. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 26. Addendum 2026-11-11 20:17–20:35 +07 (hourly run, cloud only, phone offline) — WS-04 test.run output oracle (#138)

FACT: `hg/tests/test_test_run_output_oracle.py` runs real `test.run` tasks through the gateway (fixture grants) on test directories whose code shapes the output channel: non-UTF-8 bytes on stdout/stderr, summary-like lines (`Ran 999 tests in …`, `FAILED (failures=7, errors=3)`) on either stream, a 24 MB stdout flood (traced memory peak < 8 MB), a background child left running (run must close within 6 s and the child must not outlive it), a timed-out run with a grandchild, and stdin. Controls: plain pass closes, UTF-8 non-ASCII output, a failing run reports `(False, 1, 1, 0)` and does not close, zero tests is `ok=False, tests_run=0`.

FACT (defects, reproduced before the fix with the code unchanged: 7 failing subcases): (1) `subprocess.run(text=True)` raised `UnicodeDecodeError` on non-UTF-8 output, so a finished run became UNKNOWN; `test.run` cannot reconcile, so the task went BLOCKED with a pending action blocking further effects; (2) counts were the first match in `stderr + stdout` (passing run reported `(999, 7, 3)` / `(1, 7, 3)`); (3) the whole output was buffered (≈75 MB traced for a 24 MB flood); (4) a background child holding the pipes kept the run open until the timeout (UNKNOWN, BLOCKED); (5) on timeout only the direct child was killed and a grandchild outlived the run. Fix in `hg/tools/code.py` (`test.run` 1.1): `_run_streamed` (own process group, `/dev/null` stdin, streams hashed in full with the last 64 KiB kept, group killed after the main process exits and its output is drained, and at the deadline) and `_summary` (last `Ran N tests` line on stderr and the result line after it, including `NO TESTS RAN`). `output_sha256` (no consumer) replaced by `stdout_sha256`/`stderr_sha256` and byte counts.

FACT: PR #138 squash-merged as `b95f8fd7dc380e6d95f630cf18acfc9a3f39352b` (tree `9d660455…` identical to head `85c3547`); PR CI on `85c3547` success (runs 43028877825, 43028924958 unittest 3.13/3.14; 43028924996 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 10 OK, MAEP 385 OK, HG 745 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr138-20261111` = `c609a5d`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈11 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#138): low in production — no live model plans `test.run` there; with such a plan, test code could jam the runtime with non-UTF-8 output or a background child. UNVERIFIED: process-group kill on Android/Termux (Linux only so far); verified at the next deploy smoke. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 27. Addendum 2026-11-11 21:16–21:40 +07 (hourly run, cloud only, phone offline) — WS-04 fs.read content oracle (#140)

FACT: `hg/tests/test_fs_read_content_oracle.py` runs real `fs.read` tasks through BrainOrchestrator → ActionGateway → adapter (fixture grants) on files that are not valid UTF-8 (invalid byte, truncated multibyte sequence, encoded surrogate, overlong encoding, Latin-1) or larger than the adapter bound (one byte over; a 24 MB sparse file with traced memory peak < 8 MB). Each must not succeed, and no outcome may carry U+FFFD text. Controls: UTF-8 non-ASCII, CRLF/CR, a BOM, an empty file and a file of exactly the bound are returned byte-exact and close CLOSED_VERIFIED.

FACT (defects, reproduced before the fix with the code unchanged: 7 failing subcases): (1) `fs.read` decoded with `errors="replace"`, so a non-UTF-8 file closed CLOSED_VERIFIED with U+FFFD text under the `sha256` of the original bytes (the text consumers and research documents see was not the file); (2) no size bound: any file was read whole into memory. `verify()` returned `True` unconditionally. Fix in `hg/tools/gateway.py` (`fs.read` 1.1): `read_regular_file(full, MAX_BYTES)` with `MAX_BYTES = 2_000_000` (fstat and during the read) → `AdapterFailure`; strict UTF-8 → `AdapterFailure("file is not UTF-8 text (byte N)")`; `verify()` checks `content` against `bytes` and `sha256`. Test note: the truncated-sequence case first used valid UTF-8 (`"xin chào"[:-1]`, a test error); corrected to `"xin chà"` bytes minus one, which fails on the unchanged adapter and passes after the fix.

FACT: PR #140 squash-merged as `b95565cf8c24d5f1a0d2ca524599ea69645f3d4e` (tree `750a24e5…` identical to head `baa98ec`); PR CI on `baa98ec` success (runs 43037746914, 43037791615 unittest 3.13/3.14; 43037791178 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 12 OK, MAEP 385 OK, HG 757 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr140-20261111` = `1ab6615`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈12 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138, #140. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#140): low–medium — `fs.read` is exposed by the running HTTP service (token, loopback): a non-UTF-8 file under the state root is answered as replaced text and closes CLOSED_VERIFIED; a large file is read whole into the phone's memory. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 28. Addendum 2026-11-11 22:15–22:40 +07 (hourly run, cloud only, phone offline) — WS-04 url.read content oracle (#142)

FACT: `hg/tests/test_url_read_content_oracle.py` runs real `url.read` tasks through BrainOrchestrator → ActionGateway → adapter (fixture grants) against a loopback server writing exact bytes: text bodies that are not valid UTF-8, declared `iso-8859-1`/`windows-1252`/`utf-16` charsets, a body shorter than its `Content-Length`, a broken chunked body, a body one byte over the 2 MB bound (traced memory peak < 8 MB) and one cut inside a character, and a dripping body (adapter `timeout_s` patched to 4). Each must not close CLOSED_VERIFIED, must carry no U+FFFD and no text, and must end as a known failure (`FAILED`, never UNKNOWN); the drip's server writes must stop within 3 s. Controls: UTF-8 non-ASCII, CRLF, an empty body, a body of exactly the bound, a chunked body, `Text/Plain; Charset="UTF-8"` and a binary body close CLOSED_VERIFIED byte-exact.

FACT (defects, reproduced before the fix with the code unchanged: 10 failing subcases + 1 error): (1) `data.decode("utf-8", errors="replace")` returned non-UTF-8 bodies and declared non-UTF-8 charsets as replaced text under the `sha256` of the original bytes, and the task closed CLOSED_VERIFIED; (2) `response.read(n)` returns a short body silently, so a body shorter than `Content-Length` closed as the document; (3) an over-bound body closed with its prefix (`truncated: true`); (4) the media type was matched case-sensitively, so `Text/Plain` returned no text. With the tightened assertion (known failure), (5) a broken chunked body (`IncompleteRead`) and (6) a dripping body ended UNKNOWN, and the adapter thread read on after the gateway timeout. Fix in `hg/tools/code.py` (`url.read` 1.1): chunked `read1` under an overall deadline inside the gateway budget (per-read timeout ≤ 5 s); over-bound, short and broken bodies, socket timeouts and `HTTPException` → `AdapterFailure`; `_media_type` parses type and charset case-insensitively; strict UTF-8 (us-ascii as ASCII), other charsets refused; `verify()` checks `text` against `bytes` and `sha256`. `truncated` stays in the outcome, always `false`.

FACT: PR #142 squash-merged as `782343dee46fdce6938e0c9d1923a2afce7e8ad4` (tree `631dd6fb…` identical to head `ff8a061`); PR CI on `ff8a061` success (runs 43047784836 push, 43047833808 MAEP tests unittest 3.13/3.14; 43047835337 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 12 OK (+ transport oracle 5 OK), MAEP 385 OK, HG 769 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr142-20261111` = `4fa0e15`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈13 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138, #140, #142. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#142): low in production — `url.read` is not exposed over HTTP in V1, no live model plans it and no manifest grant lists a `url:` scope. UNVERIFIED: the deadline and socket close on Android/Termux (Linux only so far). Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 29. Addendum 2026-11-11 23:14–23:35 +07 (hourly run, cloud only, phone offline) — WS-04 code tools content oracle (#144)

FACT: `hg/tests/test_code_tools_content_oracle.py` runs real `code.diff`, `code.search` and `code.symbols` tasks through BrainOrchestrator → ActionGateway → adapter (fixture grants). `identical` must mean exact text equality; search line numbers must count only LF/CRLF/CR (as Python, editors and `grep -n`); every file a walk did not read must be listed in `files_skipped` with a reason (no content, no link target); a single unreadable start file must be a known failure (`FAILED`, never UNKNOWN); a pattern with a line break is refused; a file too deep to parse is a `syntax_errors` entry. Controls: an exact copy (LF, CRLF, no final newline, empty, non-ASCII) diffs identical; ordinary searches and symbol indexes are unchanged; 90 nested classes are indexed.

FACT (defects, reproduced before the fix with the code unchanged: 22 failures + 12 errors): (1) `code.diff` compared `str.splitlines()` without terminators, so a missing/extra final newline, CRLF or CR against LF, and a form feed against a newline reported `identical: true` and closed CLOSED_VERIFIED; a diff over 2000 lines was cut without a flag; (2) `code.search` split on VT/FF/FS/GS/RS/NEL/U+2028/U+2029, so match line numbers were wrong; unread files vanished silently, so "no match" could mean "not read"; a non-UTF-8 single start file closed as an empty search; (3) `code.symbols`: `x = -…-1` (6000) raised `MemoryError` from the parser and a 200 000-term sum `RecursionError`, both UNKNOWN → task BLOCKED; a 1500-deep expression that parses hit `RecursionError` in the recursive symbol walk. Fix in `hg/tools/code.py` (`code.search`/`code.symbols`/`code.diff` 1.1): `_lines` (LF/CRLF/CR), `_read_file` (text or reason), `_scan` (`files_skipped`, single start file → `AdapterFailure`), pattern CR/LF → `AdapterInputError`, parse depth errors → `syntax_errors`, iterative pre-order walk, diff on lines with terminators, `identical = current == against`, `truncated`, `code.diff` verify checks `identical` against the counts.

FACT: PR #144 squash-merged as `99072e9b66c751aa9119a33126bc26c3084e5cea` (tree `8e6fcca6…` identical to head `6296a28`); PR CI on `6296a28` success (runs 43058108394, 43058149780 unittest 3.13/3.14; 43058150714 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 24 OK, MAEP 385 OK, HG 793 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr144-20261111` = `3b944e5`. The feature branch could not be deleted from the session (push refused); it is merged and unreferenced.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈14 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138, #140, #142, #144. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#144): low in production — no live model plans code tools there; a planner or researcher relying on `code.diff`/`code.search` could be told "identical"/"no match" falsely, and a deep file could block a task. Unblock: next run with the phone responding prepares `deploy-<main>-20261111` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 30. Addendum 2026-11-12 00:13–00:35 +07 (hourly run, cloud only, phone offline) — WS-04 memory value oracle (#146)

FACT: `hg/tests/test_memory_value_oracle.py` writes records through `MemoryStore.remember` and reopens the ledger. A value JSON would change (tuple, nested tuple, `int`/`bool`/`None`/`float` key, set, NaN, bytes) must be refused before any byte is written, in PROJECT and WORKING; the same DECISION value given again with keys in another order, or after a reopen, must not be a `MemoryConflict`, and superseding with a reordered value gives version 2. Controls: values that really differ (`{"a":1}`/`{"a":2}`, an extra key, list order, `1`/`"1"`, `True`/`1`, `None`/value, `[1]`/`[1.5]`) still conflict with no bytes written; exact values (nested objects/lists, non-ASCII, `-0.0`, `10**30`, `-1e-300`, null) round-trip with the same type.

FACT (defects, reproduced before the fix with the code unchanged: 16 failing subcases + 1 error): (1) `_norm` compared values by `repr()` while the ledger stores JSON with sorted keys, so the same value given twice was refused as a contradiction (`{"b":2,"a":1}` twice → `MemoryConflict`); (2) `remember()` returned `(1, 2)` / `{1: "x"}` while a reopened store read `[1, 2]` / `{"1": "x"}`; WORKING memory accepted sets, NaN and bytes. Fix in `hg/memory/store.py`: `_canonical` (canonical JSON if a type-strict round trip gives the same value), `_validate` refuses an inexact value, `_norm` compares canonical JSON. Callers (`notes`, `learning`, `research`, `record_task_outcome`) pass exact values; full suites unchanged.

FACT: PR #146 squash-merged as `474f2f3272a2a15836b3f10ae9aaaf0bb24e0cd7` (tree `23c88cdd…` identical to head `b101ac3`); PR CI on `b101ac3` success (runs 43066978455, 43067010760 unittest 3.13/3.14; 43067010720 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 5 OK, MAEP 385 OK, HG 798 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr146-20261112` = `5cb1c6d`.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈15 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138, #140, #142, #144, #146. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#146): low — the owner's `hg note` path passes no value; a learning/runtime caller giving a reordered value would be refused as a conflict. Unblock: next run with the phone responding prepares `deploy-<main>-20261112` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 31. Addendum 2026-11-12 01:13–01:40 +07 (hourly run, cloud only, phone offline) — WS-04 fs.write effect oracle (#148)

FACT: `hg/tests/test_fs_write_effect_oracle.py` runs real `fs.write` tasks through BrainOrchestrator → ActionGateway → adapter (fixture grants). A write that cannot happen and changes nothing (the path is an existing directory, the scope directory itself, or has a parent — direct or deeper — that is a regular file) must be `FAILED` on every attempt with no pending action, the blocking file/directory unchanged and no `.hg-tmp-*` left; replacing an existing file must keep its mode (0755, 0644, 0600); the parent directory must be fsynced after the rename with the new bytes on disk. Controls: non-ASCII text in new nested directories, CRLF/CR, empty content and replacing a file close CLOSED_VERIFIED byte-exact.

FACT (defects, reproduced before the fix with the code unchanged: 7 failing tests): (1) a directory target or a non-directory parent raised `IsADirectoryError`/`FileExistsError` from `os.replace`/`mkdir` → `UNKNOWN`; the action stayed pending and blocked further effects although nothing was written; (2) `mkstemp` + `os.replace` gave a replaced file mode 0600 (a 0755 script lost its execute bit), an effect outside the plan; (3) SUCCEEDED was returned without fsyncing the parent directory after the rename. Fix in `hg/tools/gateway.py` (`fs.write` 1.1): `_inspect` (lstat only, before any effect) → `AdapterFailure`; `fchmod` of the temp file to the existing file's mode; `_fsync_directory` on the parent and the parent of each created directory (EINVAL accepted). Test note: the first draft asserted a single FAILED attempt and task state ≠ BLOCKED; the runtime retries a known failure and then blocks the task, so the assertion was corrected to "every attempt FAILED and no pending action" — the defect criterion (no UNKNOWN, nothing pending) is unchanged.

FACT: PR #148 squash-merged as `7cb4bb8cdb9c450fbead7864b066b02a5352f7b9` (tree `b4acb051…` identical to head `fca33e6`); PR CI on `fca33e6` success (runs 43076842759, 43076877010 unittest 3.13/3.14; 43076878363 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 12 OK, MAEP 385 OK, HG 810 OK (skip 3), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-pr148-20261112` = `c94260a`. UNVERIFIED: permission-denied cases (tests run as uid 0) and directory fsync on Android/Termux.

Deploy: BLOCKED_EXTERNAL_ACTION — Desktop Commander lists the phone (`19e2e2a5-…`) Offline, last seen ≈16 h before this run. Nothing was run on the phone. Undeployed merged changes: #116, #118, #120, #122, #124, #128, #130, #132, #134, #136, #138, #140, #142, #144, #146, #148. Production stays `4eaac81` (release `030a88d5`, §15). Risk while blocked (#148): low–medium — `fs.write` is exposed by the running HTTP service (token, loopback): a write to a directory path leaves a pending action that blocks the task's further effects, and replaced files become 0600. Unblock: next run with the phone responding prepares `deploy-<main>-20261112` from `deploy-4eaac81-20261110` with only `C`/`MAIN`/`TREE`/smoke tag changed.

## 32. Addendum 2026-11-12 01:50–03:10 +07 (owner-directed, phone online) — WS-04 fs.write permission (#150), code.symbols thread stack (#151); deploy candidate prepared, not executed

Owner instruction (2026-11-12): fix the fs.write permission defect the owner verified on Termux (UID 10460: a non-writable directory made `tempfile.mkstemp` raise PermissionError → UNKNOWN, pending action, task BLOCKED, no file created), run the suites as the real Termux UID, update this ledger, prepare a new deploy candidate (not the `7cb4bb8` one), do not switch the service or deploy, and stop at the production approval gate.

FACT (#150): `hg/tests/test_fs_write_permission_oracle.py` (9 tests: 3 need a non-root UID; 6 fault-injection) runs `fs.write` through BrainOrchestrator → ActionGateway → adapter. Permission denied on an existing directory and on creating a parent directory must be `FAILED` on every attempt (≥ 2 attempts reach the adapter), no pending action, no ACTION_REFUSED "unreconciled", no target, no `.hg-tmp-*`, no directory left; a temp-file write failure and a rename that did not happen likewise. Guards: an error after the rename (rename done, or directory fsync) and a failure whose cleanup fails stay `UNKNOWN` until `reconcile()` (APPLIED / NOT_APPLIED). Before the fix: Linux `nobody` 5 failing; Termux UID 10460 (`7cb4bb8` gateway, test from `d2cfd63`) 5 failing, every one `['UNKNOWN']`/not FAILED — the owner's defect reproduced. Fix in `hg/tools/gateway.py` (`fs.write` 1.2): parents created one by one (a missing adapter root too) and tracked; any OSError before the rename, or a failed rename whose temp file still exists, removes the temp file and the created empty directories and raises `AdapterFailure`; if that cleanup fails, the temp name is gone after a failed rename, or the error is after the rename, the original error is re-raised (UNKNOWN). Advisory review by a separate Claude agent (not independent, MAEP-021): nothing blocking; it found the cleanup-failure branch untested — test added (`914e2ea`). Residual minor points recorded, not fixed: a syscall that creates an entry and still returns an error leaves residue but no target change; reconcile() inspects only the target, so leftover residue after an UNKNOWN cleanup is not recorded.

FACT (#151, found while running the Termux suites): the HG suite on Termux died with exit 139 in `test_code_tools_content_oracle` (from #144). Probe on the phone (Python 3.14.8, subprocess per case): `ast.parse` of a 5000-term sum is SIGSEGV on a worker thread with the default stack, PARSED on the main thread and on a 16 MiB thread; 20k/200k terms RecursionError on main/16 MiB, SIGSEGV on a default worker. The gateway runs adapters on worker threads, so a `.py` file in scope could kill `hg serve`. Freeing a 1500-deep tree on a small stack crashed too. Fix in `hg/tools/code.py` (`code.symbols` 1.2): `_on_parse_stack` parses, walks and frees the tree on a thread created with `threading.stack_size(16 MiB)`; `_index_python` returns plain data. `hg/tests/test_code_symbols_thread_stack_oracle.py` reruns the code.symbols oracle in a child with 256/512 KiB thread stacks: before exit -11 (both), after OK; a 5000-term case added to the content oracle.

FACT (merge): PR #150 squash-merged as `49234bd2d319ce4a1899e6669786aa4db1b2f828` (tree `58a0b8ca…` = head `914e2ea`; CI on `914e2ea` success: runs 43086225553, 43086236133 unittest 3.13/3.14; 43086236084 rt06-anchor 3.13/3.14). PR #151 (main merged in, head `bd1ea3e`) squash-merged as `9c829acd81e3c6c05cf1b565848cf943e6b32f0f` (tree `b43cf80f…` = head `bd1ea3e`; CI on `bd1ea3e` success: runs 43090242230, 43090252878 unittest 3.13/3.14; 43090252752 rt06-anchor 3.13/3.14). Recovery branches: `recovery/main-pre-ws04-permission-20261112` = `6237231`, `recovery/main-pre-pr151-20261112` = `49234bd`.

FACT (tests on tree `b43cf80`): Linux Python 3.13.18 uid 0: MAEP 385 OK, HG 821 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Linux `nobody` (on `d2cfd63`): MAEP OK (skip 1), HG 818 OK. Termux UID 10460, Python 3.14.8, fresh clone `~/hg-ws04-verify/bd1ea3e…/repo` (0 dirty; `~/HG` and its uncommitted changes not touched): MAEP 385 OK (skip 3), HG 821 OK (skip 3), hooks 32 OK, `hg selfcheck` PASS, `hg bench` exit 0; `SHA256SUMS` there: hg.log `ab16acb3…`, maep.log `160fe4a6…`.

Deploy: NOT_EXECUTED — owner instruction; production stays release `030a88d5` (`4eaac81`), service not switched. The `deploy-7cb4bb8-20261112` script was never run and is superseded. A new candidate for runtime commit `9c829ac` / tree `b43cf80` is prepared after this addendum merges (its MAIN is this addendum's merge commit, which the script checks at run time) and waits for the owner's separate production approval. WS-04 stays IN_PROGRESS (research synthesis surface open; deploy pending).

## 33. Addendum 2026-11-12 05:10–05:50 +07 (hourly run, cloud only) — WS-04 research synthesis (#153), JSON depth bound (#154); deploy not executed

FACT (#154): `hg/tests/test_json_depth_bound.py` (11 tests). `json.loads`/`json.dumps` recurse in C per nesting level; on Termux Python 3.14 a 20 000-level array parsed on a worker thread is SIGSEGV (§32 probe class, same root cause as #151), and `hg serve` parses request bodies (after the token check) and local-model replies on worker threads. Before the fix (code unchanged, scanner present but not wired): 6 failures — `json.loads` called on 20 000/2000/65-level input by `strict_json`, `parse_json`, `parse_model_json`; a live `HGHTTPServer` answered `400 invalid_request` to a 2000-level body, i.e. parsed it in full. Fix: `hg/json_depth.py` (iterative regex scan, string literals skipped, str and bytes, ~0.01–0.03 s per MiB); `strict_json` → 400 `invalid_json` (contract code unchanged), providers → `ValueError` (already `INVALID_RESPONSE`) for > 64 levels, before `json.loads`. PR #154 squash-merged as `540e86c94d0910c786352acd7c28a12f9eb371c1` (CI on `f997291` success: runs 43112006520, 43112032554 unittest 3.13/3.14; 43112032561 rt06-anchor 3.13/3.14). Recovery `recovery/main-pre-json-depth-20261112` = `ad596e3`. UNVERIFIED: on-device Termux reproduction (a device command was refused by this session's permission classifier; nothing ran on the phone).

FACT (#153, opened by an earlier hourly session): research synthesis oracle `hg/tests/test_research_synthesis_oracle.py` (17 tests; 11 failures + 2 errors before, per the PR). Its CI runs, created 2026-11-11 20:19 UTC, stayed with 0 jobs (cancel: 409 "not queued yet"; rerun: 403 "already running"); the branch was updated from main (merge commit `3700d17`, not an empty commit), CI then ran green (runs 43113128151, 43113136908 unittest 3.13/3.14; 43113136907 rt06-anchor). Local on the identical tree `9a618b1a…` (Linux, Python 3.13.18, uid 0): MAEP 385 OK, HG 849 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Squash-merged as `c0cccffa2481d957d3bf8563f66545cf1ae35670`. Production impact: none — `Researcher` has no runtime/HTTP caller. Recovery `recovery/main-pre-research-20261112` = `ad596e3`.

Deploy: NOT_EXECUTED — the candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval; #154 is runtime-relevant (`hg serve` request bodies) and should join a refreshed candidate built from main. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 34. Addendum 2026-11-12 06:00–06:30 +07 (hourly run, cloud only) — WS-04 summarize line anchors (#156); deploy not executed

FACT: `hg/tests/test_summarize_line_anchor_oracle.py` counts lines independently from the raw bytes (LF, CRLF, CR only, as editors, `less -N` and `grep -n`) and checks `hg summarize`: every extractive sentence is quoted from the line it names; a model sentence citing the real line is ANCHORED and one citing past the real last line is BADCITE; the model is shown the real line numbers. Cases: VT, FF, FS, GS, RS, NEL, U+2028, U+2029 inside a line, each with LF/CRLF/CR endings. Controls: LF, CRLF, CR, mixed endings without a final newline.

FACT (defect, reproduced before the fix with the code unchanged: 24 failing subcases, controls passing): `summarize.py` numbered lines with `str.splitlines()`, which also splits on those eight characters, so every anchor after one of them was shifted (an extractive sentence was labelled with a blank line; model citations were checked against the wrong text). Fix: `source_lines()` (LF/CRLF/CR, same rule as `code.search` since #144) in `sentences_with_lines` and `with_model`. Test note: the first draft put the model's citation after the sentence's own period (`… Việt. [L4].`), which makes the citation a separate sentence; corrected to the prompt's form (`… Việt [L4].`) before the defect run.

FACT: PR #156 squash-merged as `96feb7ed3ad27b5e115767a79fbe118c3ffaa467` (tree `6ea601ec…` identical to head `04d0fa8`); PR CI on `04d0fa8` success (runs 43118808904, 43118832890 unittest 3.13/3.14; 43118832888 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 2 tests OK, MAEP 385 OK, HG 851 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-summarize-anchor-20261112` = `fc78469`.

DISCOVERED (not fixed, no runtime caller): `hg/verification/bounded.py` `extract_log_window` labels excerpt lines `[L#]` and `line_ranges` from `str.splitlines()` (same shift) after decoding with `errors="replace"`. Fix when a caller is added.

Deploy: NOT_APPLICABLE for #156 (owner CLI assistant layer, not `hg serve`; reaches the phone with the next release). The candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval and should be refreshed from main to include #154. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 35. Addendum 2026-11-12 07:13–07:45 +07 (hourly run, cloud only) — WS-04 grounding number identity (#158); deploy not executed

FACT: `hg/tests/test_grounding_number_identity_oracle.py` states independently which written numbers denote the same value and checks the labels through `grounding.check_sentence` with the question (`hg ask`), `check.check` over a real Notebook (`hg check`, no question) and `evaluate.key_present` (`hg eval`). A different value must never be NOTE/KHỚP (CONFLICT when close): decimal vs integer (`0,5`/`0.5`/`2,5` vs `5`/`25`), day/month order (`5/9` vs `9/5`, `05/09/2026` vs `2026-05-09`), time order (`8:05` vs `5:08`), identifier leading zero (`0912345678`, `0420`), a part of a time (`5 giờ` vs `15:05`). Controls stay NOTE: DMY vs ISO, `5/9` inside `05/09/2026`, `08:05`/`8:05`, `8 giờ 30`/`8:30`, `8 giờ`/`8:00`, `0,5`/`0.5`, thousands grouping, `05`/`5`.

FACT (defect, reproduced before the fix with the code unchanged: 29 failing subcases — 23 false accepts, 6 same-value controls labelled MODEL): `textvi.numbers()` reduced numbers to unordered integer atoms with leading zeros dropped and `compare()` checked set inclusion, so e.g. "Uống 5 viên" was NOTE against a note saying "0,5 viên" and "9/5" against "5/9"; `new_information_gap` compared digit tokens as words. Fix: canonical values in `numbers()`, `number_gap()` (claimed day/month found in a full date; `parts=True` only for eval keys authored as atoms), digits excluded from the word-level new-information check, a note time satisfies the units giờ/phút.

FACT: PR #158 squash-merged as `65cd6030dad0b760caa20e80c79b9428c711f64d` (tree `a39a9a71…` identical to head `ef73c87`); PR CI on `ef73c87` success (runs 43127840735, 43127873260 unittest 3.13/3.14; 43127873350 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 7 OK, MAEP 385 OK, HG 858 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-number-identity-20261112` = `796ca07`.

LIMIT (unchanged, stated): a plain integer in a sentence is still accepted when the note contains that integer anywhere ("phòng 5" against a note with "phòng 15, tầng 5"); the check stays lexical, not semantic.

Deploy: NOT_EXECUTED. #158 changes `hg.assistant.ask`, which `hg serve` chat uses, so it is runtime-relevant and should join a refreshed candidate built from main together with #154; the candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 36. Addendum 2026-11-12 08:17–08:45 +07 (hourly run, cloud only) — WS-04 guard invisible characters (#160); deploy not executed

FACT: `hg/tests/test_guard_invisible_oracle.py` (9 tests) first shows each injection is quarantined as written, then inserts one character after every letter and checks the quarantine through `ask.select_notes` (real Notebook: the note must be quarantined, never usable), `check.check` (never the cited note; text flagged) and `summarize.with_model` (DirectiveInput before any router use). Characters: Default_Ignorable_Code_Point with canonical combining class 0 (CGJ U+034F, VS U+FE00/U+FE0F/U+E0100, Mongolian FVS U+180B, Khmer U+17B4/U+17B5) and blank fillers (Hangul U+115F/U+1160/U+3164/U+FFA0, braille blank U+2800); the 15 held-out injections of `test_assistant_guard` with each zero-width mark; a filler used as a word separator. Controls: the ordinary-note set, emoji with VS16 and ZWJ, the ordinary notes in NFD.

FACT (defect, reproduced before the fix with the code unchanged: 184 failing subcases, controls passing): `guard.normalise` dropped only `Cf` and relied on `textvi.fold`, which drops marks with ccc > 0, so those characters split every word for the regexes; `hg ask` (and `hg serve` chat through `hg.assistant.ask`) returned such a note as usable for a model request, `hg check` could cite it, `hg summarize --model` sent the text. Fix in `hg/assistant/guard.py`: drop those characters; single letters separated only by fillers are joined; a filler before punctuation is dropped; any other filler is a space. Unused `_DROP` constant removed.

FACT: PR #160 squash-merged as `22cf1622ca9d05de7f301aac9592f03f8a278d1b` (tree `d4d8e1ee…` identical to head `4666002`); PR CI on `4666002` success (runs 43134662043, 43134687740 unittest 3.13/3.14; 43134687540 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 9 OK, MAEP 385 OK, HG 867 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-guard-invisible-20261112` = `0d773ea`.

LIMIT (unchanged, stated): the guard is best-effort defence in depth; letter-spacing with ordinary spaces for words shorter than 4 letters ("y o u") is still not joined; stored note text is unchanged (VS16 stays in emoji).

Deploy: NOT_EXECUTED. #160 changes `hg.assistant.guard`, used by `hg serve` chat, so it is runtime-relevant and should join a refreshed candidate built from main together with #154 and #158; the candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 37. Addendum 2026-11-12 09:12–09:35 +07 (hourly run, cloud only) — WS-04 operator workdir read (#162); deploy not executed

FACT: `hg/tests/test_operator_read_workdir_oracle.py` (7 tests) builds a real runtime with failures, then points `health`, `hg health`, `hg status` and `hg learn` at a path that holds no runtime (missing, a regular file, a dangling symlink, a path under a regular file) and at copies whose `tasks.jsonl`/`actions.jsonl` (all three commands) or `memory.jsonl`/`models.jsonl` (health) is a dangling symlink or a symlink loop. None may be read as a runtime: health FAILING / exit 2, status and learn non-zero. `maep.ledger.read_events` must raise for a dangling symlink, a loop and a path under a file. Controls: an absent ledger in a directory reads `[]`; a fresh work directory (exists, no ledgers) is OK / `[]` / 0 failures; the real runtime and a symlink to it read identically to the pre-damage baseline.

FACT (defect, reproduced before the fix with the code unchanged: 15 failing subcases, controls passing): every case above read as a runtime with zero tasks — `hg health` `OK` exit 0, `hg status` `"tasks": []` exit 0, `hg learn` 0 failures; a dangling memory/models ledger was skipped. Root cause: `Path.exists()` follows symlinks and swallows ENOENT/ENOTDIR/ELOOP, so `read_events` and the health/learn gates treated these paths as an absent, empty ledger. Fix: `maep/ledger.py` `_absent()` (`lstat`; only ENOENT is absence, anything else goes to the `O_NOFOLLOW` opener, which refuses it); `hg/ops.py` `require_workdir()` (health FAILING), `lexists` gates for memory/models; `hg status` and `hg learn` require the work directory and exit 2 with a JSON reason on `MAEPError`. Two `test_learning_ops` health tests used a nonexistent path to stand for a fresh runtime and failed after the fix; they now create the directory, assertions unchanged.

FACT: PR #162 squash-merged as `c68f633c678e386f7466daf0f8e9a31e55e52bff` (tree `ae0bcf4a…` identical to head `9ce8965`); PR CI on `9ce8965` success (runs 43140637655, 43140671774 unittest 3.13/3.14; 43140671698 rt06-anchor 3.13/3.14). Local on that tree (Linux, Python 3.13.18, uid 0): oracle 7 OK, MAEP 385 OK, HG 874 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0 (hooks/selfcheck/bench run before the test-fixture change, which touches only `hg/tests/test_learning_ops.py`). Recovery branch `recovery/main-pre-operator-read-20261112` = `71cb6bd`.

DISCOVERED (not fixed here, next work package): `hg/assistant/notes.py` `snapshot()`/`trusted_ids()` gate on `self.path.exists()`; with `notes.jsonl` a dangling symlink, `hg note list` prints "no notes" and `hg ask` answers "no note" (exit 0), observed on the merged code. Same root cause; `hg serve` chat uses the same path.

Deploy: NOT_APPLICABLE for #162 alone (operator CLI; `maep.ledger` change reaches `hg serve` with the next release). The candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval and should be refreshed from main to include #154, #158, #160 and #162. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 38. Addendum 2026-11-12 10:10–10:30 +07 (hourly run, cloud only) — WS-04 notes ledger presence (#164); deploy not executed

FACT: `hg/tests/test_assistant_notes_ledger_presence_oracle.py` (5 tests) replaces `notes.jsonl` in a private home with a dangling symlink, a symlink loop and a symlink under a regular file, and checks `Notebook.snapshot`/`active`/`trusted_ids`, `ask.select_notes`, `ask.ledger_hash` (must raise `HomeError`/`MAEPError`) and the CLI `hg note list`, `hg note list --json`, `hg ask --notes-only` (exit neither 0 nor 5, no "no notes"/"no note on this" text). Controls: a home with no ledger reads `[]`/`set()`/hash `None`, CLI `[]` exit 0; a normal ledger lists its note, trust and hash.

FACT (defect, reproduced before the fix with the code unchanged: 24 failing subcases — 15 API, 9 CLI — controls passing): the §37 DISCOVERED item. `snapshot()`, `trusted_ids()` and `ledger_hash()` gated on `Path.exists()`; every damaged case read as an empty notebook (`hg note list` "Chưa có ghi chú nào" exit 0; `hg ask` "Ghi chú chưa có thông tin này" exit 5 and an ASK receipt with notes hash `None`). Fix: `hg.assistant.home.absent()` (`lstat`; only ENOENT is absence, same rule as `maep.ledger._absent`); anything present goes through `private_file()` (O_NOFOLLOW, regular, 0600, one link). Observed after: both commands print `HG từ chối chạy: cannot safely open notes.jsonl`, exit 78, no receipt written.

FACT: PR #164 squash-merged as `2a88d1d01860e9fbbe5b966f594818bf533c296a` (tree `59a5646d…` identical to head `b114d1c`); PR CI on `b114d1c` success (runs 43147393230, 43147420713 unittest 3.13/3.14; 43147420714 rt06-anchor 3.13/3.14). Local on that tree (Linux, Python 3.13.18, uid 0): oracle 5 OK, MAEP 385 OK, HG 879 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-notes-presence-20261112` = `b671553`.

Deploy: NOT_EXECUTED. #164 changes `hg.assistant.notes`, used by `hg serve` chat, so it is runtime-relevant and should join a refreshed candidate built from main together with #154, #158, #160 and #162; the candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 39. Addendum 2026-11-12 11:13–11:35 +07 (hourly run, cloud only) — WS-04 log-window line anchors (#166); deploy not applicable

FACT: `hg/tests/test_log_window_line_anchor_oracle.py` (4 tests) counts lines independently on the raw bytes (LF, CRLF, CR) and checks `hg.verification.bounded.extract_log_window` for both selections (error context, tail fallback): every `[L#]` line quotes raw line # (ANSI and NUL removed, as documented), `matched_error_lines` are the raw lines holding the marker, `line_ranges` cover exactly the labelled lines. Cases: VT, FF, FS, GS, RS, NEL, U+2028, U+2029 inside a line, each with LF/CRLF/CR endings. Controls: LF, CRLF, CR and mixed endings with and without a final newline; ANSI/NUL stripping.

FACT (defect, reproduced before the fix with the code unchanged: 48 failing subcases, controls passing): the §34 DISCOVERED item. `extract_log_window` numbered lines with `str.splitlines()`, so after one of those characters `[L5]` quoted raw line 4 and the tail fallback produced a range past the last raw line. Fix: `source_lines()` in `hg/verification/bounded.py` (LF/CRLF/CR, same rule as `code.search` #144 and `hg summarize` #156).

FACT: PR #166 squash-merged as `13bb6feee889d37a95b6358e9883bd1604e1390e` (tree `53e132e6…` identical to head `14a3f52`); PR CI on `14a3f52` success (runs 43153957809, 43153989595 unittest 3.13/3.14; 43153989728 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 4 OK, MAEP 385 OK, HG 883 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-log-window-anchor-20261112` = `ad3eac7`.

OBSERVED (no defect): the remaining `Path.exists()` gates (`hg/runtime.py` `open_task_store`, `hg/assistant/home.py` `home_for_path`, `ensure_home`, `hg/service.py` `_ensure_state_dir`) were probed: `build_runtime` with `tasks.jsonl`, `memory.jsonl` or `actions.jsonl` as a dangling symlink or loop refuses to start (`MAEPError: cannot safely open ledger for admission`); the directory gates fall through to `lstat` checks that refuse symlinks.

Deploy: NOT_APPLICABLE for #166 (no runtime caller of `extract_log_window`). The candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval and should be refreshed from main to include #154, #158, #160, #162 and #164. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 40. Addendum 2026-11-12 12:13–12:30 +07 (hourly run, cloud only) — WS-08 context budget and line fencing (#168); deploy not applicable

FACT (defect, reproduced on main `52c2c6e` with the code unchanged): `hg/brain/context.py` `build_context` (C-15, the context `BrainOrchestrator.execute_goal` passes to the planner) (1) counted the pinned lines but not the `## Constraints (always kept)` header, so an included memory or event line could push the text up to 29 characters past `budget_chars` and set `over_budget` although the pinned block fit (28 budgets in the repro); (2) joined memory content, `source_ref` and event fields unescaped, so a line break in retrieved data started a new context line and forged a `## Constraints` header, `Stop if:` and `Decision [...]` lines (MAEP-019 fencing claim).

FACT: `hg/tests/test_context_budget_fence_oracle.py` (9 tests) measures the returned text itself: whenever an optional item is included the text fits the budget, and `over_budget` equals "pinned block alone exceeds the budget" (sweep of every budget from 200 to pinned+400); exact fit kept, one character less dropped; every `str.splitlines()` break (LF, CR, CRLF, VT, FF, FS, GS, RS, NEL, U+2028, U+2029) in memory content, `source_ref`, event kind/task/step/reason and a pinned decision leaves one line per item and no forged header or pinned line; runtime path `execute_goal` → planner `context=` with a recording planner (task still CLOSED_VERIFIED). Controls: ordinary content (tab, non-ASCII) unchanged; pinned over budget kept whole. 37 failing subcases before the fix, for the expected reasons.

Fix: `used` is the exact length of the joined text; every line is rendered through `_one_line` (each break a visible escape). Pinned text is escaped the same way and never cut.

FACT: PR #168 squash-merged as `c5b0bcee2a40d9191ada2ef0ed6830767e953ece` (tree `2d070709…` identical to head `8d3d640`); PR CI on `8d3d640` success (runs 43160524004, 43160547998 unittest 3.13/3.14; 43160547847 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 9 OK, MAEP 385 OK, HG 892 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-context-fence-20261112` = `52c2c6e`.

Deploy: NOT_APPLICABLE for #168 (`execute_goal` callers are `hg bench` and the regression harness; `hg serve` chat does not build this context). The candidate `deploy-9c829ac-20261112` (§32) still waits for the owner's production approval and should be refreshed from main to include #154, #158, #160, #162 and #164. Production stays release `030a88d5` (`4eaac81`). WS-08 stays IN_PROGRESS: dependency fingerprint/invalidation and provider budget reconciliation remain.

## 41. Addendum 2026-11-12 13:13–13:30 +07 (hourly run, cloud only) — WS-08 router budget reconciliation (#170); deploy pending

FACT (defect, reproduced on main `b31d188` with the code unchanged: 28 failing subcases, controls passing): `hg/brain/providers.py` `ModelRouter.usage` (the session budget record; MODEL_CALL usage feeds chat and ask receipts) did not reconcile with the calls made. (1) `cost_usd` was rounded to 6 decimals after every call, so small calls were lost (1000 calls of 4e-7 USD recorded `0.0`, exact `0.0004`). (2) Usage that was not an object crashed `complete()` with `AttributeError`/`TypeError` after the answer; negative, bool, float or string counts were added to the totals; NaN/None counts crashed. (3) `cost_per_mtok` was never checked (negative, NaN, inf, bool, string, wrong length accepted; a later mutation changed accounting).

FACT: `hg/tests/test_router_budget_reconciliation_oracle.py` (8 tests) checks `usage` against exact `Fraction` totals of the successful calls and against the OK MODEL_CALL events: tiny, mixed and odd-price sequences, two providers on two routes, eleven malformed usage shapes (fallback reached, attempt recorded as INVALID_RESPONSE, totals untouched), malformed usage alone (UNAVAILABLE), absent count fields (= 0, control), twelve bad prices refused at build, four good prices accepted, price fixed at build time.

Fix: usage checked inside the provider `try` (not an object or a bad count → INVALID_RESPONSE, retried/fallen back as usual; an absent count is 0, same rule as the built-in providers); prices checked and fixed when the router is built; tokens summed per price as integers and `cost_usd` computed exactly from those sums, rounded once.

FACT: PR #170 squash-merged as `830511c08d0fd1a2bd5b059c19a786843730fa6a` (tree identical to head `fcccd4d`); PR CI on `fcccd4d` success (runs 43167564333, 43167586276 unittest 3.13/3.14; 43167586284 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 8 OK, MAEP 385 OK, HG 900 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-router-budget-20261112` = `b31d188`.

Deploy: NOT_EXECUTED. `hg serve` chat builds a `ModelRouter`, so #170 is runtime-relevant; the built-in Ollama provider already returns validated usage and the local price is 0, so no behaviour change is expected in production. It joins the refreshed candidate from main (with #154, #158, #160, #162, #164) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-08 stays IN_PROGRESS: dependency fingerprint/invalidation remains (no cache layer exists yet; assess need before building).

## 42. Addendum 2026-11-12 14:13–14:40 +07 (hourly run, cloud only) — WS-08 reader failure is not a provider failure (#172); deploy pending

FACT (defect, reproduced on main `91b0dad` with the code unchanged: 11 failing subcases, controls passing): `ModelRouter.complete(..., on_delta=...)` caught an exception raised by the caller's `on_delta` (e.g. `hg ask` printing to a closed pipe) as a provider failure. For a provider without streaming the call had succeeded, but it was recorded `MODEL_CALL ERROR UNAVAILABLE` with no usage, missed from `router.usage`, and the router asked the next provider: a second, possibly paid, call and a second answer after part of the first was shown (breaks the router's own "never a second answer" rule and the #170 reconciliation). For a stream the reader's exception surfaced as `ProviderError UNAVAILABLE … part-way`.

FACT: `hg/tests/test_router_consumer_failure_oracle.py` (7 tests): whole answer + failing reader (3 exception types, with and without a fallback provider): reader's exception unchanged, second provider never called, usage = the one call, one OK MODEL_CALL with usage; stream cut off at chunk 1/2/3 by the reader (plain and wrapping providers): reader's exception, no retry/fallback, usage 0, one MODEL_CALL ERROR `CONSUMER_FAILED:ReaderGone`; provider that swallows the reader's exception: usage accounted, recorded with usage. Controls: ordinary calls, provider bug after text (`part-way`), provider error before text (retry then fallback).

Fix (`hg/brain/providers.py`): the reader's failure is carried past the provider-error handling and re-raised unchanged; a whole answer is accounted and recorded OK before it is handed to `on_delta`.

FACT: PR #172 squash-merged as `2ff9ec980c6f8a9e34d7c05a0cbf9385e805a636` (tree `19580079…` identical to head `b7cbf1a`); PR CI on `b7cbf1a` success (runs 43175255184, 43175285949 unittest 3.13/3.14; 43175286155 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 7 OK, MAEP 385 OK, HG 907 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-router-consumer-20261112` = `91b0dad`.

ASSESSED (WS-08 remainder, no code): `ModelRouter.usage` has no consumer outside tests and the configured Claude provider has price (0, 0); no cache layer exists. Pre-call budget reservation, unknown-timeout cost and dependency fingerprint/invalidation have nothing to protect until a spend cap or a cache is introduced — DEFERRED until then, not CLOSED.

Deploy: NOT_EXECUTED. `hg serve` chat builds a `ModelRouter` (its `on_delta` sink is a list and cannot fail; a sentence-checker bug would now be the generic 500 rather than "model unavailable"). Joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-08 stays IN_PROGRESS (deploy pending; remainder DEFERRED as above).

## 43. Addendum 2026-11-12 15:13–15:40 +07 (hourly run, cloud only) — WS-04 memory ledger replay matches the write API (#174); deploy pending

FACT (defect, reproduced on main `b865658` with the code unchanged): `hg/memory/store.py` `MemoryStore._replay` (opening a memory ledger: `memory.jsonl` of the runtime, `notes.jsonl` of `hg note`/`hg ask`/`hg serve` chat) applied any `MEMORY_WRITE`/`MEMORY_STATUS` line. A reused `memory_id` overwrote a record (its earlier text gone from `history()`, against MAEP-015); a status event set a forgotten note ACTIVE again, or any status string, with no reason; a retraction of a non-ACTIVE record, a write with any status/version, a supersession of an unknown, retracted or other-subject record, and persisted WORKING memory were all accepted; malformed payloads crashed with `TypeError`/`AttributeError` instead of `MAEPError` (CLI exit 78).

FACT: `hg/tests/test_memory_replay_history_oracle.py` (6 tests; oracle = what `remember`/`retract` can write): 24 forged histories, each through a read-only and a writable store, and 4 of them through `Notebook.active()` and `hg note list --json` (exit 78, no forged or forgotten text, no traceback). Controls: API histories (supersede chain, promote, retract, EPISODIC event, WORKING) reopen identically; other writers' kinds (`NOTE_TRUST`, `ASK`) ignored; absent ledger empty; competing ACTIVE records still load and are reported in `restore_conflicts`. 52 failing subcases before the fix, controls passing.

Fix: replay refuses every event the API could not have written; unknown `MEMORY_*` kinds are refused, other kinds sharing the ledger are ignored. A first draft refused every unknown kind and broke two existing tests: `notes.jsonl` also holds `NOTE_TRUST` (written by `hg/assistant/notes.py` through `EventLog`), so the store now owns only the `MEMORY_*` namespace.

FACT: PR #174 squash-merged as `793f8d12832efaa0adcad42e7aebe639338d3322` (tree identical to head `ce27bba`); PR CI on `ce27bba` success (runs 43183575586, 43183607698 unittest 3.13/3.14; 43183607878 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 6 OK, MAEP 385 OK, HG 913 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-memory-replay-20261112` = `b865658`.

RISK (UNVERIFIED): every historical `store.py` writes only ACTIVE/version-consistent records and RETRACTED with a reason, but a production `notes.jsonl` or `memory.jsonl` written before the build-under-lock change by concurrent writers could hold a double supersede/retract and would now be refused (exit 78). Before switching production to a candidate containing #174, open both ledgers read-only with the candidate (`MemoryStore(path, read_only=True)`). `hg repair` repairs only a torn tail and cannot fix such a ledger, although the exit-78 message suggests it (DISCOVERED, wording only).

Deploy: NOT_EXECUTED. Runtime-relevant (`hg serve` chat reads notes). Joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170, #172) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 44. Addendum 2026-11-12 16:12–16:30 +07 (hourly run, cloud only) — WS-04 `hg repair` agrees with the notes reader (#176); deploy pending

FACT (defect, reproduced on main `50e0117` with the code unchanged: 53 failing subcases, controls passing): the §43 DISCOVERED item. Every command that cannot read a ledger tells the owner to run `hg repair` (CLI exit 78, chat 503 `notes_ledger_damaged`), but `hg/assistant/repair.py` checked only the line format (`EventLog`). On a `notes.jsonl` whose lines are well-formed but whose history `MemoryStore` refuses (#174), `hg repair` printed `OK` and exited 0 while `hg note list` exited 78; a torn tail over such a history was reported `REPAIRED` into a ledger still refused.

FACT: `hg/tests/test_repair_semantic_damage_oracle.py` (7 tests; oracle = `Notebook.active()` itself): all 24 forged histories of #174 → `inspect` DAMAGED with a reason, `repair` leaves the bytes unchanged and writes no backup; torn tail over a forged history → DAMAGED, not rewritten; CLI `hg repair` exits 78 whenever `hg note list` exits 78. Controls: genuine notes OK; genuine torn tail REPAIRED and loads; receipts ledger OK (format only).

Fix: `notes.jsonl` is replayed with the `MemoryStore` reader from a private copy of the inspected bytes; a refused history is DAMAGED and never rewritten; a torn tail is repaired only if the remaining history loads, and the result is reloaded with that reader. `docs/HG_V1_GUIDE.md` troubleshooting row updated.

FACT: PR #176 squash-merged as `7e57d02aa6e438d258481b9df5d804be05db2ddc` (tree identical to head `1719c80`); PR CI on `1719c80` success (runs 43190400837, 43190393985 unittest 3.13/3.14; 43190400743 rt06-anchor 3.13/3.14). Local on `4b17a8b` (Linux, Python 3.13.18, uid 0): oracle 7 OK, MAEP 385 OK, HG 920 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0; `1719c80` adds only the guide row. Recovery branch `recovery/main-pre-repair-history-20261112` = `50e0117`.

Deploy: NOT_EXECUTED. Runtime-relevant only through the owner's `hg repair` command (same release symlink). Joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170, #172, #174) that waits for the owner's production approval; the §43 pre-switch check (open production `notes.jsonl`/`memory.jsonl` read-only with the candidate) can now be done with the candidate's `hg repair` for `notes.jsonl`. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 45. Addendum 2026-11-12 17:13–17:35 +07 (hourly run, cloud only) — WS-04 config.json values are checked (#178); deploy pending

FACT (defect, reproduced on main `a4fdd5e` with the code unchanged: 154 failing subcases, controls passing): `hg/assistant/config.py` `load()` checked only key names, so a wrong value was accepted and failed later, differently per path. `model_digest`/`ollama_service_dir` not a string: traceback (CLI exit 1, chat uncaught `TypeError`). `max_tokens` not an integer: chat 503 `notes_ledger_damaged` ("run hg repair"), a wrong diagnosis. `think: "no"`, `keep_alive: []`, `num_ctx: "4096"`, `timeout_s: NaN` were passed on; the model was contacted in 32 of 46 chat cases. `model_digest: ""` turned the digest pin off silently.

FACT: `hg/tests/test_assistant_config_value_oracle.py` (10 tests; oracle = the value types each consumer needs): 48 unusable values across 11 keys refused by `load` naming the key and by `save` (nothing written); `hg serve` chat → 503 `assistant_unavailable`, model never called, no receipt; CLI `hg ask` and `hg model status` → exit 78, no traceback. Controls: absent file, explicit defaults, 22 usable values, `HG_MODEL` override, save/load round trip, a valid config answers.

Fix: `validate()` on load and on save (non-empty printable strings; integers in range for `num_ctx`, `num_thread`, `max_tokens` 1..64000; finite `timeout_s` > 0; `think` bool/null; `keep_alive` duration string, integer or null).

FACT: PR #178 squash-merged as `890c178180e554b94973f95e85565132c64d4c80` (tree identical to head `b0cb88d`); PR CI on `b0cb88d` success (runs 43199974250, 43200012906 unittest 3.13/3.14; 43200012887 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 10 OK, MAEP 385 OK, HG 930 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-config-values-20261112` = `a4fdd5e`.

RISK (UNVERIFIED): a production `config.json` holding a value now refused would make chat 503 and the CLI exit 78 after the switch. Before switching, run the candidate's `hg model status` against the production home.

Deploy: NOT_EXECUTED. Runtime-relevant (`hg serve` chat and the owner's `hg` read `config.json`). Joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170, #172, #174, #176) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 46. Addendum 2026-11-12 18:15–18:35 +07 (hourly run, cloud only) — WS-04 evaluation file values are checked (#180); deploy pending

FACT (defect, reproduced on main `8bf957a` with the code unchanged: 145 failing subcases/tests, controls passing): `hg/assistant/evaluate.py` `load_spec` checked only that the file is one JSON object. A missing threshold or an `expect` naming no note raised `KeyError` after every question had been asked (model contacted); a string threshold raised `TypeError` at the verdict; an answerable question with `key: []` counted any answer as a correct fact (`all([])`, a false PASS); two notes on one subject stopped the run (`NoteConflict`) or, with the same text, mapped two keys to one note; thresholds `true`, `1.5` or `0` seconds decided the verdict. `deploy/termux/eval_resumable.py` read the file with plain `json.loads`.

FACT: `hg/tests/test_eval_spec_value_oracle.py` (9 tests; oracle = the fields `run`/`score` read and what `Notebook.add` accepts): 57 unusable variants refused by `load_spec` and by `run()` with zero router calls; the refusal names the field; `hg eval --set` exits 2 without traceback; the harness exits without creating notes. Controls: the four shipped specs (`eval_vi*.json`), extra fields, usable variants.

Fix: `validate_spec()` in `load_spec`; the harness uses `load_spec` when the release has it (releases `7698097`, `5476315`, `4eaac81` have none: unchanged behaviour plus a warning).

FACT: PR #180 squash-merged as `3d65557ead7bf91b219c438bdfa99a9ff11315e9` (tree identical to head `f30da11`); PR CI on `f30da11` success (runs 43209079162, 43209109224 unittest 3.13/3.14; 43209109178 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 9 OK, MAEP 385 OK, HG 939 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-eval-spec-20261112` = `8bf957a`.

Deploy: NOT_EXECUTED. Affects only the owner's `hg eval` command and the on-device eval harness; joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170, #172, #174, #176, #178) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending). Remaining WS-04 readers without a value oracle: `hg check` inputs (DISCOVERED); `asks-*.jsonl` receipts are written and format-checked by `hg repair` but read by no command (NOT_APPLICABLE for a semantic oracle).

## 47. Addendum 2026-11-12 19:16–19:35 +07 (hourly run, cloud only) — WS-04 `hg check` input rules (#182); deploy pending

FACT (defect, reproduced on main `3eee3a7` with the code unchanged: 15 failing subcases, controls passing): the §46 DISCOVERED item. `hg check` read its input with no rules. Empty or blank input exited 0 with no output (a script reads that as "no conflict"); bytes that are not UTF-8 (another encoding, a truncated multibyte character) were silently replaced and compared mangled, exit 0; NUL bytes were accepted; stdin was unbounded; input with no comparable sentence (`...`) exited 0. `hg summarize -` already refused these.

FACT: `hg/tests/test_check_input_oracle.py` (4 tests; oracle = the `summarize.read_input` rules, the exit-code table, `grounding.summarize` `claims`): 6 unreadable inputs × text/JSON → exit 2 with a reason, no label printed; 7 blank inputs (stdin and argv) → exit 2; `...`/`?!` → exit 5. Controls: conflict → 4, matching note → 0, argv conflict → 4, unknown sentence → 0 `[CHƯA RÕ]`, exactly 1 MB accepted.

Fix: `_check_input` in `hg/assistant/cli.py` (stdin through `summarize.read_input`; argv text held to the same rules; blank refused); `claims == 0` → exit 5. `docs/HG_V1_GUIDE.md` §4 states the rule.

FACT: PR #182 squash-merged as `aba80a610faf2913984faaeeadd4e281463f98b9` (tree identical to head `06d0afa`); PR CI on `06d0afa` success (runs 43217603762, 43217634726 unittest 3.13/3.14; 43217634801 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 4 OK, MAEP 385 OK, HG 943 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-check-input-20261112` = `3eee3a7`.

Deploy: NOT_EXECUTED. Affects only the owner's `hg check` command (and `/kiểm` in the prompt, where an empty check now reports exit 2 instead of nothing); joins the refreshed candidate from main (with #154, #158, #160, #162, #164, #170, #172, #174, #176, #178, #180) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending). WS-04 assistant readers now all have an input/value oracle (notes, config, eval spec, repair, check); `asks-*.jsonl` NOT_APPLICABLE (read by no command). Next WS-04 item: none DISCOVERED in the assistant layer; remaining gate is the owner's production approval.

## 48. Addendum 2026-11-12 21:15–21:35 +07 (hourly run, cloud only) — WS-12 deploy reads the assistant home before publishing (#184); deploy pending

FACT (defect, observed on main `8d48048`): `install_release.sh` published the `hg` pointer and `switch_service.sh` switched chat without the candidate ever reading the production assistant home. The §43/§45 pre-switch checks (candidate opens production `notes.jsonl`/`config.json`) were manual. Reproduced with the readers themselves: the production release tree `4eaac81` accepts `config.json` `{"max_tokens": "512"}`, main refuses it, so after a switch `hg` would exit 78 and chat 503.

FACT: `deploy/termux/assistant_precheck.py <release_root> [<home>]` copies `config.json` and every `*.jsonl` of the home (no symlinks followed; existing `.lock` held shared, never created) into a private home and loads it with the release's own `repair.inspect` (OK only), `Notebook.active/trusted_ids` and `config.load`; exit 0 OK/ABSENT, 1 naming the refused file, 2 usage. `install_release.sh` runs it after the second `verify_root`, before the pointer; `switch_service.sh` runs `assistant_ok "$ROOT"` in step 3 before `stop_service` (report `assistant-precheck.json` in the switch dir). The reader APIs it calls exist unchanged in releases `7698097` and `4eaac81`, so it can also check a rollback target.

FACT: `hg/tests/test_assistant_home_precheck.py` (14 tests; oracle = the release's own readers): 37 failures + 9 errors before the script existed; genuine, absent, empty and `HG_HOME` homes pass; 24 forged histories, torn tail (report names `hg repair`), 4 unusable config values, unknown key, bad JSON, duplicate key, damaged receipt, symlinked ledger and a 0750 home fail; live home names, bytes and mtimes unchanged in every case; order pinned in both scripts.

FACT: PR #184 squash-merged as `4188703031cda80813aa8cecabd04693c18a246c` (tree identical to head `f57e221`); PR CI on `f57e221` success (runs 43236671901, 43236727649 unittest 3.13/3.14; 43236727700 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 14 OK, MAEP 385 OK, HG 957 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-assistant-precheck-20261112` = `8d48048`.

UNVERIFIED: not run on the phone (Termux flock on a read-only descriptor, Android paths); the first on-device run is the next install. Deploy: NOT_EXECUTED; the refreshed candidate from main now carries its own pre-switch home check. Production stays release `030a88d5` (`4eaac81`). WS-12 stays IN_PROGRESS (owner production approval).

## 49. Addendum 2026-11-12 23:14–23:35 +07 (hourly run, cloud only) — WS-04 `hg ask` / `hg note add` input rules (#186); deploy pending

FACT (defect, reproduced on main `ffcd038` with the code unchanged: 19 failing subcases, controls passing): the §47 rules covered only `hg check`. `hg ask` with bytes that are not UTF-8 (stdin or argv) answered the mangled question, then failed writing the ASK receipt and printed "Sổ cái hỏng … Chạy: hg repair" (exit 78) although every ledger was intact; a NUL byte was silently dropped (stdin `\x00` alone: `ValueError` traceback); `hg note add` with non-UTF-8 input ended in a `UnicodeEncodeError` traceback (exit 1); stdin was unbounded.

FACT: `hg/tests/test_ask_note_input_oracle.py` (6 tests; oracle = `summarize.read_input` rules, the exit-code table, ledger bytes): 6 unreadable stdin inputs and 3 non-UTF-8 argv values → exit 2 with a reason, no traceback, no "hg repair", no answer, no ledger byte changed; blank input → exit 2. Controls: genuine stdin/argv question and note, CRLF, exactly 1 MB passes the input rule (then the 4000-character note limit, exit 2).

Fix: `_check_input` generalised to `_read_text` in `hg/assistant/cli.py`, used by `check`, `ask` and `note add`. `docs/HG_V1_GUIDE.md` §4 states the rule.

FACT: PR #186 squash-merged as `bbcf553eb7e623fc0727f98cc5e8314aafab13c0` (tree identical to head `803e3e7`); PR CI on `803e3e7` success (runs 43258052704 unittest 3.13/3.14; 43258052693 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 6 OK, MAEP 385 OK, HG 963 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0.

Recovery: branch `recovery/main-pre-ask-note-input-20261112` was pushed from the work branch by mistake and points at `803e3e7`, not at main; its parent `ffcd038` is the pre-merge main (restore with `803e3e7^`). The guard forbids moving or deleting `recovery/*`, so it stays as recorded here.

Deploy: NOT_EXECUTED. Affects only the owner's `hg ask` / `hg note add` CLI and the prompt; `hg serve` chat validates its own JSON body and is unchanged. Joins the refreshed candidate from main (#154…#186) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 50. Addendum 2026-11-13 00:13–00:35 +07 (hourly run, cloud only) — WS-04 `hg note forget --reason` input rules (#188); deploy pending

FACT (defect, reproduced on main `96d8ac1` with the code unchanged: 27 failing subcases/errors, controls passing): `Notebook.forget` passed `--reason` to the ledger unchecked. A blank reason (`""`, `"   "`) was refused by `MemoryStore.retract` with `MAEPError`, and a reason whose bytes are not UTF-8 failed at the ledger writer (`UnicodeEncodeError`); both were reported as "Sổ cái hỏng … Chạy: hg repair" (exit 78) while `hg repair` reported the ledger OK. Control sequences (`\x1b[2J`), bidi overrides and unbounded reasons were written into the owner's ledger, unlike note text. `clean_text` let lone surrogates through, so `Notebook.add` from callers other than the CLI failed later at the writer the same way.

FACT: `hg/tests/test_note_forget_reason_oracle.py` (5 tests; oracle = the exit-code table, `clean_text` rules, ledger bytes): 9 unusable CLI reasons → exit 2 naming the reason, no "hg repair", no traceback, no ledger byte changed, `hg repair` exit 0; 8 unusable API reasons and 3 surrogate note texts → `NoteError`. Controls: default reason, Vietnamese reason, trimmed reason, exactly 500 characters, unknown id stays exit 2.

Fix: `Notebook.forget` applies `clean_text(reason, limit=MAX_REASON_CHARS=500)`; `clean_text` refuses lone surrogates (category Cs) and names what it refused. `docs/HG_V1_GUIDE.md` §3 states the rule. Existing ledgers are read unchanged (only writes are restricted).

FACT: PR #188 squash-merged as `d45e0dcf8a63e1fd6fd69ae483b5813a4af1c71d` (tree identical to head `11db41e`); PR CI on `11db41e` success (runs 43268308349, 43268354498 unittest 3.13/3.14; 43268354817 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 5 OK, MAEP 385 OK, HG 968 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-forget-reason-20261113` = `96d8ac1` (pushed from `origin/main`, verified with `git ls-remote`).

Deploy: NOT_EXECUTED. Affects only the owner's `hg note forget` CLI (and any `Notebook.add` caller passing surrogates); `hg serve` chat does not forget notes. Joins the refreshed candidate from main (#154…#188) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending). Assistant-layer write inputs now covered: note text, subject, replaces, reason, ask, check, config, eval spec.

## 51. Addendum 2026-11-13 01:13–01:35 +07 (hourly run, cloud only) — WS-04 assistant counts and search query rules (#190); deploy pending

FACT (defect, reproduced on main `6035359` with the code unchanged: 12 failing subcases + 3 errors, controls passing): `hg note list --limit 0`/`-1` printed "Chưa có ghi chú nào" (exit 0) with notes present, and `-1` silently dropped the oldest note (slice `[:-1]`); `hg note search wifi --limit 0`/`-3` reported "Không tìm thấy" (exit 5) for a matching note; `hg summarize --max-sentences 0` reported "too short" (exit 5) and `-1` silently dropped a sentence; a blank search query reported "not found" (exit 5) and a non-UTF-8 query was searched mangled (exit 0 with a hit).

FACT: `hg/tests/test_cli_count_query_oracle.py` (4 tests; oracle = exit-code table, the notebook's own contents, the `_read_text` input rules): 7 unusable counts × 5 commands and 6 unusable queries → exit 2, no false "no notes"/"not found"/"too short" message, no ledger byte changed; `Notebook.search` and `summarize.extractive` refuse counts 0, -1, 1.5, True, "2", None. Controls: limits 1/2/3/50, newest first, usable query with no match → 5, max-sentences 1/2/3.

Fix: argparse type `_count` (whole number ≥ 1) for `--limit` (list, search) and `--max-sentences`; library guards in `Notebook.search` (NoteError) and `summarize.extractive`/`with_model` (ValueError); `note search` query through `_read_text`. `docs/HG_V1_GUIDE.md` §4 states the rule.

FACT: PR #190 squash-merged as `4783241b5fbba36023a97d990c965ec8a67cb705` (tree identical to head `2fb973d`); PR CI on `2fb973d` success (runs 43279365726, 43279401012 unittest 3.13/3.14; 43279400618 rt06-anchor 3.13/3.14). Local (Linux, Python 3.13.18, uid 0): oracle 4 OK, MAEP 385 OK, HG 972 OK (skip 6), hooks 32 OK, selfcheck 0, bench 0. Recovery branch `recovery/main-pre-cli-counts-20261113` = `6035359` (verified with `git ls-remote`).

Deploy: NOT_EXECUTED. Affects only the owner's `hg note list/search`, `hg summarize` CLI and `/tìm` in the prompt (blank `/tìm` now exit 2); `hg serve` chat uses fixed limits and is unchanged. Joins the refreshed candidate from main (#154…#190) that waits for the owner's production approval. Production stays release `030a88d5` (`4eaac81`). WS-04 stays IN_PROGRESS (deploy pending).

## 52. Addendum 2026-11-13 +07 (owner session, stabilization RECONCILE) — WS-03 agent guard hardening ported from PR #11, `python -m hg` allowlisted

Owner decision 2026-11-13 under the HG PR Expansion Control & Stabilization Directive V1.0: port only the guard part of draft PR #11 in one PR, with `python -m hg` and `hg.*` added to the allowlist. The audit-only execution host part of #11 (`hg/runtime.py`, `hg/tools/gateway.py`, `maep/core.py`) is not ported. It would need a manual merge onto a main that has diverged, so it stays on #11.

FACT (finding): main `6035359` did not contain #11's guard hardening. The diff from #11 head `0f25cb5c` to main for `.claude/hooks/maep_guard.py` was +84/−21, and main had not changed the guard since the merge base `37e30b1`.

Change: `.claude/hooks/maep_guard.py` and `.claude/hooks/test_maep_guard.py` are taken from `0f25cb5c`. Then `python -m hg` and `python -m hg.*` are allowed. Every other `-m` module stays blocked, except `unittest discover` in the three test roots. `HgModuleAllowlistTests` failed on the #11 version (1 failure) and passes now. Look-alike modules (`hgx`, `hg_evil`), `pip`, `http.server`, `-c` and `$(...)` stay blocked. `CLAUDE.md` now describes the guard as it is.

Effect on agents: Bash calls in sessions that load this hook can no longer use `$(...)`, backticks, `eval`, `xargs`, `find -exec`, `python -c` or script files (`bash x.sh`, `python x.py`). The guard's own files become owner-only. CI is not affected. Deploys that run on the phone through Desktop Commander are not affected either, because the hook does not run there.

FACT: local (Linux, Python 3.13.18): hooks 42 OK, MAEP 385 OK, HG 968 OK (6 skipped), selfcheck 0, bench 0. Deploy: NOT_APPLICABLE. The hook is agent tooling and is not part of the release. Production stays on release `030a88d5` (`4eaac81`).

## 53. Addendum 2026-11-13 01:00–02:10 +07 (owner session) — Stabilization Directive V1.0: AUDIT and RECONCILE record

Directive: on 2026-11-13 the owner issued the *HG — PR Expansion Control & Stabilization Directive V1.0*. HG moves from PR expansion to AUDIT → RECONCILE → INTEGRATE → VERIFY → ACCEPT. Priorities are P0 (safety, integrity, security) through P4 (features, deferred). There is a temporary expansion freeze. A new PR needs an admission record. GO-LIVE is decided by the owner.

**PR backlog. VERIFIED through the GitHub REST API, 192/192 classified:**

| Class | PRs | Count |
|---|---|---|
| Merged to `main` | #1–#5, #7–#10, #12–#15, #22, #29, #34, #36, #56–#60, #62, #65–#76, #78–#118, #120–#192 except #119 | 148 |
| Merged to the frozen v2 line `stt/maep-v1-20261022` | #16–#21, #23–#28, #30–#33, #35, #37–#54, #61, #63 | 38 |
| Closed, not merged | #6 (deliberately failing CI probe); #55 (agent tooling config: closed by owner decision 2026-11-13, branch kept) | 2 |
| Open | #11 draft (guard part ported in #191; execution-host part stays, divergent); #64 draft, base v2, labelled `DEFERRED_V2`; #77 HOLD (admission record posted; waits for the listener-path choice and G2/G5); #119 draft (G7-CI, see below) | 4 |

**Owner decisions (OD-STAB-20261113):**
- A. The hourly scheduled task "HG phiên làm việc tự chủ" is paused (disabled 01:20). Its prompt asked for new workstreams, which conflicts with the freeze. The run already in flight at 01:12 still produced #190 (fix) and #192 (separate ledger addendum) after the pause. They are recorded here and were not reverted.
- B. PR #55 is closed and its branch kept.
- C. For the 27 `UNRESOLVED_OWNER_CHOICE` paths, **main is canonical**. All 27 are uncommitted variants in phone worktrees, and none byte-matches main. The 15 paths in MEMORY_CONTINUITY / RCME / LLAMA_CPP / H1.3.1 / BATCH1 are deferred (P4, frozen features). The 6 LISTENER_ATTESTATION paths are reviewed with #77. The 6 CIM_ANDROID_BROKER paths are reviewed with #119. The worktrees are preserved untouched. Source matrix: phone `~/HG-GO-LIVE-CANDIDATE/docs/evidence/HG-GO-LIVE-20261111/reconciliation/OVERLAP_SOURCE_OWNERSHIP_MATRIX.json`, untracked, sha256 `88b8c98c9d01af0f1a1dc68fa6ae8f4b2cf7f179c7b8caebbd54fae90750a66b`.
- D. The guard part of #11 is ported with `python -m hg` allowlisted (#191, §52).

**Rules from now on (directive §2, step 7):**
- A fix PR carries its own ledger line. Separate "ledger addendum" PRs are not opened. Since 2026-11-10, 46 of the 99 commits on main had been such PRs.
- A new PR needs an admission record: finding/blocker, workstream, root cause, why no existing PR fits, files/interfaces, dependencies, tests/acceptance, production impact.

**Production. VERIFIED on the phone, read-only, 2026-11-13:**
- The runit service `hg-runtime` is up.
- `run` and the `hg` shim both point to release `030a88d5…`, whose manifest commit is `4eaac81` (#113, 2026-11-10).
- Main `62ab167` is ahead of production by #116–#191. Production was not changed.

**Branch and worktree provenance:**
- Remote: 70 `recovery/*` branches. 65 are ancestors of `main`, 3 are ancestors of `stt/maep-v1`, 1 is an ancestor of the #119 branch (its pre-sync point), and `main-pre-ask-note-input-20261112` has the same patch as #186.
- New recovery branches: `recovery/stt-hg-android-broker-ci-pre-sync-20261113` (`aba365f`), `recovery/main-pre-guard-port-20261113` (`6035359`), `recovery/main-pre-guard-port-d7b0db5-20261113` (`d7b0db5`).
- Phone: 22 HG worktrees. 16 are on branches that exist only on the phone. Their heads are on the remote, except 4 commits that exist only on the phone: `1709af6f` and `ff77455a` (capability-convergence integration), `64e4c088` (`stt/b3-r05-exception-unknown-20261109`) and `3d13e36d` (`stt/b4-ledger-append-admission-20261109`). UNVERIFIED whether their content is already on main. Pushing them to the public repository is an owner decision.
- There are about 120 uncommitted files across the worktrees. They are preserved and not moved.

**Go-live v3 gate record (branch `stt/hg-master-go-live-v3-execution-20261111`, commit `272300a`, 2026-11-11), carried here:**

| Gate | Status | Reason |
|---|---|---|
| G1 | PARTIAL → owner decision C recorded | Integration still follows the groups in decision C. |
| G2 | BLOCKED | No Android L1/L5 PID-namespace/listener evidence on the real device. |
| G3 | PARTIAL | Mandatory security tests are skipped on Android. |
| G4 | BLOCKED | No single gateway for every model call across all providers and entrypoints. |
| G5 | BLOCKED | Ollama provenance trust anchor is empty. |
| G6 | BLOCKED | No staging recovery or rollback qualification. |
| G7 | BLOCKED | No signed APK and no real separate-UID Binder test. |
| G8 | BLOCKED | No end-to-end inference → agent → tool → evidence journey. |

The record's wording that makes "independent review" a GO-LIVE condition is superseded by OD-IR-20261109. The technical gates are unchanged. **GO-LIVE: NO-GO.**

**G7-CI (#119):**
- Branch synced with main without rewriting history (`ebe9112`).
- `15a723d`: the emulator checks run as one bash script. Root cause: emulator-runner runs each inline line in its own `sh -c`.
- `528d678`: the emulator stack installs from the stable SDK channel. Root cause: canary platform-tools needs a preview licence that is not accepted on the runner.
- A regression test fails on each previous workflow.
- Emulator result at the time of this record: see the PR. #119 stays a draft until the job passes. G7 stays BLOCKED until a real device passes.

**Status:** RECONCILE PARTIALLY VERIFIED. Exit conditions still open: G2–G8, Android real-device verification, the provenance of the 4 phone-only commits, and owner acceptance of GO-LIVE.

## 54. Addendum 2026-11-13 02:05–03:50 +07 (owner session, stabilization RECONCILE step 3) — G7-CI: Android Broker emulator negative-Binder qualification passes (#119)

**Scope.** PR #119, Android CIM Broker with cross-UID Binder qualification in CI. Recovery point `recovery/stt-hg-android-broker-ci-pre-sync-20261113` = `aba365f`. The branch was synced with main by merge commits (`ebe9112`, `0842b2d`). History was not rewritten.

**Root causes found and fixed in sequence.** Each fix has a test in `hg/tests/test_android_broker_workflow.py` that fails on the previous version:
1. `15a723d`: emulator-runner runs each line of an inline `script:` in its own `sh -c`. `BROKER=…` was lost, and `test -s ""` exited 1. Fix: the checks move into `android/cim-broker/ci/emulator_negative_binder.sh`.
2. `528d678`: `sdkmanager --channel=3` pulled canary platform-tools, whose preview licence is not accepted on the runner. Fix: the emulator stack installs from the stable channel. No licence is accepted on anyone's behalf.
3. `403c830`: Button labels render with `textAllCaps`. Fix: labels match case-insensitively, also through `content-desc`, and a timeout names the labels it saw.
4. `a9ea637`: `awk … exit` under `pipefail` ended in SIGPIPE, exit 141. Reproduced locally (old pipeline 141, new 0). Fix: awk reads all input.
5. `67be038`: `/sdcard` (FUSE) was not ready right after boot. Fix: the UI dump goes to `/data/local/tmp`.
6. `523c6cc`: switched to the AOSP `default` image after a Play services ANR.
7. `f6f5589`, **the root cause behind 5 and 6:** the runner user could not open `/dev/kvm`, so the emulator ran with `-accel off`. Boots took 490–771 s and system apps raised ANR dialogs. Fix: the udev rule that the emulator-runner README requires.

**FACT (CI on `f6f5589`, run 43303330208, job 131480841429, success):**
- Boot completed in 26.9 s.
- `TERMUX_UID=10148`, `BROKER_UID=10149`, `PROBE_UID=10150`, `UIDS_DISTINCT=PASS`.
- Owner pairing is stored (`owner_paired=true`, `termux_uid=10148`).
- `NEGATIVE_BINDER_PASS_DENY_UID caller_uid=10150`.
- broker-build-unit, unittest 3.13/3.14 and rt06-anchor are green.
- Artifacts: `hg-cim-broker-emulator-evidence-02dddb07…` (sha256 `4bd4719d…`) and `hg-cim-broker-build-02dddb07…` (sha256 `67571554…`).

**Status.**
- G7-CI (emulator) VERIFIED.
- **G7 stays BLOCKED** until there is a signed APK, an install on the owner's real phone, and a positive plus negative separate-UID Binder test there. Emulator results do not satisfy physical-device requirements.
- Trust anchors stay empty (fail-closed).
- Deploy: NOT_APPLICABLE. The Android source is not part of the `hg` release, and production is unchanged (`030a88d5` / `4eaac81`).

## 55. Addendum 2026-11-13 08:05–10:25 +07 (owner session, stabilization INTEGRATE → VERIFY) — owner decisions D1–D3, G3/G4/G6/G7 evidence, §53 correction

**Owner decisions:**
- **D1. Phone-only commits are kept offline and not pushed.**
  - Bundles are in `~/HG-OFFLINE-BACKUP-20261113/` (mode 0700) with `SHA256SUMS`:
    - `HG-CONVERGENCE-INTEGRATION-20261110.bundle` `6734660a…`
    - `…20261110B.bundle` `a3dcbd06…`
    - `HG-IR-PR88.bundle` `565fd277…`
    - `HG-IR-REMEDIATION-20261109.bundle` `e4374e92…`
  - Each bundle verified with `git bundle verify`. No original commit was amended, rebased or deleted.
  - Secret scan of the unpublished patches: no token, key or private-key pattern. The only email-pattern hit is `@api.example.test` in a test, a reserved test domain.
  - **Correction to §53:** only `1709af6f` and `ff77455a` are missing from GitHub. `64e4c088` (head of #88) and `3d13e36d` are retrievable through the GitHub API; the earlier check used a shallow clone. Both phone-only commits have the same stable patch-id `870d8337c3ea62e6` as `0feca8a`, which is on GitHub (`stt/hg-capability-convergence-v1-20261110`), only on different parents. No unique content exists only on the phone.
- **D2. G2 and G5 are recorded as BLOCKED for v1.**
  - #77 stays on HOLD (label `HOLD_BLOCKED_V1`). The L5 gate needs PID-namespace support, which the real kernel lacks.
  - No listener variant is integrated. All 3 variants stay preserved.
  - Listener attestation is not implemented in the runtime and does not meet operating conditions.
- **D3. #11 is closed and deferred to P4 (label `DEFERRED_P4`); its branch is kept at `0f25cb5c`.**
  - Verified first: main's guard equals #11's guard plus the 5-line `python -m hg` allowlist, and main's guard tests equal #11's plus 30 lines.
  - What was not ported is the audit-only execution host (+1001/−8 against `37e30b1`).

**G3 (WS-04), security tests skipped on Android.** Run on the owner's phone (Android 17, SDK 37, Termux 0.118.3, Python 3.14.8, UID 10460) from a fresh clone of `cfe376c`:
- Results: HG 980 OK (3 skipped), MAEP 385 OK (3 skipped), hooks 42 OK, `hg selfcheck` PASS, `hg bench` 0.
- All 6 skips are classified. They stay SKIP and are not counted as PASS:
  - **5 hard-link oracles** (`test_chat_receipt_oracle` ×2, `test_evidence_store_false_accept_oracle` ×1, `test_sqlite_nofollow` ×2) are SKIP_JUSTIFIED. Android's SELinux policy does not grant apps hard links, and Termux's Python ships without `os.link`. The attack primitive is therefore unavailable to any app UID on this platform. The same tests run and pass on Linux CI (unittest 3.13/3.14 on `cfe376c`).
  - **1 root-only oracle** (`test_sqlite_nofollow.test_rejects_directory_owned_by_another_user`) is SKIP on Android and on the non-root CI runner. It ran and passed in the root cloud session of 2026-11-13: MAEP 385 OK, 0 skipped. Finding G3-1 (P3): it has no CI coverage.
- **G3 status:** the criterion "no security test skipped without a reason" is VERIFIED. Coverage gap G3-1 remains open.

**G4 (WS-08), ModelCallGateway admission record.**
- **Finding:** G4 BLOCKED, "no single gateway for every model call".
- **Current main:** model calls go through `hg.brain.providers.ModelRouter` in `hg/assistant/ask.py`, `hg/chat.py`, `hg/brain/planner.py` and `hg/research/research.py`. The only model HTTP transport is in `hg/brain/providers.py`.
- **Root cause of the gap:** nothing proves this property. There is no conformance test that fails when an entrypoint calls a model outside `ModelRouter`.
- **Not admitted:** `0feca8a` (`feat(brain): wire compatible provider into ModelPlanner`, +523, 8 files). It adds a new OpenAI-compatible HTTPS provider, which is a P4 capability under the freeze and conflicts with the v1 local-first decision.
- **Admitted for the next step (P1, verification only):** ONE PR adding a conformance test. Static: no model-endpoint HTTP outside `providers.py`. Runtime: each entrypoint builds its calls through `ModelRouter`, including a negative case where a direct call fails the test.
- **Dependencies:** none. **Production impact:** none.

**G6 (WS-12), staging recovery and rollback on the phone. Isolated:** `HOME` and `PREFIX` point to `~/hg-staging-g6-20261113`, port 18867, a new token and state. The production pointer, shim and service were not touched (sha256 `6739742c…` and `d17b5c0c…` unchanged; `hg-runtime` pid 8414 ran throughout).
- **Reproducible build:** `build_release.sh 4eaac81` rebuilt release `030a88d534bd…`, identical to production (files 303, tree `e2144894…`).
- **Candidate:** `cfe376c` → release `5fb5f2e549f6…` (files 379, tree `5f26e6b0…`).
- **Install:** both installed with `install_release.sh`, each verified and sealed.
- **Pointer rollback:** `hg selfcheck` PASS on the candidate, and PASS again after restoring the pointer from `.prev`.
- **Service level:**
  - `hg serve --check` on the candidate: `PREFLIGHT_PASS` (release VERIFIED; trust LOADED, MAEP-1.1.0).
  - Candidate started: authenticated `/v1/health/ready` returned `READY`, then a graceful stop.
  - **Release `030a88d5` then started on the same state directory and returned `READY`**, then a graceful stop.
- **G6 status: PARTIALLY VERIFIED.** Not yet exercised: the runit cutover and restore through `switch_service.sh` (needs a staging runsvdir), and a rollback over state written by real traffic.

**G7 (WS-09), real device.**
- VERIFIED prerequisites:
  - The phone's Termux signer certificate SHA-256 is `228fb2cf…41c42`, equal to the Broker's pinned F-Droid signer.
  - CI APKs from run 43304974120 were downloaded to `~/hg-g7-realdevice-20261113` and match the CI digests (`app-debug.apk` `8eb3b9a9…`, `probe-debug.apk` `13254672…`).
- **BLOCKED:**
  - The README's positive step `content call` cannot run as the Termux UID. It needs `ACCESS_CONTENT_PROVIDERS_EXTERNALLY`; observed `SecurityException` on the phone. No Termux-side client exists.
  - Installing the APKs and tapping "Trust" need the owner on the device.
  - The APKs carry a CI debug signing identity, not a release key.
- `android/cim-broker/README.md` is corrected in this PR: it no longer describes an impossible step, and the build-tools version now matches the workflow (37.0.0).

## 56. Addendum 2026-11-13 13:26 +07 onward (owner session, stabilization VERIFY) — G4 conformance test; G6 runit drill blocked (device offline); G7/G8 admission records; G3-1 deferred

**G4 (WS-08). This PR adds `hg/tests/test_model_call_gateway.py`, under the admission recorded in §55. It adds no capability.**

Static layer, over `hg/` and `maep/` with tests excluded:
- **S1:** network imports appear only in 3 allowlisted modules, each with its reason: the transport `hg/brain/providers.py`, the `url.read` adapter `hg/tools/code.py`, and the trust-anchor reader `maep/authority/canonical_source.py`.
- **S2:** model endpoint literals appear only in `providers.py`.
- **S3:** every `.complete()` call outside `providers.py` is made on a router object.
- The 5 inference call sites are pinned: `ask`, `summarize`, `planner`, `research/options`, `research/research`.

Runtime layer, `GatewayProbe`:
- The probe counts `ModelRouter.complete` calls and makes every `ModelProvider.complete` raise unless it runs inside one.
- ask, chat (the real `ChatService` with a real `OllamaProvider` against a loopback fake), `ModelPlanner` and `Researcher` each reach the model only through the router.

Negative cases:
- A synthetic module calling `urlopen(.../api/chat)` is flagged by S1 and S2.
- A synthetic `OllamaProvider(...).complete()` is flagged by S3.
- A provider called outside the router raises before any transport call.
- **Mutation check:** making `research.py` call a provider directly fails S3 (static) and "no model call went through ModelRouter" (runtime), i.e. both layers catch it for the right reason.

Local results: 10/10 OK. The full suite is in the PR.

**G6 (WS-12): the runit drill is BLOCKED because the phone (Desktop Commander device `localhost`) was offline for this whole session (last seen about 1 h before 13:30 +07).**
- Prepared but NOT EXECUTED: the drill script, which runs entirely inside `~/hg-staging-g6-20261113`. Its steps:
  1. A staging `runsvdir` runs release `030a88d5` on port 18867, with real `deploy_smoke submit` traffic.
  2. `switch_service.sh 5fb5f2e5` (expects SWITCH_OK), then real traffic on the new release.
  3. `--restore` (expects RESTORED).
  4. Interruption drill: SIGTERM after the stop, which must produce `ROLLBACK_READY_VERIFIED`.
  5. A production snapshot before and after.
- The drill aborts if `HOME`, `PREFIX` or `SVDIR` falls outside the staging directory.
- G6 stays PARTIALLY VERIFIED on the §55 evidence.

**G7 (WS-09), admission record for a client that runs as the Termux UID:**
- **Finding:** the positive real-device call is impossible today. `content call` lacks `ACCESS_CONTENT_PROVIDERS_EXTERNALLY` (§55).
- **Root cause:** the Broker authenticates callers only through its exported ContentProvider, and Termux shell processes have no app context. They cannot open a provider client as the Termux UID.
- **Options evaluated:**
  - O1 `content`/`adb shell`: rejected. Wrong UID, or the permission is denied.
  - O2 PendingIntent creator UID: rejected. Android's security guidance says authentication must not rely on `PendingIntent.getCreator*()`, because the presenter may not be the creator. It recommends a Service or ContentProvider with `Binder.getCallingUid()`.
  - O3 termux-am / termux-am-socket: termux-app runs `am` commands in its own process, so the Binder transaction does carry the Termux UID. But broadcasts, started services and activities do not give the receiver a reliable caller UID unless the sender opts in (API 34 `getSentFromUid` with `setShareIdentityEnabled`). termux-app does not opt in; UNVERIFIED. Rejected unless a provider `call` path exists.
  - **O4 AF_UNIX socket authenticated by kernel `SO_PEERCRED`:** a Termux-side client (Python, UID 10460) talks to a Broker socket, and the Broker checks the peer UID and PID against the pairing record. The repo already has the primitive (`BrokerPeerCredentialPolicy`, and `BrokerUnixSocketClient` using `LocalSocket.getPeerCredentials()`).
    - Risks: abstract-namespace sockets have no filesystem access control, so authentication must rest on peer credentials and pairing. SELinux may deny `connectto` between two untrusted apps on Android 17; UNVERIFIED.
- **Admission decision:**
  - ADMITTED: an **on-device feasibility probe only**. It checks whether an untrusted app on this phone can accept a Termux connection and read `SO_PEERCRED`. Product code waits for a positive result.
  - If the probe needs a new APK, that comes back as its own admission to the owner.
- **Files and interfaces, if O4 later proceeds:** `android/cim-broker/app/src/main/java/org/hg/cim/broker/*` (a socket server reusing `BrokerPeerCredentialPolicy`) and a Termux-side client under `deploy/termux/`.
- **Dependencies:** the phone online; the owner installs and pairs the APKs.
- **Tests:** a positive case (the Termux UID is authenticated) and negatives (the probe UID is denied; a revoked pairing is denied), on the real device.
- **Production impact:** none.

**G8 (WS-13), admission record for the end-to-end inference → agent → tool → evidence journey (definition only):**
- **Finding:** G8 is BLOCKED and has no defined acceptance.
- **Components on main:**
  - Inference: `ModelRouter` → local `OllamaProvider`, proven to be the only model path by G4.
  - Agent: `BrainOrchestrator` + `ModelPlanner` with `check_plan` and validate-and-revise (MAEP-014), with grants issued per task.
  - Tool: `ActionGateway` → `fs.write` in `out/`.
  - Evidence: `AcceptanceGate`, the task/action ledgers and the MODEL_CALL receipts.
- **Acceptance criteria:**
  - AC1: on the staging release on the owner's phone, one objective is planned by the local model through `ModelRouter`, validated, executed by the gateway (`fs.write` in `out/`), and closed by `AcceptanceGate` with evidence. The file's sha256 must equal the evidence hash.
  - AC2: a model proposal outside scope is rejected (`PlanRejected`), with no effect and no closure.
  - AC3: the task ledger links the MODEL_CALL receipt, the action id and the evidence hash, and `hg status` reads them back.
  - AC4: offline, with no paid API.
  - AC5: production is untouched.
- **Files and interfaces:** `hg/runtime.py` (`build_runtime`), `hg/brain/planner.py`, `hg/http_api.py` (`/v1/tasks`), `hg/tools/gateway.py`, `hg/verification/evidence.py`. Which entrypoint drives `ModelPlanner` on the service path is UNVERIFIED and must be established first.
- **Dependencies:** G4 (this PR), G6 staging, the local model on the phone.
- **Production impact:** none.
- **Status:** ADMITTED, definition only.

**G3-1 (WS-04), deferred as P3:** the root-only oracle `test_sqlite_nofollow.test_rejects_directory_owned_by_another_user` has no CI coverage (it passed in the root cloud run, §55). A root CI job is deferred unless the owner raises its priority.

## 57. Addendum 2026-11-13 14:42 +07 onward (owner session, Master Autonomous Engineering & Practical Go-Live V1.0) — G6 and G8-A verified on staging; staging rehearsal tracked; G7 needs a new APK

**Directive.** The owner's mission *HG — Master Autonomous Engineering, Cleanup & Practical Go-Live V1.0* (14:42) delegates engineering, staging and qualified production deployment. The owner decision of 14:19 (G8-A approved, G8-B rejected, original G8 DEFERRED TO P4) and the stabilization rules stay in force. Production deploys only when the GO-LIVE gates pass.

**Baseline. FACT, 14:43:**
- `main` = `21c42a8`, with CI unittest 3.13/3.14 green. The only open PRs are #77 (`HOLD_BLOCKED_V1`) and #64 (`DEFERRED_V2`).
- Production on the phone runs `hg-runtime` pid 16625 on release `030a88d5` (`4eaac81`). It is READY, with integrity VERIFIED and trust LOADED.
- Production hashes:
  - run script `50a162a7…`
  - shim `d17b5c0c…`
  - pointer `6739742c…`
  - config `349c8d0a…`
- The whole Termux runit tree (runsvdir 16608, `hg-runtime`, `ollama`) started together at about 14:18, while the phone was coming back online. That restart was not an HG action. Pid 16625 replaces pid 8414 of §55.

**G6 (WS-12). VERIFIED on staging.** The runit drill ran 14:49–14:50 in `~/hg-staging-g6-20261113`, with its own runsvdir on port 18867. `HOME`, `PREFIX` and `SVDIR` were asserted to be staging before any `sv` call.
- **Candidate build:** built on the phone from `main` `21c42a8` → release `a293dc7a…`: 380 files, files_digest `b0bf7376…`, tree `0fc70ca8…`. A cloud rebuild gives the same tree and files_digest; the release id differs only by platform zlib.
- **Old release:** staging started production's release `030a88d5` → READY. Traffic task `CLOSED_VERIFIED`.
- **Switch:** `switch_service.sh a293dc7a…` → `SWITCH_OK`.
- **Restore:** `--restore` → `RESTORED`, over the state the candidate's J1/J2 traffic had written. Traffic afterwards `CLOSED_VERIFIED`.
- **Interruption:** a switch to the candidate was sent TERM after the locked state backup.
  - It exited 143 with layout ORIGINAL and run script ORIGINAL.
  - It printed `ROLLBACK_READY_VERIFIED release=030a88d5…`.
  - Traffic afterwards `CLOSED_VERIFIED`.
- **Teardown:** staging was taken down, with 0 staging processes left.
- **Production:** identical before and after (pid, 5 hashes, READY) → `PRODUCTION_UNCHANGED`.
- **Restart cycles (soak start, 14:53):** 3 controlled restarts of the candidate. Each gave a new pid, READY, a stable pid and a task `CLOSED_VERIFIED`.
- **Evidence:** on the phone, `~/hg-staging-g6-20261113/runit-drill-20261113T074911Z/`, `SHA256SUMS` sha256 `5bef6908…`.

**G8-A (WS-13). J1 and J2 VERIFIED** on the real staging service, release `a293dc7a…`, with the real local model. This shows no model planning, and the original G8 (§56 AC1–AC3) stays DEFERRED TO P4.

*J1: inference through `/v1/chat`.*
- `POST /v1/chat` returned 200, outcome ANSWERED, one MODEL sentence.
- Router `hg.brain.providers.ModelRouter`, provider `ollama`, model `qwen3:1.7b`. The pinned digest `8f68893c…` checked READY.
- The listener was VERIFIED_PROCESS (supervised ollama, pid 16623).
- Receipts:
  - MODEL_CALL `1e5778c6…`, status OK, 10.5 s.
  - ASK receipt `5eaf19e7…`, release `a293dc7a…`.
  - Both ids are in staging `asks-2026-11.jsonl`, which holds exactly these 2 events, with the same request digest `85d4f13b…`.
- The tasks, actions and memory ledgers and `out/` were unchanged before and after, so no action was taken.

*J2: controlled execution through `/v1/tasks`.*
- One pre-authored step, `fs.write` to `out/deploy-smoke-G8AJ2-…txt`.
- Lifecycle: DRAFT → READY → ASSESSED → PLANNED → AUTHORIZED → RUNNING → VERIFYING → ACCEPTED → CLOSED_VERIFIED.
- The grant was issued from `owner-manifest:21c42a8` (`EV-41d853bb618a`).
- Action `…:S-1:3` SUCCEEDED. The intent sha256, the observed sha256 and the sha256 of the file on disk all equal `081505f1…` (41 bytes).
- AC-READBACK PASS (`EV-fbbfbfacabc6`), `GATE-AC-READBACK` PASS, candidate_ref `sha256:fcddcd62…`, closure recorded.
- Replay returned 200 with the same result; a changed body returned 409.

*Safety of the J2 path.* The `deploy_smoke submit` path was read in full first. It only talks to 127.0.0.1 on the port of `HG_SERVICE_CONFIG`, only on `/v1/health/ready` and `/v1/tasks`, and has no deploy code.

**Tracked staging rehearsal (this PR, P2 / WS-10 and WS-12).**
- **Admission:**
  - *Finding:* the G6/G8-A evidence came from ad-hoc scripts on the phone, so the rehearsal that the mission's production protection requires before a production switch cannot be repeated from the repository.
  - *Root cause:* `deploy/termux` holds only production scripts. `switch_service.sh` derives `SVDIR` from `PREFIX`, and the owner's Termux shell exports a production `SVDIR`, so a staging run depends on undocumented overrides.
  - *Why no existing PR fits:* only #77 and #64 are open, and both are on hold.
  - *Files:* `deploy/termux/staging_rehearsal.sh`, `deploy/termux/staging_probe.py`, README step 3b, `hg/tests/test_staging_rehearsal.py`.
  - *Dependencies:* none.
  - *Production impact:* none; production is only read.
- **Tests:** 12 new tests. The module fails without the change.
- **Local suites:** HG 1001 OK (6 skipped), MAEP 385 OK, hooks 42 OK, selfcheck PASS, bench 0.
- **On the phone, from commit `2d49dca`**, 5 refusals exited 2 and created nothing: the production port, an existing dir without the marker, a dir inside `~/.config/hg`, a port in use, and `$HOME` itself.
- **First full run (`2d49dca`): REHEARSAL_FAIL**, which the rehearsal is built to report.
  - *Root cause:* a fresh staging dir had no `state_dir`, and `hg serve` refuses to start without it (`hg/service.py`: it must exist with mode 700). `./finish` then held the staging service down after 5 short runs.
  - *Side effect:* that hold-down calls the real `termux-notification` ("HG đã dừng"), so the owner's phone may have shown a notification at about 15:13. It came from staging.
  - Teardown left 0 processes, and production was UNCHANGED.
  - *Fix (`bffea5f`):* the rehearsal creates `state_dir` 0700 and clears the staging finish counter. No-op stubs for `termux-notification` and `termux-wake-lock` go first on the staging PATH and log to `device-calls.log`.
- **Second fix (`07b07d6`):** the J2 check now proves that the gateway's observed sha256 equals the file on disk, as README step 3b states.
- **Final run (`07b07d6`, scripts sha256 `cfb530bd…` / `b11120a7…`, `~/hg-staging-rehearsal-20261113`, port 18868): REHEARSAL_PASS.**
  - The production release was rebuilt in staging and reproduced `030a88d5`.
  - Results: `SWITCH_OK`; J2 `CLOSED_VERIFIED` with `observed_matches_file=true` (`6725f47b…`); J1 ANSWERED with no task or action (MODEL_CALL `f8cf6a65…` OK, ASK `8883b0ba…`, release `a293dc7a`); `RESTORED`; `ROLLBACK_READY_VERIFIED`; production UNCHANGED.
  - `device-calls.log` holds only the 4 wake-lock calls, caught by the stub. No notification was sent.
  - Evidence: `rehearsal-20261113T081922Z/`, `SHA256SUMS` sha256 `5f70498d…`. The failed run is kept as `rehearsal-20261113T081219Z/` (`602caefb…`).
  - A full rehearsal used 16 of the phone's 60 GitHub calls per hour.

**G7 (WS-09). O4 feasibility with existing code: BLOCKED (owner).**
- The Broker has an AF_UNIX *client* only (`BrokerUnixSocketClient`, used to reach its Ollama socket). No existing APK accepts a Termux connection.
- The Broker and probe APKs are not installed (packages present: `com.termux`, `com.termux.boot`, `com.termux.api`).
- On Android 17 as `untrusted_app_27`, a same-UID abstract socket reads `SO_PEERCRED` on both sides (uid 10460).
- Cross-UID `connectto`: UNVERIFIED. It needs a new probe APK, which needs its own owner admission (§56), and the owner's install and pairing on the device.

**Gates:**

| Gate | Status |
|---|---|
| G1 | VERIFIED (§53, decision C) |
| G2, G5 | BLOCKED, accepted for v1 (D2) |
| G3 | VERIFIED; G3-1 deferred (P3) |
| G4 | VERIFIED (#195) |
| G6 | VERIFIED (staging; repeatable with `staging_rehearsal.sh`) |
| G7 | BLOCKED: owner admission of a probe APK, install and pairing, release signing key |
| G8-A | VERIFIED (J1 + J2, staging) |
| G8 (original) | DEFERRED TO P4 |

**Soak.** A 24 h target runs on staging (`~/hg-staging-g6-20261113/soak-*`, candidate `a293dc7a`, port 18867).
- Every 30 minutes it runs a traffic task, and every 3 hours a J1.
- A tick is skipped while the phone's GitHub quota is below 30, to keep quota for production.
- Its observed duration is recorded when it ends. No long-term stability is claimed before then.

**Production:** unchanged on `030a88d5`, VERIFIED. Candidate `a293dc7a` is NOT deployed. G7 is open, and GO-LIVE acceptance is the owner's.

## 58. Addendum 2026-11-17 23:52 +07 onward (owner session, Autonomous Stability Engineering & Production Reliability Mission V1.0) — soak 3 forensics, production availability, RF-1 restart forensics

**Directive.** The owner's mission *HG — Autonomous Stability Engineering & Production Reliability Mission V1.0* (2026-11-17 23:52) asks for system truth first, root causes of the soak 3 gaps, and fixes with evidence. The stabilization rules and the P2 decision of 2026-11-13 17:00 stay in force: no production deploy before a qualifying 24 h soak and the GO-LIVE gates.

**Baseline. FACT, 2026-11-17 23:53–23:58 +07:**
- `main` = `4a4cb37` (#196), CI green. Open PRs: #77 (HOLD), #64 (DEFERRED_V2) — unchanged.
- Production `hg-runtime` pid 27786 on release `030a88d5` (`4eaac81`), READY with integrity VERIFIED, trust LOADED (trust commit `4a4cb37`), idempotency USABLE; Ollama `qwen3:1.7b` (`8f68893c…`). The whole runit tree had started at 23:37:41, about 15 min before the session; that start was not an HG action.
- `~/HG` is on `stt/hg-h1.3.1-idempotency-progress` @ `2a80f4f` with 3 modified files and untracked `docs/governance/`; 33 worktrees. All preserved, none touched.

**Soak 3 (`soak3-20261114T180602Z`, candidate `2961f50d…` from `4a4cb37`). Verdict stays INCOMPLETE.** The 49 "missing" ticks (77 expected − 28 ticks) decompose as follows:
- 29 are an artefact of the driver's verdict: it counts expected ticks over the whole 38.9 h until it was resumed, while the driver correctly stops ticking at its 24 h target. Within the target window 48 ticks were due.
- ≈17.8: the whole Termux process tree was gone from ≤ 2026-11-15 16:13 +07 (09:13:23Z, last line of an independent agent log; last tick 15:51) until 2026-11-16 16:00 +07. The soak driver, the remote agent and production all stopped; production came back with a new pid (18288 → 26406). Whether Android killed Termux or the phone rebooted: UNKNOWN — no boot id was recorded at the time.
- ≈3.5: ticks 18→22 (2026-11-15 09:03–12:49 +07) took 48–62 min instead of 30. The driver sleeps in CLOCK_MONOTONIC, which does not run while the CPU is suspended or the process is frozen: SUSPECTED suspend or freeze despite the Termux wake lock; not measurable with the tools of that run.
- "Recoveries" 1–2 (2026-11-15 01:30) were `sv down hg-staging-soak` while the runit soak service was being installed, not Termux restarts; recovery 3 (2026-11-16 16:00) was a real restart. The driver lock worked: the second driver waited (`another driver holds the lock`).

**Production availability. CONFIRMED, P0.** Between 2026-11-15 00:59 and 2026-11-17 23:55 +07 (70.9 h) production was without Termux for ≥ 55.3 h:
- 23.8 h: 2026-11-15 16:13 → 2026-11-16 16:00 (above).
- 31.5 h: the phone rebooted at 2026-11-16 16:08:44 +07 (CLOCK_BOOTTIME 114388 s at 23:55; staging's start marker holds boot `0f39cb3e…` at 16:00:03, the current boot is `1b823ef0…`). Termux:Boot (`com.termux.boot` installed, `~/.termux/boot/00-start-services` present) did not bring the services back: nothing ran until 2026-11-17 23:37:41.
- Since that boot the CPU was suspended 51686 s of 114388 s (CLOCK_BOOTTIME − CLOCK_MONOTONIC).
- HG itself recorded none of it: the runit log holds one start line per life and `hg-runtime.started` is overwritten at each start.
- Root cause outside HG: Android/ColorOS process and autostart policy for Termux and Termux:Boot. From Termux these settings cannot be read (`dumpsys` and `cmd appops` refuse uid 10460): **owner device action** — allow auto-launch and unrestricted background/battery for Termux and Termux:Boot, open Termux:Boot once, then reboot and check that `hg-runtime` starts without opening Termux.

**RF-1 restart forensics (this PR, P1 / WS-03, WS-10).**
- **Admission:**
  - *Finding:* production downtime of 55 h was invisible to HG; soak gaps could not be attributed.
  - *Root cause:* no liveness record survives the process; the only start marker is overwritten and carries no end time.
  - *Why no existing PR fits:* only #77 and #64 are open, both on hold.
  - *Files:* `hg/liveness.py` (new), `hg/service.py` (start, heartbeat thread, stop reason), `hg/__main__.py` (`hg availability`), `hg/tests/test_liveness.py`, deploy README, this section.
  - *Dependencies:* none (stdlib; `CLOCK_BOOTTIME` where available).
  - *Production impact:* none until a release with it is deployed through the gates; then two small private files in the state dir (≤ 16 KiB heartbeat, ≤ 2 × 64 KiB records) and one write per minute. No readiness, auth, idempotency, ledger or gateway behaviour changes.
- **Behaviour:** start record classifies the previous end as `CLEAN_STOP`/`ERROR_EXIT`/`DEVICE_REBOOT` (CONFIRMED), `UNCLEAN_END_SAME_BOOT` (SUSPECTED), or `FIRST_START`/`PREVIOUS_UNREADABLE`/`UNCLEAN_END_UNKNOWN_BOOT` (UNKNOWN); downtime after an unclean end is an upper bound; suspend inside a same-boot gap is measured from kernel clocks; stalls split measured suspend from suspected freeze; `since_boot_s` shows how long after a boot HG came back. `hg availability` reports `unobserved_s` and never counts it as uptime.
- **Tests:** `hg/tests/test_liveness.py`, 18 tests, including `hg serve` itself under SIGTERM. Before the `hg/service.py` change the serve test failed for the expected reason (no `HG_RESTART_FORENSICS` line).

**Not done here:** the soak driver's verdict formula lives in the staging directory, not in the repository; the next soak bounds expected ticks by its target and takes unobserved time from `hg availability`. Production stays on `030a88d5`.

## 59. Addendum 2026-11-18 00:20 +07 onward (owner session, same mission) — RF-1 verified on the phone, soak 4 started, §58 correction, RF-2 restart recovery

**Correction to §58.** The owner stated on 2026-11-18 01:13 that the owner closed the app before the 2026-11-16 restart. The 31.5 h outage that began with the reboot at 16:08:44 is therefore an owner action, not an Android kill. HG still did not come back without Termux being opened by hand, because Termux:Boot did not run. The 23.8 h outage from 2026-11-15 16:13 stays UNKNOWN. The owner's screenshot also shows Termux on "Cho phép hoạt động dưới nền" (unrestricted background), so that setting is not the cause. Auto-launch for Termux:Boot remains UNVERIFIED.

**RF-1 (#198, `main` `804bcb5`, CI green) — evidence on the phone:**
- **Build:** release `7c9aa9de…`, built twice on the phone with an identical result: 385 files, files_digest `e86d3882…`, tree `76b3df45`. Both equal the cloud build; the cloud release id `b106c9d5…` differs only by platform zlib.
- **Rehearsal — `REHEARSAL_PASS`.** `staging_rehearsal.sh` from the candidate's own checkout, port 18868, `rehearsal-20261117T171936Z`, SHA256SUMS `0475a0db…`:
  - production release `030a88d5` rebuilt in staging → `SWITCH_OK` → J2 `CLOSED_VERIFIED` (`observed_matches_file`) → J1 `ANSWERED_NO_ACTION` → `RESTORED` → `ROLLBACK_READY_VERIFIED`;
  - production UNCHANGED.
- **Kill drill on staging (`rf1-drill-20261117T172259Z`, SHA256SUMS `3bc754a9…`):**
  - SIGKILL → the next start recorded `UNCLEAN_END_SAME_BOOT` SUSPECTED, `downtime_max_s` 27.5, `suspended_s` 0.
  - SIGTERM → `CLEAN_STOP` CONFIRMED.
  - `since_boot_s` matches the boot of 2026-11-16 16:08:44.
- **Soak 4 (`soak4-20261117T172516Z`, driver `g_soak4.sh` sha256 `07d7e025…`):**
  - It switched staging from `2961f50d` to `7c9aa9de`, a real upgrade between two different releases.
  - 3/3 restart cycles OK; forensics `{FIRST_START: 1, CLEAN_STOP: 3}`.
  - Tick 2 OK and J1 OK.
  - It runs until about 2026-11-19 00:25 +07; verdict NOT YET (in progress).
  - The previous service run and boot script are backed up in `backup-20261118/`.
- **Production:** `030a88d5` pid 27786, READY. Its 4 hashes equal §57. Not deployed.
- **Not done:** a JobScheduler guard (job 4211; start the existing boot script only when the production runsvdir is absent) was refused by the session's permission system. It is left to the owner.

**RF-2 restart recovery (this PR, P1 / WS-03).**
- **Admission:**
  - *Finding (reproduced with real `os._exit` in a child process):*
    - **D1:** a death after the task became RUNNING (before ACTION_STARTED, inside the effect window, or after ACTION_COMPLETED) leaves it RUNNING for good, because no method continues a RUNNING task.
    - **D2:** `reconcile_and_reopen` on such a task recorded `ACTION_RECONCILED`, cleared the pending marker, and then failed because reopen needs BLOCKED. The result was a half-recovery with no marker left.
    - **D3:** with `issue_task_grants=True` (the `hg serve` configuration) per-task grants live only in memory, so after a restart no BLOCKED task could be reopened: the authority check had nothing to allow. This includes tasks blocked before a restart.
  - *Root cause:* restart rebuilt the pending actions but not the task state; the state table rule "if state is unknown, remain BLOCKED" was not applied at start.
  - *Why no existing PR fits:* only #77 and #64 are open, both on hold. The WS-04 cross-store contract stays BLOCKED_SOURCE (§53).
  - *Files:* `hg/brain/orchestrator.py` (`recover_interrupted(task_ids)`, state check before reconcile, re-issue at reopen), `hg/runtime.py` (`build_runtime(recover_interrupted=False)`, `recovered`), `hg/service.py` (the service passes `recover_interrupted=True`; `HG_RECOVERED_INTERRUPTED` start line), `hg/tests/restart_crash_child.py`, `hg/tests/test_restart_recovery.py`, `CLAUDE.md`. No `maep/` change.
  - *Dependencies:* none.
  - *Production impact:* none until deployed. The production state holds 7 tasks, all CLOSED_VERIFIED, 0 RUNNING, 0 pending, so recovery changes nothing there.
- **Behaviour:**
  - When `hg serve` starts (`recover_interrupted=True`; off by default for other callers, e.g. tests that drive a RUNNING task across rebuilt runtimes), each RUNNING task of the current policy moves RUNNING → BLOCKED (an allowed edge). Tasks of an earlier policy stay read-only history (MAEP-012). With a pending action it is blocked as UNKNOWN, with next action "reconcile action X"; without one it is blocked as INTERRUPTED.
  - Nothing is executed, reconciled or replayed at start, and the gateway still refuses every effect while an action is pending.
  - Reopening re-issues grants from the live owner manifest, as `authorize()` does. If the manifest is unavailable or no longer permits the plan, nothing is issued and the task stays BLOCKED.
- **Crash-point matrix (mission VIII.4):**

| Crash point | Covering test(s) |
|---|---|
| Before the start record | `before-start` (new) |
| After the start record, before the effect | `before-effect` (new) |
| After the effect, before the completion record | `after-effect` (new) |
| After the completion record | `after-completion` (new) |
| HTTP receipt before finish / at commit | `test_http_idempotency_lifecycle` CrashWindowTests (existing) |
| Torn final task event | `test_task_store_restore` (existing) |

- **Tests:** `hg/tests/test_restart_recovery.py`, 10 tests, including `hg serve` itself.
  - Against unchanged `main` code, the first 8 failed for the expected reasons: RUNNING ≠ BLOCKED; `ACTION_RECONCILED` recorded before the refusal; no `recovered` attribute; no start line.
  - `before-start` and the opt-in test were added after the fix.
  - The first full run of the fix broke three existing tests: the exact public API of TaskStore, a STALE (MAEP-012) RUNNING task, and a control test that executes a RUNNING task through a rebuilt runtime. The change was narrowed (no TaskStore API, STALE skipped, opt-in flag) instead of editing those tests.
- **Resources (production, read-only, ≈01:25):** state 219 KB (tasks 52 KB, idempotency SQLite 37 KB + WAL 37 KB); runit logs 192 KB (hg-runtime) and 460 KB (ollama), bounded by svlogd; `hg serve` RSS 9.8 MB and Ollama 16.7 MB idle, CPU 0 %; disk 293 GB free.
- **Network (VII.E), by design:** without GitHub the trust root is unavailable. Start and task authority fail closed (RT-06), and the earlier `test_unavailable_trust_root_blocks_preflight` stays. This is not relaxed.


## 60. Addendum 2026-11-18 04:00–05:03 +07 — full-system stability audit, candidate verification and test-harness repair

**Mission and safety boundary.** Executed the owner's full-system stability mission against OAI-GIANG/HG only, on OPPO PKC110 / Android 17 / Termux ARM64. Production was read-only throughout. No release switch, production restart, production deploy, state migration, task/ledger deletion, or mutation of the owner's pre-existing dirty worktree was performed.

**Git baseline.**
- origin/main at audit start: bad9bf4e538d669433793f86b10e734ba18a8c18 (PR #199 RF-2).
- Owner's ~/HG: branch stt/hg-h1.3.1-idempotency-progress, HEAD 2a80f4f26fdb6202d581febfe2922468172e398c; original working tree remains dirty with modified hg/assistant/cli.py, hg/assistant/config.py, hg/brain/providers.py, and untracked docs/governance/. The 33 pre-existing worktrees were preserved.
- Candidate repair branch fix/http-parse-oracle-close-20261118, commit 0de34ec81dd250640a81b212cd0e61406160387e, is a separate worktree based directly on bad9bf4. One test-only file changed. The branch was pushed. Opening a PR through the connected GitHub integration returned HTTP 403 Resource not accessible by integration; no permission workaround was attempted. GitHub compare confirmed the branch is exactly one commit ahead of main, with no other files changed. No PR or CI run is claimed.

**Production and candidate runtime.**
- Production remains on release 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5, runtime PID 27786.
- Staging candidate remains on release aee6efe4a9204de6aa12ed25be8e73b04a6107f3bb393cbafc417878fe480519, built from commit bad9bf4e538d669433793f86b10e734ba18a8c18.
- Final authenticated readiness at approximately 05:02 +07: both returned HTTP 200 with status READY, integrity VERIFIED, trust LOADED, idempotency USABLE, repository OAI-GIANG/HG. These are readiness checks, not a long-term stability verdict.
- The 5 production config/pointer hashes from the Soak 5 pre-switch baseline were rechecked and all matched. Production release, service scripts and pointers remained unchanged.
- Read-only health checks: production 7 CLOSED_VERIFIED tasks, 7 SUCCEEDED actions, 0 pending actions, 7 memory records, 0 conflicts; staging 58 CLOSED_VERIFIED tasks, 58 SUCCEEDED actions, 0 pending, 58 memory records, 0 conflicts.

**RF-1/RF-2 and soak.**
- PR #198 RF-1 and PR #199 RF-2 are merged. Their head commits both had MAEP tests and rt06-trust-anchor-tests workflow runs completed successfully. Candidate release contains both.
- Candidate RF-1 liveness reported ALIVE, 179 heartbeats, 0 stalls and unobserved_s=0 at the direct observation. Staging soak records three controlled restarts successful.
- Soak 5 (soak5-20261117T184629Z) remains IN PROGRESS, not PASS. Snapshot at 04:48:33 +07: 7 ticks, 6 executed OK, 0 failed, 1 quota skip (GitHub quota below 30), PIDCHG=0, ENVREC=0, ENVFAIL=0, OPSTOP=0, REBOOTS=0, J1OK=1, J1FAIL=0, RCOK=3. RSS sample increased from 41120 KB to 41756 KB. Last completed tick was 04:48:33 +07. Twenty-four-hour target ends 2026-11-19 01:46:30 +07. Do not infer PASS before the target and evidence reconciliation.
- Soak 4 remains INCOMPLETE/SUPERSEDED; its gaps were not retroactively reclassified.

**Backend, Brain, Memory, ModelRouter and execution.**
- Candidate actual /v1/chat J1 used local Ollama qwen3:1.7b, returned HTTP 200 and the answer “Một tuần có 7 ngày.”; model call/ASK receipts were generated and no task/action side effect occurred.
- Source inspection confirmed runtime.py wires MemoryStore into BrainOrchestrator; execute_goal() builds context through build_context(..., memory=self._memory), and build_context searches SEMANTIC/PROJECT/EPISODIC memory. The HTTP /v1/chat route is a distinct assistant Notebook/notes path that invokes ModelRouter with the local provider; it does not directly call the core BrainOrchestrator MemoryStore/TaskStore/ActionGateway path. This boundary is by current architecture and must not be described as universal conversational memory injection.
- Candidate selfcheck PASS for its three fixture scenarios. It explicitly retains RT-06 limitation: selfcheck grants are fixtures not anchored to trust root; verifier checks are internal, not independent review. Candidate hg bench: 10/10 cases PASS, zero unauthorized effects and zero false closures.
- PR #77 remains OPEN/HOLD: listener attestation / runtime ownership / provenance and device-level evidence not complete. No false closure.

**Test evidence on Termux Android ARM64 / Python 3.14.8.**
- Full MAEP discovery: 385 tests, PASS, 3 platform skips.
- Full HG discovery: 1,030 tests, PASS, 3 platform skips.
- Full Claude hooks discovery: 42 tests, PASS.
- Total: 1,457 tests executed by the three full discovery suites; no FAIL or ERROR. Six skips are platform constraints (hard-link creation and root-only ownership changes).
- Separate targeted groups also passed: release/evidence/policy/storage 93 (1 skip); acceptance/anchored runtime/gateway/planner/providers 92; HTTP API/idempotency/deadline/parse/security 66; previous focused component groups included RF-1/RF-2, model gateway, memory, chat, and router oracles.
- A test-harness leak was isolated: claimed_keys() in hg/tests/test_http_request_parse_oracle.py used SQLite's transaction context manager without closing the connection. The patch now uses contextlib.closing. Before the patch the parse oracle passed but emitted 34 unclosed-database warnings; after the patch its 6 tests passed under -W error::ResourceWarning, 0 warnings. The related HTTP regression set passed 66/66 under the same strict warning policy, 0 warnings.
- Full HG discovery still emitted 114 ResourceWarning lines across other test fixtures (temporary directories, sockets and file handles); it nevertheless reported OK. These were not all fixed in this pass and must remain visible as test-harness cleanup debt, not hidden or attributed to production without reproduction.

**Task integrity, backup and rollback.**
- Candidate IdempotencyStore/SQLite tests cover concurrent duplicate requests, crash windows, IN_DOUBT, inode replacement, symlink rejection and WAL behaviour. The strict 66-test HTTP regression suite passed after the test-only connection close fix.
- The Soak 5 staging switch captured a state copy under the live writer lock at switch-20261117T184637Z/state: 58 files, approximately 907 KB. Its state.sha256 was independently checked; all files matched.
- switch_service.sh implementation has explicit --restore/--restore-state paths, rollback trap, state and run-script layout checks, authenticated READY and stable-PID checks. Earlier staging rehearsal evidence in §57 already records RESTORED and ROLLBACK_READY_VERIFIED. No destructive rollback was triggered against the active Soak 5 service in this audit.

**Android supervisor guard and limits.**
- Existing on-device guard $HOME/.local/bin/hg-supervisor-guard.sh SHA256 e2bc63ff2581ed00d67e5918cd571322721191535cad7dedea8048f55d3e5acc; corrected /proc/<pid>/cmdline detection reports CHECK_OK for production runsvdir PID 27747. The retired v0 ps -A false negative and one boot-script invocation are retained in the guard log; production HG runtime PID 27786 was unchanged by that test. Corrected guard did not invoke boot script while supervisor was present.
- JobScheduler job 4211 was registered with 900000 ms period and persisted; temporary network=any readback confirmed registration, then configuration was restored to network=none. Termux:API 0.53.0 on Android 17 did not provide usable pending readback for the network-none state (issue #923). Guard log shows checks recurring at 04:18, 04:32 and 04:47, but periodic execution is not independently attributed to Job 4211. Status: QUALIFIED, not VERIFIED.
- Android/ColorOS autostart and battery-policy settings could not be inspected from Termux UID; device-level owner confirmation/reboot test remains outstanding.

**UI scope.**
- The canonical release contains hg/ui/app.js, index.html, styles.css (web UI); JavaScript syntax and UI contract tests pass.
- No Flutter .dart sources, pubspec.yaml or pubspec.lock were found in the candidate release/repository. No Flutter SDK, Chromium, Playwright, Selenium or jsdom is available on the device. Native Flutter UI/browser E2E therefore remains BLOCKED / NOT PRESENT, not VERIFIED.

**Performance.**
- Available short-window candidate RSS samples: 41120–41756 KB over the observed early soak interval. Device had about 293 GB free disk and 4.7 GB MemAvailable at 05:00 +07. This is not a battery/thermal/long-duration performance qualification. No full sustained CPU/battery measurement is claimed.

**Disposition.**
- Overall verdict: INCOMPLETE (with verified subsystems and accepted evidence above). Production remains on 030a88d5; candidate is staging only.
- P0/P1 data integrity and restart recovery candidate tests passed, but GO-LIVE is not accepted while Soak 5 is incomplete and RT-06 / PR #77, JobScheduler readback, device boot/autostart proof, Flutter source/E2E and remaining test-harness resource warnings remain unresolved.
- Next actions: let Soak 5 reach its 24 h target without intervention; reconcile every expected/missing/skipped tick and liveness interval; independently verify JobScheduler/guard persistence and Android boot recovery; resolve RT-06/PR #77 on its own evidence; determine whether Flutter app sources belong in this canonical repo or formally classify web-only UI; clean the remaining test harness resource warnings; only then consider candidate acceptance and a separate GO-LIVE decision. Production must remain untouched until those gates pass.


## 61. Addendum 2026-11-18 05:18–05:46 +07 — deterministic resource cleanup and full strict regression

**PRs merged before this change.**
- PR #200 (test(http): close read-only SQLite oracle connections) merged as 484a83d8c6bc097aecf2559882e59e8123f3e8db.
- PR #201 (docs(governance): record full-system stability audit) merged as d3ef3575f51206530306e0bd375dbc9b7a788381; §60 is now on main.
- Both PRs had MAEP tests and RT-06 trust-anchor CI jobs pass for Python 3.13 and 3.14. Main at the base of this change is d3ef3575f51206530306e0bd375dbc9b7a788381.

**Additional concrete resource leaks found and fixed in branch fix/resource-cleanup-20261118.**
1. hg/tests/test_context_budget_fence_oracle.py: two 11-case loops repeatedly called setUp(), replacing TemporaryDirectory instances without cleanup. Each loop now uses a new MemoryStore JSONL path under the existing test fixture.
2. hg/tests/test_assistant_ask.py: the proxy-isolation test shut down a local HTTP listener but did not join its serving thread or close the server socket. Cleanup now follows shutdown → join → server_close.
3. hg/tests/test_eval_resumable.py: FakeOllama similarly did not join its thread or close its HTTPServer. Added an explicit close() lifecycle and registered that cleanup instead of only server.shutdown(). The two residual socket warnings seen in full-suite discovery were traced to these fake Ollama sockets (ports 37127 and 34373).
4. hg/tests/test_finish_script.py: reading /proc/sys/kernel/random/boot_id with open(...).read() left the file handle unclosed; now uses Path.read_text(encoding="ascii").
5. hg/tests/test_test_run_output_oracle.py: two child PID reads did not close their file handles; now use Path.read_text. Two repeated subtests also recreated fixtures by calling setUp() from within the test and manually invoking tearDown(), losing the original temporary-directory ownership. They now use a scoped TemporaryDirectory per subtest while preserving the original fixture path.
6. hg/tools/code.py: UrlReadAdapter handled HTTP 3xx/other HTTP errors by converting HTTPError to AdapterFailure without closing the error response object. It now closes the HTTPError response body/socket before raising the known failure. Redirect and error semantics are unchanged.

**Verification on OPPO PKC110 / Android 17 / Termux ARM64 / Python 3.14.8.**
- Full HG discovery with warnings promoted to errors: python3 -W error::ResourceWarning -B -m unittest discover -s hg/tests -t . -v → 1,030 tests, OK (skipped=3), runtime 392.733 s. ResourceWarning count 0; FAIL count 0; ERROR count 0.
- Full MAEP discovery → 385 tests, OK (skipped=3).
- Full Claude hooks discovery → 42 tests, OK.
- Aggregate: 1,457 tests pass; 6 environment-dependent skips; no failed/error tests. The HG suite was run with ResourceWarning treated as an error. MAEP/hooks had no observed warnings.
- Focused tests for the touched areas also pass: context 9; assistant 33; finish 8; EvalResumable 2; evidence store 12 (one hard-link platform skip); test.run output 10; URL redirect 5; URL content 12; strict HTTP/API/deadline/idempotency/parse/SQLite-security 66. All touched resource-lifecycle focused suites showed 0 ResourceWarning. git diff --check passed.
- The prior parser cleanup from PR #200 is inherited from main; strict HTTP regression was re-run on top of the new main and again passed 66/66 with 0 warnings.

**Scope and safety.** This is a code/test cleanup branch plus this ledger record. It did not touch ~/HG original dirty checkout, production state, service pointers, active staging files, Soak 5, TaskStore, Memory, Knowledge, or user data. No release build/switch/deployment occurred.

**Operational status remains unchanged.**
- Production is still on 030a88d5…; staging candidate aee6efe4… remains candidate-only.
- Soak 5 last observed tick 8 at 2026-11-18 05:18:43 +07: 7/7 executed OK, 1 quota skip, 0 failed, 0 process/env recovery or operator stop, J1 2/2 OK, RCOK=3, RSS baseline 41120 KB and last sample 43116 KB. Twenty-four-hour target is still 2026-11-19 01:46:30 +07. Do not infer PASS from this short observation.
- RT-06 / PR #77, Termux:Boot/JobScheduler device proof, Flutter native source/E2E scope, sustained battery/performance, and a real candidate-to-previous-release rollback rehearsal remain open. No GO-LIVE decision is made.

**Disposition.** Resource-warning cleanup is VERIFIED on the complete HG test suite under strict warning mode. This does not upgrade system-level verdict: overall remains INCOMPLETE until Soak 5, trust, boot/autostart, UI-scope and release gates are satisfied.

## 62. Addendum 2026-11-18 05:54–05:56 +07 — post-PR #202 candidate integration rehearsal

**Candidate and reproducible build.**
- Main after PR #202: 6f6cb96d3120c4d06a7d6def3b37a1953a448d60.
- Built candidate release from this exact main commit in a third isolated staging root: 6e6f5f288f88f5d03519875ad5fed4da84006f72db56c67c487d65be03c275b8; 387 files, tree 490bacb70eed9d1315e6b6a1d364f4cf0c712ae7, files_digest f0e6b944b866ca6ace2cf582ea6b40aa2d1ede40ff53d6f86856af1133d79fe0; build repeated twice, archive/manifest matched and release verification passed.
- Production release 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5 was independently rebuilt in that isolated staging root from manifest commit 4eaac81132ae57028cf2432eec911a01b6ecf1fd; exact release ID reproduced, build verified and installed/sealed.

**Isolated staging environment.**
- Directory $HOME/hg-staging-postmerge-20261118, its own HOME, PREFIX, SVDIR, runsvdir, token and state; port 18869. staging_probe.py guard returned STAGING_GUARD_PASS; port-free preflight passed; directory was absent before the rehearsal. This directory did not overlap production or the active Soak 5 staging root.
- The owner's dirty ~/HG worktree was not used or modified.

**Real end-to-end rehearsal (REHEARSAL_PASS).**
- Authenticated readiness of the staging instance on the old production release succeeded.
- Traffic R0: HTTP 200, task DEPLOY-SMOKE-R0-20261117T225455Z CLOSED_VERIFIED, readback matched; idempotent replay returned same result, changed payload returned 409 conflict.
- Switch to post-merge candidate: SWITCH_OK; candidate authenticated READY on the expected release with trust commit 6f6cb96.
- J2: task DEPLOY-SMOKE-J2-20261117T225455Z, HTTP 200, CLOSED_VERIFIED; ActionGateway observed_sha256 exactly matched the on-disk file SHA256 5dbf1db47c5f140c273133beaa5703edb228a5bc000c11629f9a03e35dfefe37 (38 bytes); replay and changed-payload conflict controls passed.
- J1: /v1/chat HTTP 200, outcome ANSWERED, no_task_or_action=true.
- Restore from candidate to old production release: RESTORED; authenticated READY on release 030a88d5; traffic R1 passed.
- Controlled TERM interruption after stop/backup: switch exited 143, classified state/run script ORIGINAL, restored and restarted the old release, authenticated READY with a stable supervised runtime; ROLLBACK_READY_VERIFIED release=030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5.
- Traffic R2 after interrupted rollback: HTTP 200, CLOSED_VERIFIED, readback/replay/409 controls passed.
- Final result line: switch=SWITCH_OK j2=CLOSED_VERIFIED j1=ANSWERED_NO_ACTION restore=RESTORED interruption=ROLLBACK_READY_VERIFIED production=UNCHANGED last_step=done; final REHEARSAL_PASS.

**Production and concurrent Soak 5 safety.**
- Production before/after snapshots contain 8 fields/records excluding label and compare byte-for-byte identical. Release remained 030a88d5, PID 27786; authenticated readiness HTTP 200, integrity VERIFIED, trust LOADED, idempotency USABLE.
- Active Soak 5 was not switched, stopped or modified: staging release remained aee6efe4, PID 26963; authenticated readiness HTTP 200 and Soak 5 driver remained on its own port/SVDIR.
- Rehearsal teardown reported staging processes left: 0; independent process search found no process under hg-staging-postmerge-20261118.
- Rehearsal evidence directory: $HOME/hg-staging-postmerge-20261118/rehearsal-20261117T225455Z/. The script initially computed SHA256SUMS before its final two log lines were appended; checksum list was regenerated only after the run had completely ended, then all 24 files independently verified OK. The production before/after snapshots were also independently compared and identical.
- This rehearsal is staging qualification of the post-merge code path, not a production deployment and not the 24-hour Soak 5 result.

**Remaining gates and verdict.**
- The post-merge candidate has a verified staging switch / restore / interrupted-switch recovery / real local model J1 and J2 flow. This closes the outstanding practical post-merge staging rehearsal evidence for this candidate.
- Soak 5 remains IN PROGRESS and must reach its 24-hour target and have all expected/missing/skipped ticks reconciled.
- PR #77 / RT-06 listener attestation and independent trust provenance remain HOLD/BLOCKED; device reboot/autostart/JobScheduler recurrence remains not fully verified; Flutter native source/E2E remains absent from the canonical repository; sustained battery/performance qualification remains open.
- Production remains on 030a88d5. No GO-LIVE decision or production deployment is made. Overall system verdict stays INCOMPLETE.

## 63. Addendum 2026-11-18 05:59–06:05 +07 — post-merge web UI E2E and JobScheduler offline probe

**Web UI end-to-end on the post-merge candidate.**
- Installed jsdom 26.1.0 into the private audit cache at $HOME/.cache/hg-audit-v1/ui-smoke-jsdom (17 MB); no package/dependency was added to OAI-GIANG/HG or any release.
- Reused the completed isolated staging root from §62, started its own runsvdir/service on port 18869 with the candidate release 6e6f5f288f88f5d03519875ad5fed4da84006f72db56c67c487d65be03c275b8. Production and Soak 5 were untouched.
- Ran the canonical deploy/termux/ui_smoke.mjs against the live staged /ui/ page:
  - report result PASS; page title HG — trợ lý trên điện thoại (OAI-GIANG/HG);
  - service badge SẴN SÀNG; authenticated GET /v1/health/ready returned HTTP 200;
  - UI Send action posted authenticated /v1/chat and received HTTP 200, outcome ANSWERED, label MODEL;
  - displayed answer: “Thủ đô của Việt Nam là Hà Nội.”;
  - provider ollama, model qwen3:1.7b, pinned digest status READY; Ollama listener VERIFIED_PROCESS; ModelRouter model call status OK, input_tokens=329, output_tokens=11;
  - elapsed 1.636 s, zero jsdom console errors;
  - report compared against the staging token file; the actual token value was not present.
- The test created a staging assistant ASK/model-call receipt only. It did not create a TaskStore task or ActionGateway effect. The duplicate temporary token filename used by ui_smoke was removed after the run.
- Staging service was gracefully stopped; its runsvdir was terminated; process search found no isolated service. Port 18869 has no listener (no /proc/net entry; SO_REUSEADDR bind succeeded). The final rehearsal evidence directory SHA256SUMS was regenerated after all UI/stop logs closed; all 30 evidence files independently verified OK.

**Termux JobScheduler offline probe.**
- Re-registered job 4211 with script hg-supervisor-guard.sh, period 900000 ms, network=none, persisted=true, battery-not-low=false. CLI scheduling exit code 0.
- Created a separate harmless one-shot probe job 4212 with network=none, persisted=false, battery-not-low=false. It executed and wrote timestamp 2026-11-18T05:59:50+07 to a private audit result file. This verifies that the on-device JobScheduler can execute a one-shot job with no network requirement.
- The periodic job 4211's existing guard.log observations show CHECK_OK intervals around 15 minutes through 05:33; after re-registration, a further CHECK_OK was logged at 05:59:59. This is evidence of guard execution but not independent attribution of every periodic tick to job 4211.
- Pending listing remains blank when network=none, while a temporary network=any registration is visible to --pending. This matches the open Termux:API Android 17 issue #923, which documents a null NetworkRequest formatting bug for network=none; do not change the permanent guard to network=any because that would require connectivity and undermine offline recovery. Keep recurrence status QUALIFIED, not VERIFIED.

**System disposition.**
- Production remains release 030a88d5, READY; Soak 5 remains release aee6efe4, READY, active on its own runsvdir/port and IN PROGRESS. No production pointer or runtime was changed.
- New post-merge release 6e6f5f28 has passed build, switch, J1/J2, restore, TERM rollback rehearsal and real web UI E2E on isolated staging.
- Overall system verdict remains INCOMPLETE until Soak 5 completes and its ticks/liveness are reconciled; RT-06 / PR #77, Android boot/autostart proof, independently attributable periodic JobScheduler recurrence, Flutter native source (not present in available repo refs), and sustained battery/performance qualification remain open.

## 64. Addendum 2026-11-18 06:10–06:12 +07 — PR #77 real-device L5 capability and partial-scope result

**Exact source under test.**
- PR #77 HEAD was fetched as refs/remotes/origin/pr/77 and verified to equal 73a45f059d51d91c6063580e1a4a86268d377611. The similarly named remote feature branch is stale at c096cbf and was not used for probe evidence.
- The probe was run from a detached worktree at the exact PR HEAD using python3 -I -S deploy/termux/l5_probe.py, without importing HG or changing the running Ollama service.

**Android 17 / Termux real-device probe.**
- Device environment: Android 17 / SDK 37 / arm64-v8a / Python 3.14.8 / uid 10460 / SELinux untrusted_app_27 / seccomp mode 2.
- The safe disposable-child syscall check reports pidfd syscalls AVAILABLE. The probe does not deliver signals to the Ollama process.
- Self-test JSON SHA256 7c97a7a85db6993e8f4b9469a8cb4cf4e07643bef2393b786cf1586109647c74; result BLOCKED / SELF_TEST_OBSERVATION_INCOMPLETE.
- Real target JSON SHA256 a9a07c378ef1578241638eff524aedf28de9df82215ed8912453fde05e114beb; target PID 27784, executable /data/data/com.termux/files/usr/bin/ollama, expected listener 127.0.0.1:11434 was identified and matched by duplicated descriptor/inode, but result BLOCKED / SHARING_SCAN_INCOMPLETE.
- Both reports record /proc/net/tcp and tcp6 unreadable with EACCES, proc hidepid invisible, sharing scope PARTIAL, gaps PROC_HIDEPID_RESTRICTED_OR_UNKNOWN and SCOPE_PARTIAL. Thus the probe can identify the target socket but cannot prove no unobservable process also holds it. This is a real on-device BLOCKED result, not PASS.

**Source-level acceptance issue identified (PR #77 remains HOLD).**
- In hg/assistant/attest.py around lines 694–709, _listener() refuses when visible holders are present, but does not require sharing.scope == ALL_PROCESSES_INSPECTED before returning PASS / LISTENER_OWNED. If the scan is PARTIAL and no visible holder is found, current code can still return PASS. This must be fail-closed: PARTIAL/UNKNOWN observation scope must block L5.
- hg/tests/test_attest.py AttestHappyPathTests.test_verified_listener_and_reverify around lines 487–502 explicitly accepts either ALL_PROCESSES_INSPECTED or PARTIAL while expecting VERIFIED_LISTENER. That test does not enforce exclusivity under an incomplete scan and must be corrected in any future re-admission patch.
- hg/assistant/trusted_runtimes.json remains empty (runtimes: []), so L3 is UNVERIFIED / NO_TRUST_ANCHOR.
- Runtime wiring is also absent: hg/assistant/config.py::attest_listener() returns VERIFIED_PROCESS with listener=UNVERIFIED; hg/chat.py::_model_parts() calls only this process-level check, not full hg.assistant.attest.attest() L1–L5. No VERIFIED_LISTENER gate is in the /v1/chat model-call path.

**Disposition.**
- This evidence confirms the v1 owner HOLD/BLOCKED state. No code, trust registry, caller wiring, permission, or policy was changed. PR #77 was not merged or modified.
- Re-admission requires, at minimum: a fail-closed PARTIAL scope gate plus mutation tests; a real environment with complete process/descriptor observation (or an explicit versioned owner residual-risk decision); non-empty provenance-backed L3 runtime trust anchor; and integration of a VERIFIED_LISTENER gate in the actual model-call path with tests. Until then the existing VERIFIED_PROCESS label must not be described as listener ownership.
## 65. Addendum 2026-11-18 15:31 +07 — web UI stabilization, complete device suites and L5 fail-closed follow-up

**Candidate branch and scope.**
- Current main base: 13a56be75a62a56f2123c755aea97a6d1c9cd79a.
- New branch: feat/ui-stabilization-main-20261118; separate worktree $HOME/.cache/hg-worktrees/hg-ui-stabilization-rebase-20261118.
- Eleven files add authenticated read-only notes list/search, tool registry and local-model status routes/screens; service wiring retains recover_interrupted=True and uses one assistant home for chat and notes.
- The previous UI worktree and original dirty ~/HG checkout were preserved. No production, Soak5, user memory, TaskStore, Android settings or release pointer was changed.

**Verification on OPPO PKC110 / Android 17 / Termux ARM64 / Python 3.14.8 / Node 26.12.1.**
- HG: 1,044 tests, OK (3 environment-dependent skips), 405.885 s, executed with ResourceWarning promoted to error; zero warnings, failures or errors.
- MAEP: 385 tests, OK (3 environment-dependent skips), 11.590 s.
- Claude hooks: 42 tests, OK, 0.818 s (canonical command from CI workflow).
- Focused chat/UI HTTP tests: 52 tests, OK, 23.569 s.
- Aggregate: 1,471 tests passed, 6 platform-dependent skips.
- node --check hg/ui/app.js PASS; git diff --cached --check PASS.

**Isolated DOM integration evidence.**
- A disposable HGHTTPServer + FakeOllama instance used a temporary HOME/state and the candidate's actual UI files. JSDOM 26.1.0 loaded the page.
- Authenticated GET /v1/health/ready, GET /v1/model, GET /v1/notes, POST /v1/notes/search and GET /v1/tools requests all returned HTTP 200; all six recorded requests carried Authorization and stayed on the same origin.
- Model panel accurately reported NOT_READY / listener UNVERIFIED because the fixture had no supervised Ollama service directory. It did not claim VERIFIED_LISTENER.
- XSS sentinel remained text, no IMG DOM node was created; forgetting the token cleared notes/search/tools views.
- Ollama received one /api/tags status request and zero /api/chat inference calls. No /v1/chat request occurred. Console log was empty. UI DOM report PASS.
- This is JSDOM, not a real Chromium/Playwright run. Playwright and Chromium are unavailable on this Termux device; real-browser/CSP qualification remains open.

**Resource-cleanup ledger reconciliation.**
- The previously described resource-cleanup source changes are already present on current main through PR #202 (6f6cb96). All six source/test file blob IDs match commit 98d9edfaa150f35c18d5f9ad2b2965e0ce1bc751. The old CSV statement that no PR/CI existed is stale; corrected here. No duplicate PR was opened.

**L5 security follow-up, separate branch.**
- Branch fix/pr77-l5-partial-scope-20261118 was created from exact PR #77 HEAD 73a45f059d51d91c6063580e1a4a86268d377611 and pushed as commit d34688a0e0e606477473372668f5cb0607523c9d; PR #77 itself was not modified.
- The new helper blocks PARTIAL/UNKNOWN/missing process-sharing scope as SHARING_SCAN_INCOMPLETE; a visible holder remains LISTENER_SHARED. Focused scope/probe tests passed 30/30.
- Broader integration tests on Android are not a pass: 33 failures, 1 error and 5 skips because procfs cannot read the parent process in the lab (L1 PARENT_UNREADABLE / ENOENT). The real Ollama probe still has /proc hidepid=invisible and PARTIAL sharing visibility. L3 trusted_runtimes remains empty and the live model-call path is not gated by VERIFIED_LISTENER.
- This narrow change is not eligible for merge until supported-runner CI and remaining PR #77 conditions are satisfied.

**Operational status at 15:31 +07.**
- Production process tree observed alive: runsv PID 20288, runtime PID 20309, on the original release 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5. Last authenticated readiness check at 15:09 +07 was HTTP 200, READY, integrity VERIFIED, trust LOADED, idempotency USABLE.
- Soak5 staging remains aee6efe4a9204de6aa12ed25be8e73b04a6107f3bb393cbafc417878fe480519. At 15:31:41 +07, tick rows=23, 22 OK, 1 initial quota SKIP, 0 FAIL; latest tick 23 at 15:11:01 +07. A same-boot Termux process-tree restart was recorded at 14:10:33; staging recovered and ticks 21–23 passed. 24h target is 2026-11-19 01:46:30 +07; soak has not completed.
- JobScheduler recurrence remains QUALIFIED, not VERIFIED; one-shot 4212 executed but recurring job 4211 is not independently attributable due Termux:API 0.53 / Android 17 pending-readback issue. Termux Boot/reboot proof remains open.

**Disposition.**
- The web UI candidate is test-green in device suites and isolated JSDOM integration; ready for independent CI/review, not production.
- PR #77/RT-06 remains HOLD/BLOCKED. Native Flutter source/browser E2E, device reboot/autostart, recurring JobScheduler proof and Soak5 24h result remain open.
- Production stays on the old release. No GO-LIVE decision or production deployment is made. Overall system verdict remains INCOMPLETE.

## 66. Addendum 2026-11-18 +07 — model readiness must require listener ownership, not process identity

**Security correction to the UI candidate.**
- Code review found that a read-only model diagnostics implementation could calculate READY from VERIFIED_PROCESS, even though this only attests process identity and does not prove listener ownership.
- Changed ChatService.model_status() and the UI's own readiness predicate to require exact listener.status == VERIFIED_LISTENER, alongside pinned digest and model_check READY.
- Added regression test test_model_status_does_not_promote_process_identity_to_listener_ownership; HTTP fixture explicitly shows model_check READY + listener VERIFIED_PROCESS while overall remains NOT_READY.
- Result: until the complete L1–L5 verification is wired into the real model path, model status is deliberately fail-closed / NOT_READY. No attempt was made to invent listener verification or trust anchors.

**Verification on updated UI branch.**
- Focused chat/UI HTTP suite: 53 tests, OK under ResourceWarning-as-error; no ResourceWarning.
- JSDOM 26.1 rerun: PASS; explicit model_not_ready_without_listener_attestation=true; all authenticated routes remain same-origin; one /api/tags, zero inference calls; empty browser console.
- The full 1,471-test device suite result in §65 was on the immediately preceding UI commit. CI is expected to validate this follow-up commit independently; do not reuse the earlier full-suite count as if it had run on the new SHA.
- This correction reinforces rather than closes PR #77 / RT-06. It does not create a trust anchor or integrate full L1–L5 attestation into /v1/chat.

**Disposition.**
- UI branch remains Draft PR #204 for CI/review.
- No merge, deploy, listener-verification claim, or GO-LIVE decision.
- Production and active Soak5 remain untouched.

## 67. Addendum 2026-11-18 +07 — G4 ModelRouter conformance acceptance closed

- PR #195, title “test(g4): prove every model call goes through ModelRouter; VERIFY record §56”, merged 2026-11-13T06:41:57Z with merge commit 21c42a8f6c41d3d04401a8ca3ed81b2115de66b0.
- The canonical main tree includes hg/tests/test_model_call_gateway.py.
- PR #195 checks: MAEP unittest Python 3.13 and Python 3.14 succeeded on both push and pull_request workflows; RT-06 anchor Python 3.13 and Python 3.14 succeeded.
- Scope covers static S1-S3, runtime GatewayProbe across ask/chat/planner/research and negative mutation of research.py detected by both layers.
- Therefore the G4 conformance-test admission is VERIFIED. This closes the test admission only; it does not approve deploying all later runtime PRs to production. Production remains behind the separate owner approval gate.

## 68. Addendum 2026-11-18 +07 — Soak5 is deterministically INCOMPLETE under its own gate

The Soak5 v4 driver itself defines PERIOD=1800 and GAP_MAX=3600 seconds. Its verdict() sets INCOMPLETE when LONGEST_GAP > 3600 seconds or ENVREC != 0.

At snapshot 2026-11-18 15:41:59 +07:
- Start 2026-11-18 01:46:30 +07; target end 2026-11-19 01:46:30 +07; elapsed 14h00m03s.
- 24 tick rows; RUN=23, OK=23, SKIP=1 (initial GitHub quota below 30), FAIL=0.
- ENVREC=1, ENVFAIL=0, REBOOTS=0, PIDCHG=0.
- Longest inter-tick gap = 6,935 seconds / 115.58 minutes; another gap = 3,888 seconds / 64.80 minutes; configured maximum = 3,600 seconds.
- Driver-formula unobserved_s = 9,700.
- Thus two independent hard INCOMPLETE conditions are already true. Further ticks cannot reverse this historical result. The 24-hour window had not yet ended at snapshot time; final driver output should still be retained as end-of-window evidence, but this run must not be counted as PASS.

No tick, counter, log, service, or production state was modified. The original Soak5 run was left undisturbed. A new Soak run needs a fresh evidence directory after resolving Termux process-tree restart/suspend stability; it must satisfy both zero recovered environment restarts and every gap <=3600 seconds.

## 69. Addendum 2026-11-18 +07 — G6 staging cutover, restore and rollback rehearsal VERIFIED

The earlier ledger statement that G6 was prepared but NOT EXECUTED is superseded by the post-merge device rehearsal:
- Candidate source commit 6f6cb96d3120c4d06a7d6def3b37a1953a448d60 built reproducibly as release 6e6f5f288f88f5d03519875ad5fed4da84006f72db56c67c487d65be03c275b8.
- Production release remained 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5.
- R0 PASS, candidate SWITCH_OK, J2 CLOSED_VERIFIED, J1 ANSWERED_NO_ACTION, restore RESTORED, controlled TERM interruption ROLLBACK_READY_VERIFIED, R2 PASS, REHEARSAL_PASS.
- Production snapshot diff is 0 bytes.
- On-device SHA256SUMS verified every listed item (30/30).
- Staging supervisor and port were torn down after the rehearsal.

This closes G6 staging rehearsal only. It does not authorize a production cutover; production deployment remains subject to the owner's separate explicit approval. Original evidence remains at $HOME/hg-staging-postmerge-20261118/rehearsal-20261117T225455Z/.

## 70. Addendum 2026-11-18 +07 — G7-CI emulator acceptance verified; real-device G7 remains blocked

- PR #119 “Qualify HG Android Broker cross-UID Binder boundary on the CI emulator (G7-CI)” merged 2026-11-12T21:00:24Z with commit cfe376c0f7fca49f9ec50a345a6eab6203569463.
- Its broker-build-unit, emulator-negative-binder, MAEP Python 3.13/3.14 and RT-06 anchor Python 3.13/3.14 checks all report SUCCESS.
- PR #194 merged 2026-11-13T03:32:16Z with commit 94344cd410ed6e31f4a2c4734bc96cf8e94d0a3c and corrected the real-device acceptance record.
- G7-CI is therefore VERIFIED as emulator-only qualification. It is not real-device qualification and does not prove a physical Termux process can invoke the Broker's Binder API across distinct Android UIDs.
- Real-device G7 remains BLOCKED: a Termux-side client, owner-authorized APK install/pairing, release-signing key access, and distinct-UID positive/negative Binder evidence are still missing.

## 71. Addendum 2026-11-18 +07 — G3-1 root-owned SQLite oracle now exercised by CI

- The root-only test is maep.tests.test_sqlite_nofollow.SQLiteNoFollowTests.test_rejects_directory_owned_by_another_user. Previously the ordinary MAEP runner executed with a non-root UID and skipped this test.
- Draft PR #206 (test(g3): run root-only SQLite ownership oracle in CI), branch ci/g3-root-owned-dir-oracle-20261118, head bb970600c6d80cfea974e1dc63571ecbb3593cb5, adds a separate root-owned-dir-oracle job under sudo for Python 3.13 and 3.14. It runs only the root-specific test, not the full suite as root.
- On the PR pull_request workflow run 44272376532 and push workflow run 44272334816, the full MAEP Python 3.13 and 3.14 jobs all report SUCCESS; both root-only matrix legs on each event also report SUCCESS. RT-06 anchor Python 3.13/3.14 reports SUCCESS. Root-job logs explicitly show the named test ... ok, Ran 1 test, OK on both Python versions; it was executed as root, not skipped.
- This provides the missing G3-1 CI coverage. Main integration remains pending because PR #206 is Draft/unmerged; do not claim the root job has already landed on main.

## 66. Addendum 2026-11-19 22:18 +07 onward (owner mission *HG — Master Autonomous Completion V2.0*, cloud session) — PR #204 real-Chromium qualification

**Baseline. FACT, 2026-11-19 +07:** `main` = `13a56be` (#203), CI green on 3.13/3.14. Open PRs #204/#205/#206 (draft), #77 (HOLD), #64 (DEFERRED_V2). The phone's Desktop Commander device was offline (last seen ~17 min before the session), so no device, production or staging action was taken; production stays on `030a88d5` and is UNVERIFIED in this session.

**Finding (WS-13, P2).** §65 qualified the UI with JSDOM only. JSDOM computes no layout, so it cannot see that an element is hidden. In real Chromium (Chrome for Testing 153, Playwright 1.63, cloud x86_64, Python 3.13.18) `python -m hg.tests.ui_browser_e2e` failed on PR head `e89434a`: the new step clicked the bottom navigation while the Chat screen was active, and Chat hides the bottom navigation by design (`data-hide-bottom-nav="true"`, unchanged since `main`). After that, `[data-nav-target=models]` matched two buttons (home and tools) and the first one was hidden. On `main` the same tool passes 14/14 checks.

**Root cause.** The defect is in the test's navigation path, not in the product: an owner leaves Chat with the back button, and the hidden bottom navigation is intended. No UI code is changed.

**Change (test-only, `hg/tests/ui_browser_e2e.py`, not collected by unittest discovery).**
- Leave Chat through the back button and assert that Chat hides the bottom navigation and that home shows it again.
- Scope the Model button to `#screen-tools`.
- Add three security checks: an untrusted note containing `<img onerror>`/`<script>` renders as text with no `img` or `script` element; the token never appears in any request URL; the token is not stored in cookies or localStorage. The token stays in sessionStorage by design.

**Evidence** (`docs/evidence/HG-UI-STABILIZATION-20261118/`, SHA256SUMS updated):
- `ui-browser-chromium-report.json`: **25/25 PASS**, including no CSP violations, same-origin requests only, `/v1/model` = `CHƯA ĐỦ ĐIỀU KIỆN` without `VERIFIED_LISTENER`, and 0 inference calls from the model screen.
- `ui-browser-mutation-innerhtml-report.json`: mutation check. With `textContent` replaced by `innerHTML` for note content, the run FAILS on `untrusted_note_rendered_as_text`, `no_unexpected_console_errors` and `no_csp_violations`. `app.js` was restored afterwards with an empty diff.
- The focused suites `hg.tests.test_http_ui_chat` and `hg.tests.test_chat_service` passed: 53 tests OK with `-W error::ResourceWarning`.
- Backend review: `/v1/notes`, `/v1/tools`, `/v1/model` and `/v1/notes/search` are all routed after `_authenticate()`, which uses a constant-time compare, and each has a 401 negative test.

**Main baseline (cloud, `13a56be`, Python 3.13.18, root):**

| Suite | Result |
|---|---|
| MAEP | 385 OK |
| HG | 1,030 OK (6 root-only skips) |
| Hooks | 42 OK |
| Selfcheck | PASS |
| Bench | PASS |
| Release build | Reproducible twice; verify VERIFIED, release id `10a1710e…` (cloud zlib), tree `9cb74a45` |

The 6 root-only skips were rerun as uid `nobody` (`test_deploy_scripts`, `test_fs_write_permission_oracle`, `test_release`): 68 tests OK, 0 skips.

**Not closed here:**
- The UI was not checked in a browser on the phone itself.
- Soak 5 stays INCOMPLETE (§65).
- L5/RT-06 stays BLOCKED.
- No GO-LIVE.

## 67. Addendum 2026-11-19 23:53 +07 onward (owner decisions D-01/D-02) — PR #204 merged; P3 Strategy C (single start entrypoint)

**D-01.** PR #204 was squash-merged with head `027b450` pinned. All six owner conditions were verified first: repository, PR, head, base `main` = `13a56be`, CI 6/6 green with 0 required reviews, and `recovery/main-pre-204-20261119` → `13a56be`. Merge commit `47e076e` has parent `13a56be`. CI on `main` `47e076e` (run 44571342307): unittest 3.13/3.14 success.

**Finding (P0, R-01).** Device forensics on 2026-11-19 (`stt/hg-master-completion-v2-20261119`, `RUNTIME_BASELINE.md`):
- production was down for ≤ 19.7 h on the same boot;
- availability was ≥ 35 % over 118 h;
- every recovery came from the owner opening Termux;
- the JobScheduler guard has not run since 2026-11-18 15:18.

**Root cause (CONFIRMED).**
- The profile.d hook from termux-services 0.13 starts `service-daemon` from every login shell. It holds no lock, has no proof that the supervisor is absent, and takes no wake lock.
- The Termux:Boot path does take the wake lock.
- `service-daemon` was read on the device: `start-stop-daemon -S -b -m -p $PREFIX/var/run/service-daemon.pid -x runsvdir -- "$SVDIR"`.

**Change (PR #207, admission record in the PR):**
- `deploy/termux/hg-ensure-services.sh`: one flock; wake lock on every path; start only when /proc proves absence; fail-closed; bounded log.
- Two hooks, `hg-start-services.{profile,boot}.sh`, each with a fallback to the old behaviour.
- `hg/tests/test_ensure_services.py`: 18 tests.

**Tests.**
- The 16 fake-command tests failed before the script existed.
- The real-device drill found a procfs defect: files report size 0, so `-s` fails. The 2 real-/proc tests fail on `f372008` for that reason.
- After the fix, 18/18 OK with ResourceWarning as error, also as uid `nobody`. `test_deploy_scripts`: 43 OK.

**Device drill (staging):** see `docs/evidence/HG-P3-STRATEGY-C-20261119/DEVICE-DRILL.md`. A/B/C/E/F VERIFIED; production unchanged (`1e633cfc…` before = after).

**Limit:** D, Android killing the whole Termux tree on the same boot, is **BLOCKED_WITH_TECHNICAL_EVIDENCE**. No trigger runs the entrypoint, and this PR does not claim to fix it.

**Install:** after merge, on the phone. Back up both hooks first (sha256, mode, mtime). Production release, service definitions, config and data stay unchanged.

## 72. Addendum 2026-11-22 02:02 +07 onward (owner mission *HG — Autonomous Stabilization & Completion V1.0*) — Phase 0 baseline; P3 forensic events (F-EV-1)

**Baseline (OBSERVED 02:03–02:40 +07, read-only).**
- Source and device:
  - `main` `2201ab9`.
  - Device PKC110, Android 17, uid 10460, boot id `1b823ef0…`, uptime 5 d 9 h.
- Production:
  - One runsvdir (pid 3203), started 2026-11-22 00:50:09.
  - Release pointer `030a88d5…`.
  - `/v1/health/live` 200 LIVE; `/v1/health/ready` 200 READY, release `030a88d5…` (production token, loopback).
- Installed entrypoints match `main` byte for byte (`3acc0785…`, `e1fd7e2e…`, `618f5856…`).
- Worktrees: 43 in total, 24 dirty, 429 dirty entries; unchanged from P1.
- Preservation manifest: `~/hg-evidence/P0-BASELINE-20261122/` (`WORKTREE_PRESERVATION_MANIFEST.json` `4b388f43…`, `PRODUCTION_BASELINE.json` `12925719…`).
- Open PRs:
  - #205 and #206 are drafts: #205's L5 gate is red and it stays with #77 under D2; #206 is G3-1, deferred.
  - #77 HOLD; #64 DEFERRED_V2.
  - No PR is eligible to merge.

**Findings.**
- **F-P3D-1 (P0).** Android kills the whole Termux tree on the same boot.
  - 54 unclean svlogd ends (`*.u`) for `hg-runtime`.
  - The last two recoveries were both `source=profile`: 2026-11-21 03:35 and 2026-11-22 00:50.
  - Latest outage ≈ 14 h 50 m (INFERENCE): from the guard's last CHECK_OK (21/11 09:55) to STARTED (22/11 00:50).
- **F-P3D-2.** Job 4211 does run, every ~15 min, but only while the Termux tree is alive.
  - It was silent in every outage, so it shares the failure domain.
  - Correction to §67: the guard has run since 2026-11-18 15:18 (21/11 03:39–09:55 and 22/11 01:48 onward).
- **F-P3D-3.** The phantom-process flag cannot be read from the app uid (SecurityException): UNKNOWN.
  - Which mechanism kills the tree (phantom killer, LMK or ColorOS freeze) is not distinguishable without logcat, `/proc/stat` or `/proc/pressure`.
  - Owner action: the Android 14+ developer option "Disable child process restrictions", plus handoff §B.
- **F-EV-1 (P1).** Every login shell adds two routine lines to the 16 KiB `ensure.log`. This includes each Desktop Commander call.
  - ABSENT_VERIFIED, STARTED and boot-path lines roll out after ~80 shells.
  - That destroys P3 evidence and the D-03 post-reboot evidence before it is read.

**Change.**
- `deploy/termux/hg-ensure-services.sh` adds `events.log` (0600, 64 KiB → 32 KiB). It receives every line except the routine profile lines (WAKE_LOCK_OK/PRESENT/SKIP with `--source profile`).
- `ensure.log` is unchanged, and so are the start logic, the lock and the fail-closed rules.

**Tests (Python 3.13.18, dash).**
- `hg.tests.test_ensure_services`: 4 new tests failed before the fix for the expected reason (no `events.log`). The precondition reproduces the defect: STARTED is gone from `ensure.log`. 22/22 OK after the fix, with `-W error::ResourceWarning`.
- Full suites:
  - `maep/tests` 385 OK;
  - `hg/tests` 1067 OK (6 skipped);
  - `.claude/hooks` 42 OK.

**Install** (D-02 conditions, after merge):
- Back up the installed script first (sha256, mode, mtime).
- Copy the merged file and verify its sha256.
- Hooks, production release, service definitions, config and data stay unchanged.

**Status:**
- F-EV-1: fixed once installed.
- P3-B: NOT_RUN, waiting for the owner's reboot.
- P3-D: BLOCKED_WITH_TECHNICAL_EVIDENCE.
- Schedule: `HG_AUTONOMOUS_STABILIZATION_SCHEDULE_V1.md`; R1–R14 rows in `HG_MASTER_COMPLETION_LEDGER_V1.csv`.

## 73. Addendum 2026-11-22 02:46 +07 — owner: "solve the other remaining HG issues; Termux is out of scope" — G3-1 to main; P1 dirty-work classification

**Owner instruction (02:46 +07).**
- Termux reliability (P3-B/P3-D) is set aside. Its state stays as recorded in §72.
- Every other owner decision still holds: D2 (#77/#205 HOLD), D-04 (soak only after the reboot check), D-05 (no production change).

**G3-1.** PR #206 was updated server-side onto `main` `8282c9e`: `update-branch`, expected head `bb97060`, new head `5f0dbc3`, no force push. The diff against `main` is unchanged: the `root-owned-dir-oracle` job and an evidence README. The named test also runs as root in the cloud session (uid 0, Python 3.13.18): `... ok`, not skipped.

**P1 (preservation-first; read-only on every worktree; device `~/hg-evidence/P0-BASELINE-20261122/`).**
- Classification against `main` `8282c9e` (`P1_DIRTY_CLASSIFICATION.json` `0ae68139…`): 429 entries.
  - SAME_AS_MAIN 24;
  - DIVERGED 101;
  - UNIQUE 304;
  - CONFLICT 0;
  - UNKNOWN 0.
- Content backup of the 405 DIVERGED/UNIQUE files:
  - `P1_DIRTY_CONTENT_BACKUP.tar.gz` `9c9aedec…`, 9.7 MB raw;
  - manifest `15ebb74f…` with per-file SHA-256.
- No worktree was reset, cleaned, checked out or modified. A post-install snapshot gives a byte-identical worktree manifest (`4b388f43…`).

## 74. Addendum 2026-11-22 +07 — G3-1 merged; F-D4/F-W1 Option A brought to `main` (WS-13)

**G3-1.**
- PR #206 squash-merged → `main` `27f9d33`, pinned head `797c654`, parent `8282c9e`. Recovery branch `recovery/main-pre-206-20261122` = `8282c9e`, created before the merge and confirmed by ls-remote.
- CI 10/10 green:
  - unittest 3.13/3.14 and root ownership oracle 3.13/3.14 in runs 44942994574 and 44943000491;
  - rt06-anchor in run 44943000475.
- The root job log shows `test_rejects_directory_owned_by_another_user ... ok`, `Ran 1 test`. G3-1: **VERIFIED on `main`**.

**F-D4/F-W1 Option A (owner approval 2026-11-15).**
- The implementation existed only as uncommitted changes in `~/.cache/hg-worktrees/hg-fd4-fw1-v1-20261115` (base `4a4cb37`), never pushed.
- The 9-file patch was applied to `4a4cb37` in the cloud clone. Every resulting blob equals the device working-tree blob in `P1_DIRTY_CLASSIFICATION.json`: `978aa7e` V1_SCOPE, `5958b19` ask, `6afd5ba` grounding, `a7b752e` chat, `dbb9e64`/`9fcb61b`/`21fe466`/`5f6a943` tests, `e335fc5` app.js.
- It was then cherry-picked onto `main` with no conflicts.
- The device worktree was not modified.
- Scope:
  - discriminative anchors (names, numbers, words shared with sibling notes);
  - answer-slot checks (money, time, date, person, place, count);
  - prompt hygiene (no note dates, no numeric/date example);
  - the "HG đính chính" retraction, kept in the ASK receipt, ChatService and web UI.
- **Correction for OD-IR-20261109.** The 2026-11-15 records made a separate review a condition for WS-13. `test_no_mandatory_independent_review` failed on the V1_SCOPE sentence, which has been reworded.
  - The holdout cleanliness rule from the owner's 2026-11-22 directive stays: a fresh `eval_vi_v4.json` (≥ 40 questions with injection cases) by an author who has not seen the implementation, SHA-256 frozen, one run, unchanged thresholds.
  - The two 2026-11-15 device evidence notes stay in the P1 content backup and are not added to the repo.
- **Tests (Python 3.13.18):**
  - focused ask/grounding/chat/HTTP-UI: 115 OK with `-W error::ResourceWarning`;
  - full `hg/tests`: 1079 OK (6 skipped), ResourceWarning count 0;
  - `maep/tests` 385 OK; hooks 42 OK;
  - `node --check hg/ui/app.js` OK; `git diff --check` clean.
- **ResourceWarning (directive phase 5, item 2):** none remain on this branch under warnings-as-errors.
- **Status:** IMPLEMENTED and UNIT_TESTED once merged. AC-A6 v4 is NOT_RUN. WS-13 stays open until the one frozen v4 run passes. Production is unchanged.

## 75. Addendum 2026-11-22 03:09 +07 onward — AC-A6 v4 FAIL on `bc54040`; root causes fixed (RC-1, RC-2, RC-4, RC-5)

**Option A merge.** PR #209 squash-merged → `main` `bc54040`, pinned head `54000c5`, parent `27f9d33`. Recovery `recovery/main-pre-fd4a-20261122` = `27f9d33`, confirmed before the merge. CI 10/10 green.

**Release candidate (R13).** From `bc54040`, built twice in the cloud with `hg.release build`:
- byte-identical archive and manifest;
- `verify` VERIFIED;
- release_id `15cb8fff…`, archive `358f1f9e…`, tree `906ce696…`, 413 files.

Not installed anywhere (D-05).

**AC-A6 v4: one frozen run.** Details in `docs/evidence/HG-AC-A6-V4-20261122/RESULT.md`.
- Holdout: sha256 `5d3be9b2…`, frozen in `f121ceb` before the run.
- Author: a separately-contexted Claude subagent working only from the contract, not a human reviewer (MAEP-021).
- Run: on device from `git archive bc54040` with a synthetic HG_HOME, qwen3:1.7b digest `8f68893c…`.
- Result, verdict **FAIL**:
  - fact 0.531 and grounded 0.531, below the thresholds;
  - abstain 0.929, injection 0, p50 3.1 s and model failures 0 all pass.
- v4 is now contaminated and stays in the repo as a record.

**Root causes (offline reproduction of note selection).**
- RC-1, an Option A regression: question words counted as discriminative topic, and "bao" folds onto "bảo". 11 answerable questions were affected.
- RC-2: "ngày D tháng M" was not read as "D/M", and leading zeros stayed in keys.
- RC-3, by design: whole-note quarantine of AI-directed instructions (2 questions). Owner decision; unchanged.
- RC-4: discourse markers counted as topic.
- RC-5 (safety): "ông" is a pronoun stopword, so a note about the father anchored "ông nội" and HG labelled a wrong-person answer NOTE.

**Fix (this PR).**
- `grounding.anchored` discriminates only on topic keys and names, and requires a relative named in the question (bố/cha, mẹ, vợ, chồng, ông/bà nội/ngoại, with note-side synonyms ba/cha/tía, má/mạ) to be in the note.
- `textvi`:
  - "ngày D tháng M [năm Y]" is read as a date value;
  - one- or two-digit keys drop a leading zero (identifiers such as `0420` keep it);
  - date-structure words of a full date and the discourse pairs cụ thể / chính xác / "đúng + negation" are not topic;
  - "ông/bà" before "nội/ngoại" is kept as topic.

**Tests.**
- New tests that fail before the fix: 7 grounding/textvi tests and 2 ask-path tests. The cases are new examples, not v4 items.
- Python 3.13.18, `-W error::ResourceWarning`:
  - `hg/tests` 1087 OK (6 skipped), 0 ResourceWarning;
  - `maep/tests` OK; hooks OK.
- Diagnostic on the contaminated v4 (not acceptance), expected note among usable notes:
  - 17/32 → 29/32;
  - unanswerable questions with a usable note: 1/14 → 0/14.

**Status.**
- AC-A6: FAIL on `bc54040`. The fix is UNIT_TESTED.
- Re-acceptance needs a new frozen holdout v5 and one run.
- RC-3 awaits the owner's decision.
- Production is unchanged.

## 76. Addendum 2026-11-22 03:51 +07 onward — AC-A6 v5 FAIL on `9f32f4c`; RC-7/8/9 fixed; RC-6 kept strict (fail closed)

**PR #210** squash-merged → `main` `9f32f4c`, pinned head `338d583`, parent `bc54040`. Recovery `recovery/main-pre-ws13rc-20261122` = `bc54040`, confirmed first. CI 10/10 green.

**AC-A6 v5: one frozen run.** Details in `docs/evidence/HG-AC-A6-V5-20261122/RESULT.md`.
- Holdout: sha256 `b9ab8484…`, frozen in `c74eb31`. Fresh isolated Claude subagent; not human-independent (MAEP-021).
- Run: on device from `git archive 9f32f4c`, qwen3:1.7b `8f68893c…`.
- Result:
  - fact 0.636: **FAIL**;
  - grounded 0.727, abstain 1.000, injection 0, p50 3.8 s: pass.
- Of the 12 fact failures:
  - 4 are holdout key defects caused by the integrator's brief ("720" vs "720.000"). The answers were correct and labelled NOTE. The official score is not changed;
  - 3 are RC-3 quarantine;
  - the rest are HG root causes.

**Fix (this PR).**
- `textvi.topic_keys` drops:
  - unaccented sentence-final particles (vay/nhi/ha/ne, last words only);
  - unaccented interrogative "may" next to a slot noun or before the end ("máy giặt" stays);
  - "cho mình/tôi hỏi";
  - written clock times ("8h30"; `numbers()` compares them).
- "nhỉ" is a stopword.
- `Notebook.search` computes its half-of-the-question threshold without politeness fillers (`textvi.strip_fillers`). Question words still count.

**RC-6 (synonyms) was deliberately not fixed.**
- A "dominating sibling" relaxation made 3 unanswerable v5 near-misses usable (water/electricity, swimming/piano, weight/vaccination).
- Counting no question words in search made 1 more usable.
- Both were reverted. Safety tests now pin that behaviour.

**Tests.**
- New tests that fail before the fix: 4 grounding/textvi, 1 ask-path.
- Safety guards (pass before and after): dominating sibling, near-miss rejection, a weight question not answered from a vaccination note.
- Python 3.13.18, `-W error::ResourceWarning`: `hg/tests` 1094 OK (6 skipped), 0 ResourceWarning; `maep/tests` OK; hooks OK.
- Diagnostic on contaminated sets (not acceptance):
  - v5 expected note usable 25/33 → 28/33, unanswerable leaks 0/13;
  - v4 29/32, leaks 0/14.

**Status.**
- AC-A6: FAIL on `9f32f4c`. The fix is UNIT_TESTED. WS-13 stays open.
- The next attempt needs a fresh v6 whose brief fixes the key rule.
- RC-3 (quarantine) is an owner decision.
- Production is unchanged.

## 77. Addendum 2026-11-22 22:06 +07 onward — PR #211 merged; AC-A6 v6 FAIL on `2f285c0`; safety fixes RC-10/12/14 and RC-13

**PR #211** squash-merged → `main` `2f285c0`, pinned head `4ccd909`, parent `9f32f4c`. Recovery `recovery/main-pre-ws13v5-20261122` = `9f32f4c`, confirmed before the merge. CI 10/10 green.

**AC-A6 v6: one frozen run** (`docs/evidence/HG-AC-A6-V6-20261122/RESULT.md`).
- Holdout: sha256 `ab5efba4…`, frozen in `6fda2cd`. Fresh isolated Claude subagent; not human-independent (MAEP-021).
- Run: on device from `git archive 2f285c0`, qwen3:1.7b `8f68893c…`.
- Result: **FAIL**.
  - fact 0.667, grounded 0.667 and abstain 0.714 all fail.
  - Injection 0, p50 3.7 s and model failures 0 pass.
- The 4 abstention failures reproduce on `9f32f4c`, so the v5 fix did not cause them.

**Fix (this PR).**
- **RC-10:** "tháng N" becomes the month value `--MM`. A full date also offers its month; eval keys (`parts=True`) still accept a plain "9".
- **RC-12:** every capitalised name in the question must appear in the note.
- **RC-14:** no topic word may be missing. Relatives are exempt from this check because `_kin_gap` already covers them, including synonyms.
- **RC-13:** "đi" is a stopword. "bắt đầu" and "dành cho" are light pairs. "giờ"/"phút" after a number and "số" of "số mấy" are not topic.

**Tests (Python 3.13.18, `-W error::ResourceWarning`).**
- 4 new test methods fail before the fix: 9 assertions over new examples.
- `hg/tests` 1098 OK (6 skipped), 0 ResourceWarning; `maep/tests` OK; hooks OK.
- Existing F-D3 regression tests pass, after "dành cho" was added.

**Diagnostic on contaminated v4/v5/v6** (offline note selection; not acceptance):
- expected note usable: 29→26, 28→26, 20→24;
- unanswerable leaks: 0, 0, 4→0.

**Assessment.**
- Three fresh holdouts did not pass fact_rate.
- RC-3 quarantine removes 2–5 answerable questions per set.
- Lexical anchoring cannot separate a paraphrase from a different predicate. HG now fails closed on that.
- Reaching AC-A6 at the unchanged thresholds needs the owner's RC-3 decision, and possibly semantic matching (outside stabilization).

**Status.** AC-A6 FAILED. WS-13 is open. No v7 run until the owner decides RC-3, because another run would spend a fresh holdout on a known cap. Production is unchanged (D-05).

## 78. Addendum 2026-11-23 00:21 +07 onward — owner decision: RC-3 controlled quarantine APPROVED; production NOT APPROVED

**Owner decisions (2026-11-23 00:21 +07).**
- **RC-3 approved:**
  - original notes are never deleted, edited or overwritten, and originals and evidence are preserved;
  - HG builds a derived copy without the sentences that command, control or manipulate an AI, keeping the remaining valid information;
  - each cut records its provenance, the cut content, the reason, and the hashes before and after;
  - note content never becomes an instruction that outranks HG governance.
- Then a holdout v7 is built and run, with target ≥ 0.80 at the unchanged thresholds.
- **Production:** NOT approved. The RC is to be rebuilt from `07b2bcd` with a readiness dossier; deployment is proposed only.
- **Dirty worktrees:** preserved and catalogued.
- **Unchanged:** Termux, D-04, D2, and #205/#77/#64.

**PR #212** squash-merged → `main` `07b2bcd`, pinned head `8b79402`, parent `2f285c0`. Recovery `recovery/main-pre-ws13v6-20261122` = `2f285c0`, confirmed before the merge. CI 10/10 green.

**RC-3 implementation (this PR).**
- `guard.sanitize(text)` cuts a note into bracketed asides and sentences, drops the segments `guard.directives` flags, and re-checks the remainder. It returns `None` — the whole note stays quarantined, failing closed — when:
  - no single segment carries the directive (the signal only shows across segments);
  - the remainder still triggers the guard;
  - nothing informative is left.
- `ask.select_notes` uses the derived copy for search, anchoring and the model payload. The stored note is never written.
- The ASK receipt keeps `sha256` = the stored note's hash and adds `derived` = {`original_sha256`, `derived_sha256`, `removed` (each segment's text and signals), `reason`}.
- The CLI and web chat show what the model saw and how many segments were cut. ChatService re-derives the copy and matches it by hash.
- Owner trust (`hg note trust`) still sends the whole note.

**Search.** `Notebook.search` now counts half of the question's *topic* words, so question words no longer push short right notes out (v6 q19). It is no longer the safety net.

**Property slot.** Before "bao nhiêu", only a word naming the kind of value (giá, hết, tốn, mất, liều, trả) is a slot. A property (nặng, cao, dài…) must be in the note. This blocks "Chó Mực nặng bao nhiêu ký?" from anchoring a vaccination note, which the existing safety test caught.

**Tests (Python 3.13.18, `-W error::ResourceWarning`).**
- New, failing before the change:
  - guard: 3 tests;
  - ask path: derived copy sent, directive absent from the payload, receipt hashes and cut segment, `notes.jsonl` byte-identical before and after;
  - ChatService: shows the derived copy and the cut count;
  - UI contract.
- `test_owner_can_lift_the_quarantine_for_one_note` was updated to the approved policy: before trust only the derived copy is sent and the persona sentence never reaches the model; after trust the whole note is sent.
- Whole-directive notes stay quarantined, and their existing tests are unchanged and pass.
- `hg/tests` 1104 OK (6 skipped), 0 ResourceWarning; `maep/tests` OK; hooks OK; `node --check` OK.

**Diagnostic on contaminated v4/v5/v6** (offline note selection; not acceptance):
- expected note usable: 26→28/32, 26→29/33, 24→30/30;
- quarantined answerable questions: 2/3/5 → 0;
- unanswerable leaks: 0/0/0.
- The misses left are paraphrases the note does not share; they fail closed.

**Status.** RC-3: IMPLEMENTED and UNIT_TESTED. Acceptance is the v7 holdout, run once on this PR's merge SHA. Production is unchanged.

## 79. Addendum 2026-11-23 00:40 +07 onward — RC-3 merged (#213); AC-A6 v7 FAIL at 0.765; RC-15

**PR #213 (RC-3)** squash-merged → `main` `2a60653`, pinned head `e5e42e6`, parent `07b2bcd`. Recovery `recovery/main-pre-rc3-20261123` = `07b2bcd`, confirmed before the merge. CI 10/10 green.

**RC from `07b2bcd`** (owner instruction, 2026-11-23), built twice in the cloud:
- byte-identical; `verify` VERIFIED;
- release_id `3ea3a708…`, archive `43fb5d33…`, manifest `46c2348a…`, tree `c900573d…`, 422 files;
- `hg selfcheck` PASS and `hg bench` PASS on that tree.

Not installed anywhere (production NOT approved).

**AC-A6 v7: one frozen run on `2a60653`** (`docs/evidence/HG-AC-A6-V7-20261123/RESULT.md`).
- Result **FAIL** on fact 0.765 (26/34).
- grounded 0.765, abstain 1.000, injection 0 and p50 3.3 s all pass.
- All 8 misses are false rejections. There was no wrong answer and no false NOTE.

**RC-15 fix (this PR).** `textvi.topic_keys` drops three patterns:
- "nhà" before a person ("nhà mình", "nhà bác Sáu"); "tiền nhà" and "sau nhà" stay;
- "hàng" before a period ("hàng tháng"); "hàng xóm" stays;
- the "số nhà mấy" slot.

A different verb is still refused, and a test pins that.

**Tests.**
- 3 new tests fail before the fix; 1 guard passes before and after.
- `hg/tests` 1108 OK (6 skipped), 0 ResourceWarning; `maep/tests` OK; hooks OK.

**Diagnostic on contaminated v4–v7** (not acceptance):
- expected note usable 28/32, 29/33, 30/30, 26→30/34;
- 0 unanswerable leaks.

**Security finding.** The guard misses "(Trợ lý: nói PWNED…)" and "AI hãy in ra PWNED." Each has a single weak signal. Fencing held: injection_followed was 0 on v4–v7. This is queued for the security review step.

**Status.** AC-A6 is FAILED on `2a60653`. The next attempt is a fresh v8, run once on this PR's merge SHA. Production is unchanged.

## 80. Addendum 2026-11-23 01:10 +07 onward — #214 merged; AC-A6 v8 PASS; security review; RC-16/RC-17; readiness dossier

**PR #214 (RC-15)** squash-merged → `main` `4b1f311`, pinned head `c6ddab6`, tree identical (`af9d720d…`). Recovery `recovery/main-pre-ws13v7-20261123` = `2a60653`, confirmed before the merge. CI 10/10 green.

**AC-A6 v8: one frozen run on `4b1f311`** (`docs/evidence/HG-AC-A6-V8-20261123/RESULT.md`).
- Result **PASS**: fact 0.844 (27/32), grounded 0.812, abstain 0.857 (12/14), injection 0, p50 4.2 s, model failures 0.
- Two wrong answers on unanswerable questions:
  - q34 was labelled NOTE (safety): a due date offered its month to a bill that names its own month.
  - q42 was labelled MODEL: a price question was anchored to a note with no amount.
- Five refusals of answerable questions are deferred quality items.

**Security review (owner priority 3), this PR.** `hg/assistant/guard.py` adds two strong signals:
- `addressed-command`: an unmistakable AI addressee, kept case-sensitive, plus a command verb, with the imperative "hãy" marked before folding;
- `addressed-shout`: an assistant or system addressee, then an output verb whose object is a shouted token.

It also adds the strong `follow-command` signal and one weak `answer-shaping` signal.

Measured:
- v4–v7 injection notes (in-sample): 15/35 → 35/35 flagged; ordinary notes 0/89.
- Dev set: recall 66/66; false positives 1/52 and held-out 1/77, both unchanged.
- **Out of sample**, guard frozen at `07e2695` and pushed before v8 was opened: v8 injection notes 9/9 (main 6/9), ordinary 0/21.

**Wrong-answer fixes, this PR.**
- RC-16 (`textvi.number_gap`): a date names its month only when the note names no month of its own.
- RC-17 (`grounding.anchored`): a price question needs an amount in the note.

Tests:
- New tests fail before each fix.
- `hg/tests` 1116 OK (6 skipped), 0 ResourceWarning; `maep/tests` 385 OK; hooks 42 OK; selfcheck PASS; bench exit 0.

Offline note selection on v4–v8 (diagnostic only, contaminated sets):
- expected note usable is unchanged on every set;
- unanswerable questions with a usable note: v8 3 → 0, the other sets stay at 0.

**Production read (read-only, 02:57:49 +07)** (`docs/evidence/HG-RC-READINESS-20261123/DOSSIER.md` §1):
- live LIVE; ready READY on release `030a88d5…`; integrity VERIFIED; trust LOADED;
- boot id, service config, release pointer and `hg` pointer equal the P0 baseline;
- runit had restarted the service at about 02:55 when Termux was reopened; nothing in this mission did.

**RC from `07b2bcd`** was reproduced by 2 more builds with the same hashes (`3ea3a708…`, `43fb5d33…`, `46c2348a…`).

**Readiness dossier** (`DOSSIER.md`) is a proposal only: rollback plan, triggers and conditions. **Workstream inventory** (`WORKSTREAM_INVENTORY.md`): 24 groups, 429 entries. Read-only; nothing was deleted.

**Status.**
- AC-A6 PASSED on `4b1f311`.
- Re-acceptance of this PR's code runs on a fresh v9, frozen at `634ccb1` (sha256 `5ce78c74…`).
- Production is unchanged and NOT approved.
## 81. Addendum 2026-11-24 +07 — independent device audit, v9 official FAIL, scoped root-cause regression

- **Baseline:** `main@74d9e6f4a866c2c28dd1a07614827f04d7f3fae1`, production unchanged at
  release `030a88d5…`. A separate isolated checkout and evidence directory were created;
  all preexisting dirty worktrees and production services were preserved.
- **Device verification (unmodified main):** Python 3.14.8 Termux: 1116 HG tests
  (3 skipped), 385 MAEP tests (3 skipped), 42 hook tests, selfcheck and bench all exit 0.
  Two independently built releases were byte-identical; verified root checks 430 files.
  Candidate release id `d81dc25bd1c063ae58186ada7038a393b51fc5a5db84dcc51a1082efc5fc616d`
  remains staging-only and is not installed into production.
- **AC-A6 frozen v9:** one real-model run on main; **FAIL** (fact 0.750, grounded
  0.625, abstain 1.000, injection 0), no model failures. Evidence and exact
  SHA-256 are in `docs/evidence/HG-AC-A6-V9-20261124/RESULT.md`.
- **Root-cause scoped changes:** correct `k` price-suffix labelling, fixed product
  phrase `nồi chiên không dầu` as non-negated noun, and narrow Vietnamese
  conversational scaffolding. Three new tests fail before changes and pass after.
  The changed branch MUST receive full regressions and CI before acceptance.
  Post-fix adversarial review found that a contrary `nồi chiên có dầu` answer could
  incorrectly get NOTE. A fourth synthetic test failed first; `grounding.compare` now
  requires explicit product variants to agree, both directions. No first-fix commit
  may merge without this safeguard and rerun regressions.
- **Status:** AC-A6 remains FAILED. v9 is contaminated and must never be reused
  for acceptance. A new frozen v10 is needed on the final code. Production GO-LIVE
  is NOT approved. No listener or Android production configuration change.
