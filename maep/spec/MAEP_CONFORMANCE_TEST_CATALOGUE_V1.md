# MAEP Conformance Test Catalogue V1

Run: `python -m unittest discover -s maep/tests -v`. Test names are stable anchors; each test must be mapped to rule IDs when expanded.

| Test ID | Test/module anchor | Rule coverage | Expected result |
|---|---|---|---|
| T-001 | TaskContractTests.test_valid_task / test_missing_task_field_rejected | MAEP-001, 002 | valid accepted; missing objective rejected |
| T-002 | TaskContractTests.test_empty_scope_rejected | MAEP-001, 002 | incomplete scope rejected |
| T-003 | AuthorizationTests.test_exact_authorization_allowed | MAEP-003, 004 | exact authorized action accepted |
| T-004 | AuthorizationTests.test_wrong_resource_denied / test_scope_escalation_denied | MAEP-004 | mismatched resource/scope denied |
| T-005 | AuthorizationTests.test_untrusted_allow_not_enough / test_expired_grant_denied | MAEP-005 | missing trusted allow or expired grant denied |
| T-006 | test_task_store_restore WriterClaimTests; hg/tests/test_orchestrator.py SoleCoordinatorTests | MAEP-006 | second writer claim and second orchestrator refused; every store mutation without the claimed writer refused |
| T-007 | TransitionTests.test_valid_transition / test_forbidden_shortcut_rejected | MAEP-007 | valid edge accepted, shortcut rejected |
| T-008 | GateAndClosureTests.test_valid_closure / test_closure_missing_gate_rejected | MAEP-008, 013 | only complete evidence/gates permit closure |
| T-009 | ReportingAndRetryTests.test_not_run_cannot_be_reported_pass | MAEP-009, 024 | NOT_RUN cannot be promoted to PASS |
| T-010 | EvidenceTests.test_valid_evidence / test_missing_source_rejected | MAEP-010 | required evidence metadata enforced |
| T-011 | EvidenceTests.test_candidate_mismatch_rejected | MAEP-011 | candidate mismatch rejected |
| T-012 | GateAndClosureTests.test_closure_rejects_wrong_candidate_evidence / assess_candidate_change tests | MAEP-012 | evidence for old candidate not accepted for new candidate |
| T-013 | GateAndClosureTests.test_required_not_run_gate_fails | MAEP-013 | required NOT_RUN blocks acceptance |
| T-014 | ReportingAndRetryTests.test_three_attempts_stop / test_safety_stop_is_immediate | MAEP-014 | stop after three attempts or earlier safety stop |
| T-015 | EvidenceHistoryTests amendment tests | MAEP-015 | amendment links original; does not reuse ID |
| T-016 | ChangeAndRecoveryTests.test_side_effect_requires_plan | MAEP-016 | side effect without plan rejected |
| T-017 | PolicyAndReviewTests.test_policy_self_approval_rejected | MAEP-017 | self-approval denied |
| T-018 | ChangeAndRecoveryTests recovery tests | MAEP-018 | unknown non-idempotent outcome blocks blind retry |
| T-019 | TrustBoundaryAndResearchTests.test_external_instruction_never_grants_authority | MAEP-019 | content cannot grant authority |
| T-020 | TrustBoundaryAndResearchTests research tests | MAEP-020 | claim must link to known source |
| T-021 | PolicyAndReviewTests.test_internal_critique_is_not_independent | MAEP-021 | independent label requires independent evidence |
| T-022 | BlockerAndArchitectureTests architecture tests | MAEP-022 | duplication rejected absent boundary need |
| T-023 | ExecutionModeTests.test_read_only_denies_write | MAEP-023 | side effect denied in READ_ONLY |
| T-024 | ReportingAndRetryTests.test_failed_result_cannot_be_reported_pass | MAEP-024 | contradictory report rejected |
| T-025 | BlockerAndArchitectureTests blocker tests | MAEP-025 | incomplete blocker rejected |
| T-026 | TransitionTests.test_terminal_state_cannot_reopen | MAEP-026 | terminal task cannot silently reopen |
| T-027 | ChangeAndRecoveryTests destructive-plan test | MAEP-027 | destructive action requires recovery or explicit irreversibility authorization |
| T-028 | PolicyAndReviewTests policy-version tests | MAEP-028 | policy changes require new version and authorization |
| T-029 | SchemaFileTests.test_all_six_contracts_exist_and_parse | all six contracts | all JSON documents parse and declare 2020-12 |
| T-030 | SchemaFileTests.test_required_fields_are_declared | all six contracts | required fields exist in properties |
| T-031 | ClaimClassificationTests | MAEP-009 | facts require evidence; inference/hypothesis/proposal disclose limitations |
| T-032 | VerifyingEntryGuardTests | MAEP-007 | entering VERIFYING requires a recorded result and non-empty candidate_ref |
| T-033 | BlockerReassessmentGuardTests | MAEP-007, 025 | BLOCKED -> ASSESSED requires resolution evidence refs and fresh authority and risk assessment |
| T-034 | TerminalContinuationTests / TransitionTests.test_new_linked_task_can_start | MAEP-026 | no caller flag reopens a terminal task; continuation is a new DRAFT task with a TASK input reference to its predecessor |
| T-035 | ClosureInputValidationTests | MAEP-008, 013 | closure rejects non-list or non-string limitations, empty/naive/unparseable closed_at, and malformed criteria/evidence with MAEPError |
| T-036 | RetryDecisionTypeTests | MAEP-014 | bool, float, string and negative attempt counts and non-bool stop flags rejected |
| T-037 | test_policy_evaluator (all classes) | MAEP-003, 004, 005, 017, 019 | authority only from the evaluator's grant store and condition provider; caller-asserted decision/conditions/flags, expired, not-yet-valid, non-expiring (default), unknown and mismatched requests denied; invalid policy rejected at construction |
| T-038 | test_task_store (all classes) | MAEP-003, 007, 012, 015, 025, 026 | RT-01: no caller-supplied guards; RUNNING->VERIFYING denied without result; stale or bool expected_version rejected; ledger failure leaves state unchanged; authority re-evaluated at AUTHORIZED, RUNNING and reopening; evidence bound to the current candidate; BLOCKED needs a blocker, reopening needs a fresh reassessment; terminal tasks frozen |
| T-039 | .claude/hooks/test_maep_guard.py | MAEP-005, 015, 016, 017, 027 | force/mirror/all/prune pushes, direct pushes to main, deleting or lease-forcing main and recovery/*, hard reset with changes, clean with files, rm -r of .git, and delegation-file writes are blocked; unparseable risky input fails closed |

| T-040 | test_task_store_restore RestoreTests | MAEP-012, 015, 018, 026 | RT-05: restore reproduces every record field; inconsistent versions, event IDs, start states, policy versions and event types fail closed; authority re-evaluated after restart |
| T-041 | hg/tests/test_gateway.py DeniedEffectTests | MAEP-003, 005, 019, 023 | no effect after expiry, in READ_ONLY, on planned/real effect or scope mismatch, unknown tool or task, unplanned step, or failed evidence capture |
| T-042 | hg/tests/test_gateway.py ReconcileBeforeRetryTests; test_orchestrator.py RecoveryTests | MAEP-018, 025 | UNKNOWN outcome blocks further effects, survives restart, is reconciled against live state, never replayed; reopening needs fresh authority and a risk assessment |
| T-043 | hg/tests/test_acceptance.py; test_orchestrator.py NoFalseClosureTests | MAEP-008, 011, 013, 015, 024 | NOT_RUN, FAIL, wrong-candidate, unlinked or other-task evidence never closes a task; failures preserved |
| T-044 | hg/tests/test_orchestrator.py AuthorityTests, RetryLimitTests | MAEP-003, 005, 014 | a plan with any unauthorized step never starts; known failures retried at most three times |
| T-045 | hg/tests/test_cli.py | MAEP-006, 008, 023 | `python -m hg selfcheck` in a fresh process: authorized task closes, ungranted task never executes, READ_ONLY blocks; `status` writes nothing |

| T-046 | test_trust_anchor, test_trust_anchor_defects | MAEP-004, 005, 019 | RT-06 provider: F1–F11 (scope, timestamps, window, actions, principal, renewal, naive time, duplicate keys, mutable results) fail closed |
| T-047 | test_canonical_source | MAEP-005, 012, 019 | manifest read only from main at the resolved commit; feature branch never read; missing/unreachable/invalid denies; failed reload never reuses stale data; anchored ALLOW needs both grants |
| T-048 | hg/tests/test_anchored_runtime | MAEP-003, 005, 017, 019 | anchored runtime: no effect without a live manifest grant; revocation and expiry deny at the tool boundary; restart re-checks the trust root |
| T-049 | hg/tests/test_bypass | MAEP-005, 017, 023 | direct adapter calls, forged/reused/other-resource permits and unanchored runtimes cause no effect |
| T-050 | .claude/hooks/test_maep_guard.py OwnerGrantsFileTests | MAEP-017 | agent shell and edit-tool writes to owner-grants.json blocked |

| T-051 | hg/tests/test_providers.py | MAEP-005, 014 | provider errors classified; non-retryable not retried; offline mode never calls remote providers; no prompt text or key in ledgers |
| T-052 | hg/tests/test_planner.py, maep/tests/test_issuer.py | MAEP-003, 004, 005, 009, 014, 017 | planners cannot choose resource/action/authorization; invalid plans revised at most 3 times then rejected with no effect; per-task grants issued only when the owner manifest permits every step |
| T-053 | hg/tests/test_memory.py | MAEP-009, 010, 015, 019 | FACT needs evidence; contradictions refused unless superseded; history preserved; tampering reported on restore; memory never grants authority; constraints never dropped from context |
| T-054 | hg/tests/test_tools_research.py | MAEP-003, 005, 009, 018, 020 | code/URL tools only through the gateway; EXECUTE needs an EXECUTE grant; interrupted test runs stay UNKNOWN; research claims cite sources; fake citations discarded |
| T-055 | hg/tests/test_learning_ops.py | MAEP-008, 014, 015, 024 | recurring failures become lessons and guard cases; benchmark fails on unauthorized effects, false closures, failed cases or regressions; health flags pending actions and corrupt ledgers |
| T-056 | hg/tests/test_bypass.py DirectAdapterCallTests | MAEP-005, 017, 019 | no public API can bind an adapter to a caller-chosen key or mint a permit; an unbound or foreign-bound adapter performs no effect |
| T-057 | hg/tests/test_bypass.py DirectAdapterCallTests; hg/tests/test_gateway.py SerializedEffectTests, AuthorityRecheckTests | MAEP-003, 018 | authority is re-read immediately before the effect and withdrawal stops it; concurrent effects never overlap and the ledger still loads |
| T-058 | maep/tests/test_conformance_catalogue.py ConformanceCatalogueTests | MAEP-020, 021, 024 | every rule MAEP-001..028 maps to a test that exists; no catalogue row cites a test the suite no longer has |
| T-059 | maep/tests/test_conformance_catalogue.py StateTableParityTests | MAEP-007, 026 | the spec table and the implementation declare the same states and the same allowed edges |

## Test layers and limits
- Unit tests: executable local invariants in `core.py`.
- Schema-file tests: JSON syntax, dialect marker, required/property declaration only.
- NOT RUN: full JSON Schema Draft 2020-12 meta-schema validation because no standards-complete validator is available in the checked Termux environment.
- RUN (in-process): BrainOrchestrator integration, local-filesystem tool adapters, ledger-based restart recovery — `python -m unittest discover -s hg/tests -t . -v`.
- RUN (in-process): trust-root-anchored grants (RT-06) against a fake canonical source, plus the live `main` read in `python -m hg authority-check`; T-046..T-050. Amended 2026-10-28: this section previously listed RT-06 as NOT RUN.
- NOT RUN: production deployment, OS-level isolation, Android crash recovery, GitHub permissions, deploy/migration integration.
- Internal review only; no independent review is claimed.
