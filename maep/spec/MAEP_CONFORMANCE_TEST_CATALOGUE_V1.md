# MAEP Conformance Test Catalogue V1

Run: `python -m unittest discover -s maep/tests -v`. Test names are stable anchors; each test must be mapped to rule IDs when expanded.

| Test ID | Test/module anchor | Rule coverage | Expected result |
|---|---|---|---|
| T-001 | TaskContractTests.test_valid_task / test_missing_task_field_rejected | MAEP-001, 002 | valid accepted; missing objective rejected |
| T-002 | TaskContractTests.test_empty_scope_rejected | MAEP-001, 002 | incomplete scope rejected |
| T-003 | AuthorizationTests.test_exact_authorization_allowed | MAEP-003, 004 | exact authorized action accepted |
| T-004 | AuthorizationTests.test_wrong_resource_denied / test_scope_escalation_denied | MAEP-004 | mismatched resource/scope denied |
| T-005 | AuthorizationTests.test_untrusted_allow_not_enough / test_expired_grant_denied | MAEP-005 | missing trusted allow or expired grant denied |
| T-006 | Integration test pending | MAEP-006 | BrainOrchestrator sole task-state owner; runtime not present yet |
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

## Test layers and limits
- Unit tests: executable local invariants in `core.py`.
- Schema-file tests: JSON syntax, dialect marker, required/property declaration only.
- NOT RUN: full JSON Schema Draft 2020-12 meta-schema validation because no standards-complete validator is available in the checked Termux environment.
- NOT RUN: BrainOrchestrator end-to-end integration, persistent append-only storage, runtime tool adapters, Android crash recovery, GitHub permissions, deploy/migration integration.
- Internal review only; no independent review is claimed.
