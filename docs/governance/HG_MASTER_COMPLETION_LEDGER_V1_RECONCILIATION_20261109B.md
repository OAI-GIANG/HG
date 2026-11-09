# HG MASTER COMPLETION LEDGER V1 — POST-DEPLOY RECONCILIATION 2026-11-09 (B)

**Repository:** `OAI-GIANG/HG`
**Observed:** 2026-11-09 (Asia/Ho_Chi_Minh), GitHub REST, git, Desktop Commander on the owner's phone (device `22e6ee74-…`)
**Relation:** ADDITIVE. The 2026-11-06 snapshot and the morning reconciliation `HG_MASTER_COMPLETION_LEDGER_V1_RECONCILIATION_20261109.*` stay unchanged as provenance. This delta records what happened after them: merges, a deployment, a CI regression and its fix.

**Labels:** FACT = observed during this reconciliation; INFERENCE = derived; UNKNOWN = not established; BLOCKED = needs a source or an owner decision.

---

## 1. Main and merges

| Item | Value | Source |
|---|---|---|
| PR #81 (ledger + morning reconciliation) | MERGED 2026-11-09T05:00:51Z, merge `fa599dd0fd3d44bb669992fc07b3eaeb8f2a8965`; main changed only the 6 governance files; both checksum files pass on main | FACT, REST `pulls/81`, `sha256sum -c` on main blobs |
| PR #84 (EC07 part 2: evidence operation idempotency, IN_DOUBT append outcome) | MERGED 2026-11-09T05:04:18Z, merge `9d82701ec8a30628e678fa85132e8c706e297e77`, tree `32f34ec02f12bdedb032eab4e2cb542079271ad7` | FACT, REST `pulls/84`, `git rev-parse` |
| PR #85 (Batch 1: refused append is "state unchanged") | MERGED 2026-11-09T05:45:39Z, merge `f57c7e76799e7af88f9ea3a4298516cc555ad529`, tree `acdaa52946758ca2d70c3d6620300c566e054a25`; head `0ef8eae` CI 6/6 green; push CI on the merge commit: `unittest (3.13)` and `unittest (3.14)` SUCCESS ([run 42569134749](https://github.com/OAI-GIANG/HG/actions/runs/42569134749)) | FACT, REST `pulls/85`, `commits/f57c7e7/check-runs` |
| main tip at reconciliation | `f57c7e76799e7af88f9ea3a4298516cc555ad529` (tree `acdaa529…`); push CI green on 3.13 and 3.14 | FACT, `git rev-parse origin/main` |

## 2. CI regression on main 9d82701 and its fix

- FACT: push CI on `9d82701` ([run 42565176818](https://github.com/OAI-GIANG/HG/actions/runs/42565176818)): `unittest (3.13)` SUCCESS, `unittest (3.14)` FAILURE — `hg.tests.test_writer_admission.CrossProcessLedgerTests.test_taskstore_duplicate_task_event_id_has_single_winner_across_processes` gave `['CREATED', 'LedgerOutcomeUnknown']` instead of `['CREATED', 'MAEPError']`.
- FACT (root cause, proven by deterministic tests that fail on `9d82701`): PR #84's `_commit` re-read the ledger after every append error. A loser's append that `append_event` refused before writing was then reported IN_DOUBT when the winner's event was byte-identical (PRESENT) or the ledger was torn (UNREADABLE). The outcome was known: nothing was written.
- Fix: PR #85 — `maep.ledger.LedgerAppendRefused` for every pre-write refusal; `_commit` maps it to "state unchanged" without a readback. Cross-process race repeated 300× on Python 3.13 (cloud): 0 `LedgerOutcomeUnknown`. Python 3.14.8 on the phone (Termux, non-root) at `c902338`: focused tests OK; the CI race test run 50×, 50 pass. The repetitions show no regression but do not discriminate base from fix (a reviewer's 150 runs on base also gave 0 IN_DOUBT); the discriminating evidence is the two deterministic tests (PRESENT and UNREADABLE branches), both red on `9d82701`. Which branch fired on CI is UNKNOWN; the fix covers both.
- FACT (process finding): release `7cfd94e4…` (`9d82701`) was deployed at 12:09 +07, after the push CI on `9d82701` had failed on 3.14 at 12:05:39 +07. The deploy gate checked CI on the PR head (`ad1380e`, green) but not on the merge commit. Production impact (INFERENCE): classification only; a false IN_DOUBT needs two writers that build byte-identical events or a foreign torn tail, and the service has one admitted writer. Corrective rule: deploy only after push CI on the exact merge commit is green.

## 3. Deployments on the phone (FACT)

| Release | Commit | Tree | Build | Install | Switch | Status |
|---|---|---|---|---|---|---|
| `363fbc3a82d08a2d68652a9254796ff54970fa35c4100984b0264b3e2f5f411f` | `61d26cf` | `5958a667…` | archive `660d2c3b…`, 261 files | SEALED, VERIFIED | SWITCH_OK 11:18 +07, `~/hg-v1-evidence/switch-20261109T041759Z` | kept for rollback |
| `7cfd94e45a70a797c2a060703c61d0701f30fe3a08a4b01a2dad8d0c39bd40d2` | `9d82701` | `32f34ec0…` (= cloud) | archive `c854f4a0e398b43a7250c7c6c67117c7753b77d11b0eb8a542f7739f01ac93fb`, files_digest `8f3ba88ca3a4b2b81fe9305cd831f310a280453fb22d3fbf38ee44b12945d298`, 269 files, two builds byte-identical | SEALED (38 dirs, 269 files), VERIFIED | SWITCH_OK 12:09 +07, `~/hg-v1-evidence/switch-20261109T050910Z`; ready true, trust_commit `9d82701`; pid 3403 stable | RUNNING (last observed ~12:42 +07: pid 3403 up 2093 s). Contains the PR #84 classification defect fixed by PR #85; superseded on main by `f57c7e7` |

- Deploy of `f57c7e7` (PR #85): **NOT_RUN**. The phone stopped answering Desktop Commander at ~12:50 +07 (two timeouts; device listed Online, last seen 9 min) and the concurrent hourly session holds `~/hg-v1-evidence/.autonomous-run.lock` (taken 12:13:33 +07). Prompt rule for the lock holder or the next hourly run: a merged runtime change not yet on the phone is IN_PROGRESS — deploy `main` once push CI on the exact merge commit is green (it is).

- Evidence bundle `~/hg-v1-evidence/20261109-deploy-9d82701/`: SHA256SUMS sha256 `3553b4f09a05f3bb77cfc2d06a4c77ad7b1b5080c417bebfa1120af0cd43ee37`, `sha256sum -c` OK.
- Termux tests on `9d82701` (non-root): maep 346 OK (skipped=3), hg 507 OK.
- Rollback: `sh deploy/termux/switch_service.sh --restore <switch dir>` (switch dirs above).
- Health evidence kind: `deploy_smoke.py ready` (authenticated readiness JSON) + `HG_RUNTIME_READY` log line + `sv status` pid. No unauthenticated 401 is counted as health.

## 4. Open PRs (FACT)

| PR | Head | State | Notes |
|---|---|---|---|
| #77 listener attestation HG-LA-2 | `73a45f0` | OPEN, HOLD | Synced with main by merge (no rewrite): 17 ahead / 0 behind vs `9d82701` at sync; 17 ahead / 4 behind vs `f57c7e7` after PR #85, 67 files +5041/−10 unchanged; unit 3.13/3.14 and RT06 green; `l5-capability-gate` BLOCKED (red = BLOCKED by design); 0 formal reviews; protected path `hg/assistant/config.py` (+10/−7) and CI file `.github/workflows/maep-tests.yml` in the diff |
| #64 opt-in `hg.policy.v2` | `ec8b781` | OPEN, draft (converted 2026-11-09) | base frozen `stt/maep-v1-20261022`; out of v1 scope (v2 deferral 2026-10-28); triage comment posted |
| #55 Claude setup + `jev` MCP | `6d96f4b` | OPEN, draft (converted 2026-11-09) | third-party MCP via `npx -y` with API key; owner decision needed; triage comment posted |
| #11 audit-only execution host | `0f25cb5` | OPEN, draft | needs owner decision (AUDIT_ONLY, `HG_AUDIT` grant, guard rewrite); conflicts in `hg/runtime.py` |

## 5. Writer inventory findings (Batch 4 input, read-only, main 9d82701)

- H1 (FACT): `maep.ledger.append_event` / `append_generated` take any path and check no admission; admission lives only in store constructors (`task_store.py` `require_writer_session`, `evidence.py`). Any in-process caller can append to a ledger file directly.
- H2 (FACT): admission is a marker file plus an in-process registry (`maep/admission.py`); another process that does not construct a store is not blocked. Matches CLAUDE.md ("nothing ENFORCED system-wide") and owner decision Q3 (same-UID attacker out of v1 scope).
- M1 (FACT): `hg/assistant/repair.py` rewrites live assistant ledgers by `os.replace`, protected only by the HOME lock.
- M2 (FACT): assistant ledgers have two writer processes (owner CLI and `hg serve` chat receipts), coordinated by the HOME flock only.
- M3 (UNVERIFIED): whether `switch_service.sh` holds `.writer.lock` across the state-directory swap.
- T-1 (FACT): the principal is a string constant (`hg/runtime.py` `DEFAULT_PRINCIPAL="STT"`); no code distinguishes agent from owner identity.
- Status: inventory only; no code changed. EC03–EC06 remain open.

## 6. Workstreams and G1

- Denominator 15 unchanged. Statuses unchanged: 5 IN_PROGRESS, 4 BLOCKED, 6 REMAINING; **DONE 0**.
- WS-04: evidence-operation idempotency (EC07 part 2) IMPLEMENTED, UNIT_TESTED and INTEGRATION_TESTED (runtime path), deployed (`7cfd94e4…`); WS-04 stays IN_PROGRESS (false-accept oracle, cross-store recovery acceptance open).
- WS-12: CI regression found and fixed (PR #85); PR #77 HOLD; L5 BLOCKED.
- G1: BLOCKED (unchanged). EC01–EC12 matrix and the cross-store contract T0–T9 / R-00–R-13 cannot be built from source here: `06-G1-REVISED-EXIT-CRITERIA-V1`, G1 Acceptance Report V2.2/V2.2.1, G1 EC Closure Plan V1.0, `HG-CROSS-STORE-RECOVERY-CONTRACT-V1`, Idea/Decision Registry and Roadmap V2 are not in the repository and not on the phone (bounded filename search, 2026-11-09). BLOCKED_SOURCE.

## 7. Limits

- No Python 3.14 in the cloud sandbox; 3.14 evidence comes from CI and the phone.
- A concurrent hourly session (lock taken 12:13:33 +07) worked on the same CI regression; its plan matched PR #85. Coordination note on PR #85.
