# RT-01 and Agent Guard Validation Record V1

Date: 2026-10-23. Executor: STT (Claude Code cloud session) under `MAEP_OWNER_DELEGATION_V1.md`.
Base: `main` = `ea2bdf1`. Branch: `stt/rt01-enforcement`. Python 3.13.17 locally; CI on 3.13 and 3.14.

## Objective and acceptance criteria
| ID | Criterion (RUNTIME_ENFORCEMENT_PLAN_V1) | Test |
|---|---|---|
| RT-01a | Direct state mutation impossible through the public API | `test_snapshot_is_a_copy`, `test_created_task_is_copied_from_caller`, `test_callers_cannot_supply_guards`, `test_public_api_has_no_state_setter`, `test_task_must_start_in_draft` |
| RT-01b | RUNNING -> VERIFYING denied with no recorded result | `test_running_to_verifying_denied_without_recorded_result` |
| RT-01c | Stale `expected_version` rejected | `test_stale_expected_version_rejected`, `test_bool_expected_version_rejected` |
| RT-01d | Ledger append failure leaves state unchanged | `test_ledger_append_failure_leaves_state_unchanged` |
| RT-07 (CI part) | CI fails on a failing check | First CI run (`1694df0`): MAEP step passed, guard step failed because its tests were not yet committed; run concluded `failure` |

## Changes
- `maep/task_store.py` (new): `TaskStore`. Guards are derived from stored facts: task contract, a fresh `PolicyEvaluator` decision at AUTHORIZED, RUNNING and BLOCKED -> ASSESSED (MAEP-003), the recorded result and candidate, mandatory gates evaluated over stored evidence for the current candidate (MAEP-012), the stored closure, and open blockers. Entering BLOCKED needs a recorded blocker (MAEP-025); reopening needs a reassessment recorded during the current block.
- `maep/tests/test_task_store.py` (new): 41 tests.
- `.claude/hooks/maep_guard.py`, `.claude/settings.json`, `.claude/hooks/test_maep_guard.py` (new): PreToolUse guard and 29 tests.
- `.github/workflows/maep-tests.yml` (new): CI.

## Commands and results
| Command / check | Before | After |
|---|---|---|
| `python -m unittest maep.tests.test_task_store` | ImportError, exit 1 | 41 OK, exit 0 |
| `python -m unittest discover -s .claude/hooks -p "test_*.py"` | ImportError, exit 1 | 29 OK, exit 0 |
| `python -m unittest discover -s maep/tests` | 128 OK | 169 OK, exit 0 |
| JSON parse: 6 schemas and `.claude/settings.json` | — | 7/7 |
| AST parse of all Python files | — | 17/17 |
| `git diff --check` | — | clean |
| Hook invoked as Claude Code calls it (JSON on stdin, `git push origin main`) | — | exit 2, reason on stderr |

## Mutation checks (scratch copies; each mutant weakens one control)
- TaskStore: 17/18 killed. The survivor removes the explicit copy of the caller's task in `create_task`; it is equivalent because `_commit` deep-copies the record before storing it.
- Guard hook: 14/14 killed.

## Status labels
- TaskStore: IMPLEMENTED, UNIT_TESTED (real `PolicyEvaluator` and ledger, no mocks). Not INTEGRATION_TESTED: no runtime calls it.
- Guard hook: IMPLEMENTED, UNIT_TESTED, including subprocess runs with real git repositories. Not observed firing inside a live Claude Code session.
- CI: in place; results recorded on the pull request.

## Limitations
- No restart recovery: a store refuses a ledger that already holds events (RT-05).
- Authority comes from an injected `PolicyEvaluator` with test grants; no trust-root anchor (RT-06).
- The guard is a best-effort parser, blind to `$(...)`, `eval`, `xargs` and interpreter one-liners; it fails open if `python3` is missing; an agent that edits it can disable it.
- Branch protection on `main`: configured afterwards by the owner as ruleset `main-maep` (2026-10-23); the session proxy refused the branch-protection and rulesets write APIs (HTTP 403), and rulesets are not enforced on private repositories of free accounts, so the owner made the repository public and imported the ruleset.
- Internal checks only; no independent review is claimed (MAEP-021).
