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
