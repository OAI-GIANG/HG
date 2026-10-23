# RT-02..RT-05 Runtime Validation Record V1

Date: 2026-10-23. Executor: STT (Claude cloud session) under `MAEP_OWNER_DELEGATION_V1.md`, on the owner's directive MIID-1.0.
Base: `main` = `e1c66ee` (PR #3). Branch: `stt/miid-runtime-rt02-rt05`. Python 3.13.17 locally; CI on 3.13 and 3.14.

## Objective and acceptance criteria (RUNTIME_ENFORCEMENT_PLAN_V1 §4)
| ID | Criterion | Tests |
|---|---|---|
| RT-02a | effect denied without an ALLOW decision | `test_grant_expiring_between_start_and_effect_denies`, AuthorityTests |
| RT-02b | effect denied in READ_ONLY | `test_read_only_mode_denies_write`; self-check scenario 3 |
| RT-02c | effect denied after grant expiry between plan and execution | `test_grant_expiring_between_start_and_effect_denies`, `test_expiry_during_downtime_denies_running` |
| RT-02d | timeout reported UNKNOWN, not retried | `test_real_timeout_is_unknown`, `test_raised_timeout_is_unknown`, `test_unknown_outcome_blocks_further_effects` |
| RT-03a | closure denied for another candidate or a NOT_RUN gate | `test_evidence_for_other_candidate_is_not_counted`, `test_missing_verifier_is_not_run_not_pass` |
| RT-03b | evidence recorded by a different task rejected | `test_evidence_recorded_on_another_task_is_ignored` |
| RT-04a | a second dispatcher cannot obtain the TaskStore write handle | `test_second_orchestrator_cannot_claim_writer`, WriterClaimTests |
| RT-04b | happy path reaches CLOSED_VERIFIED only with linked evidence | `test_task_reaches_closed_verified_only_with_linked_evidence` |
| RT-05 | after restart, an UNKNOWN non-idempotent action blocks new effects until reconciled | `test_restart_preserves_block_and_pending_action`, `test_pending_action_survives_restart`, RestoreTests |

## Changes
- `maep/task_store.py`: shared per-event appliers used by both live mutations and `restore`; `TaskStore.restore` (RT-05) replays the ledger and fails closed on inconsistent history; `claim_writer` + `TaskWriter` (MAEP-006); `record_plan` (ASSESSED only). Existing behaviour of an unclaimed store is unchanged.
- `maep/tests/test_task_store.py`: the pinned public-API set now includes `claim_writer`, `record_plan`, `restore` (intent unchanged: no state setter; `test_plan_is_not_a_state_setter` added).
- `maep/tests/test_task_store_restore.py` (new): 17 tests.
- `hg/` (new): `brain/plan.py`, `brain/orchestrator.py`, `tools/gateway.py`, `verification/evidence.py`, `runtime.py`, `__main__.py`; `hg/tests/` 59 tests.
- `.github/workflows/maep-tests.yml`: adds the HG suite and the self-check.
- Docs: CLAUDE.md status, runtime plan §6, conformance catalogue T-006 and T-040..T-045, acceptance checklist AC-22/23, READMEs, `docs/architecture/MIID_AUDIT_AND_CAPABILITY_MATRIX_V1.md`.

## Commands and results
| Command / check | Before (`e1c66ee`) | After |
|---|---|---|
| `python -m unittest discover -s maep/tests -v` | 169 OK | 186 OK, exit 0 |
| `python -m unittest discover -s hg/tests -t . -v` | no such suite | 59 OK, exit 0 |
| `python -m unittest discover -s .claude/hooks -p "test_*.py" -v` | 29 OK | 29 OK, exit 0 |
| `python -m hg selfcheck` | no entry point | PASS 3/3, exit 0 |
| Run with `-W error::ResourceWarning` | — | clean |

## Mutation checks (scratch copies, not committed)
17/17 killed: gateway ignoring a DENY, a pending action, READ_ONLY, adapter scope or planned resource; store not enforcing the writer claim or allowing a second claim; restore skipping version, start-state or policy-version checks; plan allowed outside ASSESSED; gate treating NOT_RUN as PASS, ignoring candidate or criterion link; orchestrator skipping preflight, retrying without limit or ignoring the gate report.

## Reconciliation with PR #3
A first version of this work (local branch only, never pushed) had its own TaskStore. PR #3 merged a TaskStore while this work was in progress; keeping both would create two task-state owners (MIID §7, MAEP-022, ADR-009). The local one was dropped and PR #3's store extended instead.

## Status labels
- TaskStore extensions, ActionGateway, AcceptanceGate, BrainOrchestrator, restart recovery, CLI: IMPLEMENTED, INTEGRATION_TESTED (in-process, real filesystem and ledgers, no mocks of MAEP). ENFORCED on the HG runtime path only.
- Not END_TO_END_VERIFIED in a deployed system: none exists.

## Limitations
- In-process capability boundaries, not OS isolation; code in the same process can reach private attributes.
- Ledgers are not tamper-proof (single writer, append-only API).
- One authorization request per task in the store; the gateway preflights every step before AUTHORIZED and re-checks each before its effect.
- Grants come from fixtures; no trust-root anchor (RT-06 BLOCKED).
- Verifiers are internal checks; no independent review is claimed (MAEP-021).
- Plans are supplied as data; no autonomous planning or model provider exists yet.
