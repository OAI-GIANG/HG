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
| T-021 | PolicyAndReviewTests.test_internal_critique_is_allowed / test_independent_review_is_prohibited_even_with_evidence / test_independent_review_is_prohibited_without_evidence | MAEP-021, MAEP-030 | internal critique remains allowed; INDEPENDENT is always rejected, regardless of evidence |
| T-022 | BlockerAndArchitectureTests.test_duplicate_module_rejected_by_default / test_security_boundary_can_justify_module | MAEP-022 | unnecessary module duplication rejected unless a real boundary need exists; these tests alone do not prove mandatory protocol integration |
| T-023 | ExecutionModeTests.test_read_only_denies_write | MAEP-023 | side effect denied in READ_ONLY |
| T-024 | ReportingAndRetryTests.test_failed_result_cannot_be_reported_pass | MAEP-024 | contradictory report rejected |
| T-025 | BlockerAndArchitectureTests blocker tests | MAEP-025 | incomplete blocker rejected |
| T-026 | TransitionTests.test_terminal_state_cannot_reopen | MAEP-026 | terminal task cannot silently reopen |
| T-027 | ChangeAndRecoveryTests destructive-plan test | MAEP-027 | destructive action requires recovery or explicit irreversibility authorization |
| T-028 | PolicyAndReviewTests policy-version tests | MAEP-028 | policy changes require new version and authorization |
| T-029 | SchemaFileTests.test_all_seven_contracts_exist_and_parse | all seven declared contracts | all seven schema documents parse and declare 2020-12 |
| T-030 | SchemaFileTests.test_required_fields_are_declared | all six contracts | required fields exist in properties |
| T-031 | ClaimClassificationTests | MAEP-009 | facts require evidence; inference/hypothesis/proposal disclose limitations |
| T-032 | PolicyAndReviewTests.test_independent_review_is_prohibited_even_with_evidence | MAEP-030 | evidence cannot override the system-wide independent-review prohibition |
| T-033 | Scoped policy/source inspection (no signature feature exists in Foundation package) | MAEP-029 | no signature functionality/workflow or signature-based acceptance gate is introduced; whole-runtime enforcement remains NOT_VERIFIED |
| T-034 | `maep/tests/test_native_authority.py::test_caller_cannot_self_assert_applicability_and_unknown_skips_gate`, `test_required_gate_must_pass`, `test_required_gate_uses_canonical_maep_validator_and_returns_attestation`, `test_stale_gate_blocks`, `test_pass_gate_without_resolved_evidence_is_blocked`, `test_pre_effect_recheck_detects_candidate_and_policy_changes`; `maep/tests/test_trusted_providers.py::test_gate_resolves_provenance_checked_evidence_and_runs_canonical_validator`, `test_gate_blocks_when_evidence_provenance_cannot_be_verified`, `test_candidate_mismatch_blocks_trusted_gate`; `memory/tests/test_store.py::test_external_action_blocks_caller_false_when_trusted_applicability_requires_gate`, `test_external_action_blocks_when_trusted_applicability_requires_gate_without_pass_evidence`; `brain/tests/test_orchestrator.py::test_maep022_required_gate_denies_before_any_effect_and_records_deny_receipt`, `test_gate_revocation_between_authorize_and_effect_blocks_dispatch` | MAEP-022, MAEP-003-005, MAEP-012 | tests are mapped to actual authority/provider/store/dispatch layers; authorization requires trusted applicability; required capability changes require canonical current candidate/policy-bound PASS with resolved evidence; these are unit/component tests, not production-wide proof; runtime-wide integration remains NOT_VERIFIED |
| T-035 | BlockerAndArchitectureTests.test_consolidation_requires_all_superiority_dimensions / test_retirement_requires_explicit_authorization_and_recovery / test_consolidation_passes_when_superiority_and_retirement_are_evidenced / test_false_gap_claim_conflicting_with_overlap_is_rejected | MAEP-022, MAEP-027 | superiority compares required quality dimensions; deprecation/removal blocks without explicit authority and recovery; contradictory gap decision rejected |
| T-036 | Execution Protocol process check; no standalone process test yet | MAEP-031 | actionable improvement opportunities use existing task plan/ledger, tests and risk controls; proactive runtime discovery remains NOT_VERIFIED |

## Test layers and limits
- Unit tests: executable local invariants in `core.py`.
- Schema-file tests: JSON syntax, dialect marker, required/property declaration only.
- JSON Schema Draft 2020-12 meta-schema validation: recorded as PASS for all six schemas using temporary `jsonschema==4.17.3`; positive and negative representative instances also passed/rejected as expected. See `SCHEMA_VALIDATION_REPORT_V1.md`. This optional validator is not a runtime dependency. The standard-library schema-file unit tests themselves check JSON parsing, dialect marker and required/property declarations only.
- NOT RUN: BrainOrchestrator end-to-end integration, persistent append-only storage, runtime tool adapters, Android crash recovery, GitHub permissions, deploy/migration integration.
- Internal critique/testing only; independent-review workflows are prohibited by MAEP-1.2.0 and must not be claimed as performed. MAEP-029/030 are policy-level constraints in this Foundation snapshot; runtime-wide enforcement across every HG component/workflow is NOT_VERIFIED.

## Anti-forgetting protocol proposal — future tests, not executed

The detailed AF-001–AF-016 scenarios and AC-AF-01–AC-AF-13 criteria are defined in maep/spec/MAEP_ANTI_FORGETTING_CONTINUITY_PROTOCOL_V1.md. They are planned conformance coverage only; they have not been implemented or run by this design task. No test status should be inferred from their listing.
