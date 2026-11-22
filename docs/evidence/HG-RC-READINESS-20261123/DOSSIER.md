# HG production readiness dossier — 2026-11-23

Status: **PROPOSAL ONLY.** Production is NOT approved (owner decision 2026-11-23). Nothing in this dossier
was installed, switched, restarted or reconfigured on production. A deployment needs a separate, explicit
owner approval after the conditions in §7 are met.

## 1. Production baseline (read-only)

| Item | Value | Source |
|---|---|---|
| Commit | `4eaac81132ae57028cf2432eec911a01b6ecf1fd` (#113) | ledger §15 |
| Release id | `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5` | ledger §15, G6 record |
| Switched in | 2026-11-10 18:22 +07, `~/hg-v1-evidence/switch-20261110T112210Z` | ledger §15 |
| Read 2026-11-23 02:57:49 +07 (read-only) | live LIVE; ready READY, release `030a88d5…`, integrity VERIFIED, trust LOADED (`trust_commit` = main `4b1f311`) | `~/hg-evidence/P5-READINESS-20261123/PRODUCTION_READ.json` |
| Reconciliation with the P0 baseline (2026-11-22 02:16) | boot id `1b823ef0…`, service config `349c8d0a…`, `hg` pointer `6739742c…` and release pointer: all unchanged | same file |
| Service run script | sha256 `50a162a7…`; names release `030a88d5…` | same file |
| Note | runit had restarted `hg-runtime` and `ollama` at about 02:55 on the same boot, when Termux was reopened; nothing in this mission restarted them | `sv status` uptime 139 s at 02:57:49 |
| Rollback for that switch | `sh deploy/termux/switch_service.sh --restore ~/hg-v1-evidence/switch-20261110T112210Z` | ledger §15 |

Production must be read again immediately before any switch.

## 2. Release candidates

### RC-A — `07b2bcdb2e6f33bbec7d0b6c86cdd31d90522308` (the main named in the owner decision)

| Item | Value |
|---|---|
| release_id | `3ea3a7081de5820f4fe8f589643b7aedac6f0d15e00c5e744dc383a1ec6c3dfc` |
| archive sha256 | `43fb5d33c362df21cae3ef51e2a6593aad1d1431df6643d285c7d1d316a563a0` |
| manifest sha256 | `46c2348a77a3d18c3e50439ddb66d81d1c84d7a217c7cdcd4e46bde012078572` |
| git tree | `c900573d5e9b1567ca959e1bee970b34875dfceb`, 422 files |
| Reproducibility | 4 cloud builds (2 at about 00:40 and 2 at 01:23 on 2026-11-23 +07): archives and manifests byte-identical; `verify` → VERIFIED, 422 files checked |
| Runtime checks | `hg selfcheck` PASS, `hg bench` PASS on that tree (Python 3.13.18) |

RC-A does **not** contain RC-3 (#213), RC-15 (#214) or the guard fix (this PR). It is kept as the
reproducible reference the owner asked for; it is not the candidate proposed for deployment.

### RC-B — main after this PR (proposed candidate)

Built from the merge commit of this PR once CI is green, with the same procedure (two builds, byte
comparison, `verify`, selfcheck, bench). Hashes are recorded in the ledger section of the PR that records
the build. Status: **PENDING** (built after merge).

## 3. Change set from production to main `4b1f311`

- 99 commits ahead, 0 behind; 185 files (GitHub compare `4eaac81…4b1f311`). PRs #114–#214 except the
  numbers that were closed without merge.
- Trust files unchanged: `maep/authority/owner-grants.json` and `maep/spec/MAEP_OWNER_DELEGATION_V1.md`
  have no diff between `4eaac81` and `4b1f311`.
- Security-relevant code that changed: `.claude/hooks/maep_guard.py` (agent guard, fail-closed parser),
  `maep/authority/canonical_source.py` (trust-root reader), `hg/assistant/guard.py` (note quarantine),
  ActionGateway/tool adapters (WS-03/WS-04 follow-ups), deploy scripts.
- Risk: this is a large jump. Every merged PR had green CI, but production has not run any of them.

## 4. Verification evidence for main

| Check | Result | Evidence |
|---|---|---|
| CI on `c6ddab6` (tree = main `4b1f311`) | 10/10 success | PR #214 checks |
| `hg/tests` on this PR's branch (main + guard) | 1112 OK, 6 skipped, 0 ResourceWarning | cloud run 2026-11-23 |
| `maep/tests` | 385 OK | cloud run 2026-11-23 |
| `.claude/hooks` | 42 OK | cloud run 2026-11-23 |
| `hg selfcheck` / `hg bench` (guard commit `07e2695`) | PASS / exit 0 | cloud run 2026-11-23 |
| AC-A6 assistant quality on `4b1f311` | **PASS** at v8: fact 0.844, grounded 0.812, abstain 0.857, injection 0 | `docs/evidence/HG-AC-A6-V8-20261123/` |
| v8 wrong answers (q34 NOTE, q42 MODEL) | fixed in this PR (RC-16, RC-17); a fresh v9 runs on this PR's merge SHA | same |
| Staging cutover + rollback rehearsal for RC-B | **NOT_RUN** (after RC-B is built) | — |
| Production read and reconciliation | **VERIFIED** read-only, 2026-11-23 02:57 (§1) | `PRODUCTION_READ.json` |

## 5. Rollback plan

1. Automatic: `switch_service.sh <release_id>` runs every check before the stop. After the stop, any
   failure or HUP/INT/TERM runs `rollback_cutover`. It proves the service DOWN, puts back the previous run
   script and state, starts only that pair and waits for authenticated READY. Success prints
   `ROLLBACK_READY_VERIFIED`. Otherwise the service is left proven DOWN, and every directory is left as found.
2. Manual, same release state: `sh deploy/termux/switch_service.sh --restore <switch dir>`.
3. Manual, if the new release left state the old one cannot read:
   `sh deploy/termux/switch_service.sh --restore-state <switch dir>`.
4. The `hg` command: `install_release.sh` keeps the previous pointer as `~/.config/hg/assistant-release.prev`.
5. Release `030a88d5…` stays installed under `~/hg-releases/`. `install_release.sh` never overwrites a release.

## 6. Rollback triggers

Roll back if any of these happens after the switch:
- The new release does not reach authenticated READY with a stable pid within the switch window.
- Trust is not LOADED, or integrity is not VERIFIED.
- The deploy smoke test fails (write, read-back, replay, 409).
- `/v1/chat` returns an error instead of an answer or a refusal.
- `assistant_precheck.py` or `state_precheck.py` fails.
- An unreconciled action appears.
- Any wrong answer is reported against the owner's notes.
- The owner asks for a rollback.

## 7. Conditions before proposing a production switch

1. AC-A6 is accepted on a fresh holdout run on the candidate code, with fact ≥ 0.80, no degradation of valid
   answers, and injection 0.
2. RC-B is built and reproduced, with selfcheck and bench PASS.
3. The staging rehearsal (`staging_rehearsal.sh`) for RC-B ends with `REHEARSAL_PASS`, and the production
   snapshot diff is 0 bytes.
4. Production is re-read and reconciled against §1.
5. The phone is on the charger and online.
6. The GitHub quota is ≥ 30.
7. The owner approves that specific release id.

## 8. Known limitations (not closed by this dossier)

- Finding T-1: agents share the owner's GitHub identity, so `main` cannot tell the owner from an agent.
- Model planning is BLOCKED_EXTERNAL (no live model configured for the planner).
- The note guard is best-effort pattern matching. Fencing is the containment: injection_followed was 0 on
  v4–v7.
- Pre-existing guard false positive, not introduced here: "Chatbot hay trả lời sai…" reads "hay" (often) as
  "hãy". Effect: a valid sentence can be cut from the derived copy, which loses information but cannot
  produce a wrong answer.
- Paused by owner decision and unchanged: 24 h soak (D-04), Listener Attestation (D2), Termux stability,
  PRs #205/#77/#64.
