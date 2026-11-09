# HG MASTER COMPLETION LEDGER V1 — RECONCILIATION 2026-11-10: PR #87 and PR #88 merged

**Repository:** `OAI-GIANG/HG`
**Observed:** 2026-11-10 02:30–02:55 +07, GitHub REST, git, Desktop Commander on the owner's phone (device `22e6ee74-…`, read-only)
**Relation:** ADDITIVE to `…_20261109C.*`. Workstream rows not listed in the CSV are unchanged from reconciliation C.

**Labels:** FACT = observed during this reconciliation; INFERENCE = derived; UNVERIFIED = not established.

## 1. Merges

| PR | Exact head | Merge commit on `main` | Gates (FACT) |
|---|---|---|---|
| #87 B4 ledger admission and state-swap locks | (squash) | `163be5dc5fe5a7b386ee8465a5d6b2f44adfa5be`, 2026-11-09T17:38Z | Push CI on the merge SHA: run 42666536949 success. Merged by an earlier session; not recorded in reconciliation C. |
| #88 B3 reconcile exception → UNKNOWN | `64e4c088d11e0c5d7d3e8c664a3eb2d0f7b64c3e` (2 ahead / 0 behind `163be5d`) | `d7b94d8bd0f5b4ee894e0a53c9e8d5468aae04f6`, squash, 2026-11-09T19:43Z | Exact-head CI 6/6 success (unittest 3.13 129337576400, 129337547302; 3.14 129337576798, 129337547754; rt06-anchor 3.13 129337577404, 3.14 129337578006). Termux exact-head evidence (PR comment 2026-11-09T17:49Z): MAEP 362 OK, HG 578 OK, selfcheck PASS, bench PASS, `~/hg-v1-evidence/b3-pr88-post-odir-20261110/`. Push CI on the merge SHA: run 42686008297 success. Recovery point `recovery/main-pre-pr88-20261110` = `163be5d`. |

Cloud re-run on the #88 exact head (this session, Linux, Python 3.13.18, **uid 0**): MAEP 362 OK; hooks 32 OK; selfcheck PASS; bench ran; HG 578 with **1 failure**: `hg.tests.test_release.SealedReleaseTests.test_sealed_import_without_dont_write_bytecode_leaves_tree_unchanged`. The same test fails identically on `163be5d` as root, and passes in CI and on Termux (non-root). INFERENCE: root bypasses the sealed tree's directory permissions, so Python writes `__pycache__`; the sibling test `test_sealed_release_verifies_and_refuses_owner_writes` already skips under root, this one does not. Not a #88 regression. Recorded as backlog item N-01 (below), not changed here.

## 2. Deployment

- FACT (phone, 02:46 +07): `hg-runtime` up 4344 s (since ≈01:34 +07), release `54547829c939…`. The source commit of that release was not established here: **UNVERIFIED** whether it is `163be5d` (#87).
- #88 (`d7b94d8`) is **not deployed** (NOT_EXECUTED). Another session is active on the phone (evidence dirs `convergence-wp0…`, `wp1-provider-convergence…`, `wp2-modelplanner-maep…`, `wp4-release-build-20261110` written up to 02:09 +07; branch `stt/hg-capability-convergence-v1-20261110` head `0feca8a`, built at 02:09). To avoid two sessions switching the same runtime, this session did not deploy.

## 3. Hourly-session coordination

- `~/hg-v1-evidence/.autonomous-run.lock` unchanged since 2026-11-09 17:14 +07 (content: takeover from 12:13). Not reclaimed.
- No `ACTIVE_OWNER_HOLDS` file under `~/hg-v1-evidence`.

## 4. New backlog

- **N-01** (DISCOVERED, LOW): `test_sealed_import_without_dont_write_bytecode_leaves_tree_unchanged` fails when the suite runs as root. Options: skip under `os.geteuid() == 0` like its sibling (the guarantee depends on directory permissions), or make the assertion independent of permissions. Not a release blocker: CI and the device run non-root.
- **N-02** (DISCOVERED): deploy `main` ≥ `d7b94d8` to the phone once the active convergence session has finished its release work; record the release id ↔ commit mapping (closes the UNVERIFIED in §2).

## 5. Workstreams and G1

Denominator 15 unchanged. DONE 0. G1 BLOCKED (unchanged). WS-04 and WS-12 deltas in the CSV.
