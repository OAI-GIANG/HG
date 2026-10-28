# WP0 — Baseline forensic report

Task: `HG-MAEP-BLOCKER-ELIMINATION-20261028` · Directive `MAEP-MTC-HG-1.0` · Executor: STT (Claude, cloud session `session_01FGekwA3bpBSrnwwQKY9wSd`).
Observed: 2026-10-28 11:23–11:45 +07 (04:23–04:45 UTC). Mode: read-only. No state transition was made during this audit.

Labels: **VERIFIED** = observed in this session with the command shown. **UNVERIFIED** = not observable from here. **INFERENCE** = conclusion drawn from verified facts.

## 1. Access and tools

| Item | Result | Evidence |
|---|---|---|
| GitHub repository | `OAI-GIANG/HG`, public, default branch `main` | `gh api repos/OAI-GIANG/hg` → `permissions.admin=true, push=true` — VERIFIED |
| git clone/fetch/push | Working through the session git proxy | Clone of `main`, pushes of two new branches (WP4) — VERIFIED |
| GitHub REST | Working; GraphQL refused by the proxy (403) | `gh pr list` → 403 GraphQL; REST `pulls`, `actions/runs`, `rulesets` OK — VERIFIED |
| `GH_TOKEN` | `gh auth status` reports it invalid, yet REST calls succeed through the proxy | VERIFIED (credential is injected by the proxy; the env token itself is not used) |
| Termux device (Desktop Commander) | **Offline**, device `localhost` `00957d5b-656c-4a8d-98d7-592626705b50`, last seen 20 h before 11:23 +07 | `list_devices` twice; one call returned `Bad Gateway` — VERIFIED |
| Python here | 3.13.18 (no 3.14 locally; CI runs 3.13 and 3.14) | VERIFIED |

Consequence: everything on the phone (`~/HG`, `hg-runtime`, `~/.config/hg/*`, releases, logs, evidence directory under `$PREFIX/tmp`) is **UNVERIFIED** in this session. Nothing on the phone was read or changed.

## 2. Repository state on GitHub (VERIFIED)

| Ref | Commit | Tree | Note |
|---|---|---|---|
| `main` | [`504d1bc`](https://github.com/OAI-GIANG/HG/commit/504d1bc5d87d1754f9544f08b365fb37f56825dc) | `6440eac8bf41c2f509ab13eed793714fe0a4f6a2` | Merge of PR #60, 2026-10-28 01:47 +07. CI [run 40563237583](https://github.com/OAI-GIANG/HG/actions/runs/40563237583) success |
| `stt/maep-v1-20261022` (runtime.service line, ADR-012) | [`2b9a087`](https://github.com/OAI-GIANG/HG/commit/2b9a0872684b6ccec879d30864ebacce662235e2) | `847100e9d1f2966b6a0b742a63d5e67549f358bc` | Merge of PR #54. CI [run 40349891314](https://github.com/OAI-GIANG/HG/actions/runs/40349891314) success |
| `stt/production-composition-20261026` | [`c3e9494`](https://github.com/OAI-GIANG/HG/commit/c3e9494f08d00b582b0ba0ccf9469a8a140e2864) | `e940667fe3eebe0c4cf18e376b5a272d91c8e7fe` | = checkpoint "isolated candidate" (PR #25 head) |
| `recovery/stt-maep-v1-pre-ci-u1-20261025` | [`8dda6d4`](https://github.com/OAI-GIANG/HG/commit/8dda6d4a5cfb63614ee684e72d03bf9d5eea224b) | `cffce080acade652d7a15190b3a1dc36a1f0fd77` | = checkpoint canonical `~/HG` HEAD |
| `stt/maep-gitignore-hardening-20261027` | [`5e8e652`](https://github.com/OAI-GIANG/HG/commit/5e8e652bee127b1b3f6c58b5d9c4e8e8a2e3b48c) | — | runtime tip + 4 SQLite commits, never merged into the runtime line (CI [40457758208](https://github.com/OAI-GIANG/HG/actions/runs/40457758208) success) |

Ruleset [`main-maep` (25706034)](https://github.com/OAI-GIANG/HG/settings/rules/25706034): active on the default branch; no deletion, no non-fast-forward, PR required (0 approvals), required checks `unittest (3.13)` and `unittest (3.14)`, bypass list empty — VERIFIED. The runtime line has no ruleset.

Open PRs before this task: [#55](https://github.com/OAI-GIANG/HG/pull/55) (Claude setup), [#11](https://github.com/OAI-GIANG/HG/pull/11) (draft). PRs #56–#60 merged into `main` on 2026-10-28 01:21–01:47 +07.

## 3. Checkpoint comparison

| Checkpoint input | Current finding | Status |
|---|---|---|
| Canonical repo `/data/data/com.termux/files/home/HG` | Device offline | UNVERIFIED |
| Branch `stt/maep-v1-20261022` | Exists on GitHub at `2b9a087` | VERIFIED (remote) |
| HEAD `8dda6d4…`, tree `cffce080…` | Commit exists with exactly that tree | VERIFIED (object); phone HEAD UNVERIFIED |
| 81 commits behind upstream | `git rev-list --count 8dda6d4..origin/stt/maep-v1-20261022` = **81** | VERIFIED (consistent) |
| 46 dirty/untracked entries | Not observable | UNVERIFIED (earlier records: 18+8 on 10-25, 26 on 10-26, 44 on 10-27 — growing) |
| Active release `f7cfd766…` | Not observable. Project record says built from `main@f3dac34` | UNVERIFIED |
| runit `hg-runtime`, PID 19228 | Not observable | UNVERIFIED |
| `~/.config/hg/runtime-service.json` | Not observable | UNVERIFIED |
| Candidate `c3e9494…`, tree `e940667…` | Matches exactly | VERIFIED |
| Entrypoint `runtime.service:main`, factory `runtime.production_config:create_service` | Present at `c3e9494` and at `2b9a087` | VERIFIED |
| Staging tests 266 / 165 / 67 / 102 = 600 | Re-run here at `c3e9494`: maep 266 (1 skip), brain 165, memory 67, runtime 102, all exit 0 | VERIFIED (counts); checkpoint said 2 skipped, here 1 |
| Candidate source manifest `4b2e1243…` | Not reproduced. `GitCandidateProvider` digest of a clean `c3e9494` checkout = `sha256:bfba39f9…176b`; `sha256sum` over `git ls-files` = `b30f7f31…fecd` | UNVERIFIED (method of the original value unknown) |
| `PHASE4-CURRENT-STATUS-20261028.md`, evidence dir | On the phone; not found in GitHub, Project docs or chat history | UNVERIFIED |

## 4. Discrepancies that matter

1. **The checkpoint candidate is stale.** `c3e9494` is 57 commits / 26 merged PRs behind the runtime tip. At `c3e9494` only `maep022-record-reader` is registered, so `create_service()` blocks by design. The tip has all eight bindings registered and includes later security and correctness fixes (#39/#40 idempotency recovery and API contract, #44 effect intent persisted before the adapter, #45 authentication before GET routing). Using `c3e9494` would discard those fixes. INFERENCE: `c3e9494` is not eligible.
2. **The runtime line lacked the SQLite hardening.** The 4 commits on `stt/maep-gitignore-hardening-20261027` were never merged, and `main` received the stronger recovery-record binding (#57) that the runtime line did not have. Handled in WP4 (PR #61).
3. **The deployed `hg serve` release is behind `main`.** If it is still built from `f3dac34` (UNVERIFIED live), it lacks #36, #57 (SQLite binding) and #58 (permit minted only by the gateway; authority re-read at the effect). See WP2.

## 5. Tests run in this session (Python 3.13.18)

| Tree | Suites (counts; all exit 0) |
|---|---|
| `main@504d1bc` | maep 304, hg 256, hooks 32, `hg selfcheck` 0, `hg bench` 0 |
| runtime tip `2b9a087` | maep 284 (1 skip), memory 70, brain 172, runtime 211, composition 1, creativity 12, tools 13 |
| stale candidate `c3e9494` | maep 266 (1 skip), memory 67, brain 165, runtime 102 |

The one skip is `test_candidate_provider_observes_current_checkout_and_manifest`: the sandbox clone's remote is spelled `OAI-GIANG/hg`, and `GitCandidateProvider` matches `OAI-GIANG/HG` case-sensitively. Logs: `logs/test-main-*.log`, `logs/test-tip-*.log`, `logs/test-cand-*.log`.

## 6. Preservation

No local or remote user data was touched. The phone working tree was not reachable. In the cloud, all work used separate clones and worktrees.
