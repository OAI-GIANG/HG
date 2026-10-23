# MAEP Phase 2 Validation Record V1

Date: 2026-10-23
Environment: Claude Code cloud container, Linux, Python 3.13.16, `jsonschema` 4.26.0 (pre-installed; not a repository dependency)
Repository: OAI-GIANG/HG
Source commit: `f7f00a75c6a1b1363993c2fb9bc023171f080038` (`stt/maep-v1-20261022`, verified on GitHub and with `git rev-parse`)
`main` at record time: `d71b771987bbdfba41edb68d27ef0ba722bafabc` (unchanged)
Execution mode: local code, test and documentation changes on a separate work branch; no change to `main` or `stt/maep-v1-20261022`; no merge or deploy.

## Baseline

`python -m unittest discover -s maep/tests`: 68 tests, OK, exit 0.

## Defects, reproduction and fix

Each defect was first reproduced by a new test that failed against the source commit. Pre-fix run of `test_defect_regressions.py`: 35 tests, 18 failures and 14 errors, exit 1; the 8 tests that passed are positive controls and guards that already held.

| Probe | Defect at source commit | Fix | Tests |
|---|---|---|---|
| P2 | RUNNING/UNVERIFIED -> VERIFYING accepted with no result or candidate | guard requires `result_recorded is True` and non-empty `candidate_ref` | VerifyingEntryGuardTests |
| P3 | BLOCKED -> ASSESSED accepted on `blocker_resolved=True` alone | also requires `blocker_resolution_evidence_refs` and `authority_reassessed`/`risk_reassessed` True | BlockerReassessmentGuardTests |
| P4 | `transition(terminal, "DRAFT", new_task=True)` returned DRAFT on a caller flag | flag removed; terminal tasks never transition; `validate_linked_task` checks a new DRAFT task with a TASK input reference to the predecessor | TerminalContinuationTests, TransitionTests.test_new_linked_task_can_start |
| P5 | `retry_decision(True)` returned CONTINUE | bool and non-int rejected; stop flags must be bool | RetryDecisionTypeTests |
| P6 | non-dict criterion raised `AttributeError` | criteria, refs and evidence records type-checked; `MAEPError` raised | ClosureInputValidationTests |
| P7 | `limitations=""` and `closed_at=""` accepted | limitations must be `list[str]`; `closed_at` must parse as timezone-aware ISO 8601 | ClosureInputValidationTests |
| P1-02 | `authorize_action` trusts caller-supplied `trusted_policy_allow` and `satisfied_conditions` | new `maep/policy.py` `PolicyEvaluator`; module absent before (ModuleNotFoundError) | test_policy_evaluator.py |

`test_core.TransitionTests.test_new_linked_task_can_start` previously asserted the P4 behavior; it now asserts the linked-task path.

`closure.schema.json` already rejects the P6/P7 inputs (checked with Draft202012Validator), so those fixes align code with the published contract.

## Results after fix

| Check | Result |
|---|---|
| `python -m unittest discover -s maep/tests -v` | 128 tests, OK, exit 0 |
| `test_defect_regressions.py` alone | 35 tests, OK, exit 0 |
| `test_policy_evaluator.py` alone | 25 tests, OK, exit 0 |
| Mutation check on a scratch copy: 11 mutants re-introducing each defect or weakening each new check | 11/11 detected by at least one failing test |
| Python AST parse of all `maep/` Python files | 13/13 OK |
| Draft 2020-12 meta-schema check of the six schemas | 6/6 PASS |
| `git diff --check` | PASS |
| `origin/main`, `origin/stt/maep-v1-20261022` after the work | unchanged (`d71b771…`, `f7f00a7…`) |

## Limitations

- Unit-level evidence only. No HG runtime exists, so nothing here is INTEGRATION_TESTED or ENFORCED.
- `transition()` guard values are still supplied by the caller; only a task-state owner can derive them (RUNTIME_ENFORCEMENT_PLAN_V1 RT-01).
- PolicyEvaluator status: BLOCKED_FOR_TRUST_INTEGRATION. Whoever constructs it is trusted; the request principal is not authenticated.
- Interpretation choices pending owner decision: RUNTIME_ENFORCEMENT_PLAN_V1 Q-1 to Q-6.
- `BRAIN_ORCHESTRATOR_MASTER_PLAN_V1.md`: NOT AVAILABLE in any accessible ref.
- Python 3.14 (the Phase 1 record's environment) was not re-run here.
- Internal critique only; no independent review is claimed.
