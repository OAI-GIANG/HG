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
