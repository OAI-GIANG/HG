# RT-06 Trust Anchor — Validation Record V1

Executor: STT (Claude cloud session) under `MAEP_OWNER_DELEGATION_V1.md`, on the owner's mandate "RT-06 Autonomous Completion" (2026-10-23).
Repository `OAI-GIANG/HG`; branch `rt06/trust-anchor-provider-20261023`; isolated worktree (the session's other clone was not modified).
Status vocabulary: PASS, FAIL, BLOCKED_EXTERNAL, NOT_VERIFIED, NOT_APPLICABLE. Internal checks only; no independent review is claimed (MAEP-021).

## 1. Initial state (2026-10-23T11:19Z)

| Fact | Observed | Source |
|---|---|---|
| Remote | `https://github.com/OAI-GIANG/hg` (GitHub redirects to `OAI-GIANG/HG`) | `git remote -v`, push response |
| `main` | `40c959218bc2b78545c322bcc73fd667044dd43d` (merge of PR #5) | `git ls-remote` |
| Feature branch head | `cf366f6dc2f0c62702a432b82834792368bf5f37` = expected starting SHA; parent chain `cf366f6 ← 4a661fa ← df8f42a ← 40c9592` | `git ls-remote`, `git log` |
| Changes on branch vs main | `maep/authority/{__init__,trust_anchor}.py`, `maep/tests/test_trust_anchor.py`, `.github/workflows/rt06-trust-anchor-tests.yml` | `git diff --stat` |
| Ruleset | `main-maep` (25706034) active on default branch: deletion, non_fast_forward, pull_request (0 approvals), required checks `unittest (3.13)`, `unittest (3.14)`; bypass list empty | `GET /repos/.../rulesets/25706034`, `GET /repos/.../rules/branches/main` |
| Session GitHub identity | token user `OAI-GIANG` (id 337459912), repository permissions admin/maintain/push | `GET /user`, `GET /repos/...` |
| Prior CI on branch | `cf366f6`: MAEP tests success, rt06 workflow success (Python 3.12, pytest); `4a661fa`, `df8f42a`: MAEP tests failure | Actions API |
| Cause of those failures | `4a661fa:maep/tests/test_trust_anchor.py` imported `pytest`, absent in the unittest CI job | source at that commit |
| Baseline tests at `cf366f6` | maep 201 OK, hg 59 OK, hooks 29 OK, selfcheck PASS (local, Python 3.13.17) | commands in §6 |
| Provider callers | none: `maep.authority` imported only by its own tests | `grep` |

## 2. Findings

### 2.1 Provider defects (each reproduced by a probe, then by a test that failed at `cf366f6`)

| ID | Location (`maep/authority/trust_anchor.py`) | Scenario | Impact | Test | Fix |
|---|---|---|---|---|---|
| F1 | `authorize`, scope match | scope entry `123` | AttributeError instead of denial | `test_f1_*` | scope entries validated at load |
| F2 | scope match `s.rstrip("/") + "/"` | scope `""` | grant matched any resource starting `/` (e.g. `/etc/passwd`) | `test_f2_*` | scope must be `<namespace>:<path>`, path not `/` |
| F3 | `_parse_ts` | naive timestamps in manifest | TypeError at authorize | `test_f3_*` | timezone required |
| F4 | `load_manifest` | `issued_at` after `expires_at` | inverted window accepted | `test_f4_*` | rejected |
| F5 | `load_manifest` | action `"rm -rf"` | arbitrary action names accepted | `test_f5_*` | vocabulary `maep.<MAEP action>` (OTHER excluded) |
| F6 | `load_manifest` | principal `["owner"]` | non-string principal accepted | `test_f6_*` | rejected |
| F7 | `authorize` | live grant + future renewal | legitimate operation denied ("not yet valid") | `test_f7_*` | non-live grants skipped; no live grant still denies; two live grants still ambiguous |
| F8 = P8 | `load_manifest(fetch, branch=...)` | caller's `fetch` serves any bytes while `branch="main"` | **trust root asserted by the caller, not anchored**: a feature-branch or fabricated manifest was accepted | `test_feature_branch_manifest_is_never_read`, `test_feature_branch_manifest_is_not_a_trust_root` | `canonical_source.py`: constants-only GitHub REST read of `main`, pinned to the resolved commit |
| F9 | `authorize` | naive `now` | TypeError | `test_f9_*`; `test_naive_time_is_not_accepted_as_validity_input` (still a rejection, now explicit) | explicit denial |
| F10 | `json.loads` | duplicate keys (`"principal"` twice) | last-wins override | `test_f10_*` | duplicate keys rejected |
| F11 | `authorize` return | caller mutates returned grant | widened later decisions (shared mutable state) | `test_f11_*` | copies returned; loaded document detached |

### 2.2 Activation-path and bypass findings

| ID | Path | Before | Fix / status |
|---|---|---|---|
| B-a | `LocalFileWriteAdapter(root).execute(params)` called directly | **wrote the file with no authorization** (`test_unregistered_adapter_refuses_every_call` failed by writing) | single-use `_Permit` minted by the adapter's own gateway after ALLOW and the ACTION_STARTED record, bound to the exact resource; one gateway per adapter |
| B-b | provider not on any runtime path | trust anchor never consulted | `AnchoredPolicyEvaluator` wraps the evaluator shared by TaskStore and ActionGateway |
| B-c | `build_runtime(grants)` | caller-supplied grants silently trusted | refuses unless `authority=` or explicit `allow_fixture_grants=True`; exclusive; `runtime.trust` reports the mode |
| B-d | agent writes `maep/authority/owner-grants.json` locally | not blocked by the guard | guard hook treats it as an owner-only trust file (shell + edit tools) |
| T-1 | trust-root integrity on GitHub | — | **open, owner action**: see §5 |

## 3. Activation-path matrix

Protected effect inventory (`grep` over non-test code): the only effect HG can cause is a file write by `fs.write` under the adapter root (`hg/tools/gateway.py`). There is no git, commit, push, deploy, install or service code in `maep/` or `hg/`. Other writes are the two audit ledgers and work-directory creation; network use is the read-only manifest fetch.

| Entry point | Caller control | Identity source | Authorization check | Protected effect | Bypass possibility | Test evidence | Status |
|---|---|---|---|---|---|---|---|
| `build_runtime(authority=CanonicalManifest.from_github())` → `BrainOrchestrator.execute_task/resume/run` | task, plan | runtime principal (config) | PolicyEvaluator ∧ trust anchor at AUTHORIZED, RUNNING, preflight, each effect | file write | none found on public API | `test_anchored_runtime` (14) | PASS (application level) |
| `build_runtime(grants)` without authority | grants | caller | refused unless `allow_fixture_grants=True` | none | explicit fixture opt-in (tests, self-check), labelled | `test_bypass.UnanchoredRuntimeTests` | PASS |
| `ActionGateway.execute(task, step)` called directly | task id, step id | gateway principal | task RUNNING, plan from TaskStore, mode, planned-vs-real effect, adapter scope, fresh anchored decision | file write | none found | `test_gateway` DeniedEffectTests; `test_revocation_after_running_denies_at_the_tool_boundary` | PASS |
| `Adapter.execute(params[, permit])` called directly | params | none | permit from bound gateway, single use, same resource | file write | in-process code reading private state can mint a permit | `test_bypass.DirectAdapterCallTests` (6) | PASS (public API); private-state exception documented |
| `ActionGateway.reconcile(action_id)` | action id | — | none needed: inspects live state, never replays | none (ledger record only) | clearing a pending action re-enables effects, each still re-authorized | `test_gateway` ReconcileBeforeRetryTests | PASS |
| `TaskStore` mutation methods | task facts | — | `claim_writer` single writer | task state | private-state access | `test_task_store_restore.WriterClaimTests` | PASS (public API) |
| `TaskStore.restore` / ledger files | ledger contents | — | consistency checks (versions, IDs, start states, policy) | task state after restart | a consistent forged history written to the ledger file is accepted (ledgers are not tamper-proof) | `test_task_store_restore.RestoreTests` | OPEN: documented limitation |
| `AnchoredPolicyEvaluator` / `CanonicalManifest(loader=...)` built by in-process code | loader, evaluator | — | `from_github` is the only production constructor | — | in-process code can supply its own loader/evaluator | — | OPEN: application cannot prevent same-process code |
| `python -m hg selfcheck` | workdir | constant `STT` | fixture grants (explicit), full gateway path | writes only in a fresh empty workdir | by design (fixture, labelled) | `test_cli` | PASS (fixture scope) |
| `python -m hg status` | workdir | — | — | none (read-only replay) | — | `test_status_reads_ledgers_without_writing` | PASS |
| `python -m hg authority-check` | none | — | — | none (HTTPS GET of main) | — | `AuthorityCheckReport` + live run | PASS |
| Agent writes to `owner-grants.json` (Claude Code session) | tool call | — | PreToolUse guard (owner-only trust files) | trust data on disk | best-effort parser (blind to `$(...)`, `eval`, interpreter one-liners) | `OwnerGrantsFileTests`; live hook exit 2 | PASS (agent-side, best effort) |
| Change `owner-grants.json` on `main` | PR | GitHub token | ruleset: PR + required CI, no force push/deletion | trust root | **any holder of the owner token can open and merge the PR (0 approvals); agent sessions hold it** | ruleset read-back | BLOCKED_EXTERNAL (T-1) |

## 4. Enforcement levels (kept separate)

| Level | Claim | Evidence | Status |
|---|---|---|---|
| Application | Every HG runtime decision requires a live grant on `main`; denial means no effect | §3 tests; live `authority-check` → BLOCKED (404 at `40c9592`) | PASS, in-process |
| Runtime | Single writer, gateway-only effects, permits, restart blocks unreconciled actions | §3 tests; mutation checks §6 | PASS, in-process |
| OS / host (Android, Termux) | — | no shell or Remote Desktop Commander access to the owner's device from this session; no evidence HG is deployed there | BLOCKED_EXTERNAL |
| OS / host (this cloud sandbox) | none: the session runs as root; ledgers (0600) and adapter root are writable by the same user | `id` → uid 0 | NOT_VERIFIED as a boundary (none exists) |
| Server (GitHub) | `main` only via PR with required checks; no force push or deletion | ruleset and effective-rules read-back | configuration PASS; rejection not live-tested (a test push could alter `main`) |
| Production deployment | — | none exists | NOT_APPLICABLE |

## 5. Trust root: T-1 and owner actions

The canonical source is now fixed to `main` of `OAI-GIANG/HG`, read at a resolved commit. Its integrity rests on who can change `main`. Observed: the session token is `OAI-GIANG` with admin rights, the ruleset requires 0 approvals, and the bypass list is empty. On GitHub an agent session is indistinguishable from the owner, so an agent could open and merge a PR that adds a grants file. The ruleset requires green CI, but it cannot tell who merged. On 2026-10-23 an agent merge attempt for PR #5 was stopped only by the session's own permission classifier, not by GitHub.

Minimal owner actions:
1. **O-1 (G3):** add `maep/authority/owner-grants.json` to `main` through a PR the owner opens and merges. Example shape (values are the owner's decision):
   `{"trust_root":"main","policy_version":"MAEP-1.1.0","grants":[{"principal":"STT","actions":["maep.read","maep.write"],"scope":["file:out/"],"issued_at":"<UTC>","expires_at":"<UTC>"}]}`
   STT must not create this file (guard hook blocks it; MAEP-017).
2. **O-2 (T-1):** make the trust root distinguishable from agents. Smallest option: give agent sessions their own GitHub identity without admin, and add a push ruleset restricting `maep/authority/owner-grants.json` and the delegation file with only the owner as bypass actor. Alternative: require one approving review from an account agents cannot use. Signatures are not required by any current contract and are not added here.
3. **O-3 (G6):** if HG is to run on the Termux device, grant this session access to it (or run `python -m hg selfcheck` and `python -m hg authority-check` there and share the output).

## 6. Commands and results

All local runs: Python 3.13.17, worktree `/home/claude/hg-rt06`.

| Commit | Command | Result |
|---|---|---|
| `cf366f6` (baseline) | `python -m unittest discover -s maep/tests` / `-s hg/tests -t .` / hooks | 201 / 59 / 29 OK |
| `7f37adb` (F1–F11) | new defect tests before fix | 19 run: 11 failures, 2 errors |
| `7f37adb` | `python -m unittest discover -s maep/tests` | 220 OK |
| `95c696b` (source + wiring) | maep / hg / hooks | 244 / 73 / 29 OK; selfcheck PASS |
| `95c696b` | `python -m hg authority-check` (live) | exit 3, BLOCKED: owner-grants.json 404 at `40c9592` |
| `0f4bcba` (bypasses + hook) | bypass + hook tests before fix | bypass 8 run: 4 failures, 4 errors; hook 2 failures |
| `0f4bcba` | maep / hg / hooks | 244 / 82 / 32 OK; selfcheck PASS |
| `0f4bcba` | hook invoked with JSON on stdin (Write to owner-grants.json) | exit 2, blocked |

Mutation checks (scratch copies, not committed): RT-06 provider/source/wiring 17/18 killed — the survivor removes the cache-clear line and is equivalent (a failed reload keeps the timestamp stale, so the old document is never returned); permits/refusal/hook 7/7 killed.

CI on `e08ed8e` (workflow change; code identical to `0f4bcba`): see §7.

## 7. CI

| Run | Workflow | Head | Jobs | Conclusion |
|---|---|---|---|---|
| [39946842837](https://github.com/OAI-GIANG/HG/actions/runs/39946842837) | MAEP tests (required by `main-maep`) | `e08ed8e` | `unittest (3.13)`, `unittest (3.14)`: MAEP, HG runtime, self-check, guard hook steps | success (every step success) |
| [39946842838](https://github.com/OAI-GIANG/HG/actions/runs/39946842838) | rt06-trust-anchor-tests | `e08ed8e` | `rt06-anchor (3.13)`, `rt06-anchor (3.14)`: provider + defects, canonical source, anchored runtime + bypass, hook, byte-compile | success (every gating step success) |

Not verified in CI: the output of the informational step "Live trust root on main". It is `continue-on-error`, which GitHub reports as `success` whatever the exit code, and job logs are not readable through this session's proxy. The live result is established locally (§6: exit 3, BLOCKED, 404 at `40c9592`).

The record commit itself (docs only) is checked again in CI; its run IDs are in the completion report.

## 8. Gates

| Gate | Status | Evidence | Remaining |
|---|---|---|---|
| RT06-G1 repository and branch integrity | PASS | §1; every push verified local SHA = remote SHA (`7f37adb`, `95c696b`, `0f4bcba`, `e08ed8e`, record commit); no force push | — |
| RT06-G2 provider validation, fail closed | PASS (application level) | F1–F11 tests; `test_trust_anchor` (15), `test_trust_anchor_defects` (19), `test_canonical_source` (24); mutation 17/18 (1 equivalent) | — |
| RT06-G3 canonical source and legitimate owner-grant mechanism | BLOCKED_EXTERNAL | source verified live: main resolved to `40c9592`, manifest 404 → deny. Mechanism not verified: no manifest exists (O-1), and agents share the owner's GitHub identity with 0 required approvals (T-1, O-2) | owner actions O-1, O-2 |
| RT06-G4 activation-path inventory | PASS | §3 matrix from a full scan of effect primitives in non-test code | — |
| RT06-G5 no application-level bypass on discovered paths | PASS for public APIs | B-a, B-b, B-c, B-d closed with failing-first tests; documented exceptions: same-process private state, ledger tampering, in-process custom authority objects (§3 OPEN rows) | exceptions need OS-level isolation, out of application scope |
| RT06-G6 host enforcement | BLOCKED_EXTERNAL | Termux host unreachable from this session; sandbox runs as root (no boundary); GitHub ruleset configuration read back, rejection not live-tested to protect `main` | O-3; separate OS principal for HG if host enforcement is required |
| RT06-G7 regression coverage | PASS | every finding in §2 has a test that failed before its fix; mutation checks §6 | — |
| RT06-G8 Python 3.13 CI | PASS on `e08ed8e` | runs 39946842837 `unittest (3.13)`, 39946842838 `rt06-anchor (3.13)` | re-checked on the record commit |
| RT06-G9 Python 3.14 CI | PASS on `e08ed8e` | same runs, `(3.14)` jobs | re-checked on the record commit |
| RT06-G10 dedicated RT-06 workflow | PASS on `e08ed8e` | run 39946842838 | re-checked on the record commit |
| RT06-G11 remote SHA, diff, record reconciled | PASS at `e08ed8e`; final reconciliation in the completion report | `git ls-remote` after each push | — |
| RT06-G12 no unauthorized change to protected resources | PASS | `main` still `40c9592`; ruleset 25706034 unchanged on read-back; no production; work done in an isolated worktree; no other branch pushed | — |

Overall: PARTIALLY_COMPLETED_BLOCKED — all engineering gates pass; G3 and G6 wait on owner actions O-1, O-2, O-3.
