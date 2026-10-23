# MAEP Acceptance Checklist V1

| ID | Criterion | Status | Evidence / gap |
|---|---|---|---|
| AC-01 | Every rule has ID and normative level | PASS-DESIGN | Constitution MAEP-001..028 |
| AC-02 | Rule-to-mechanism/test/evidence traceability | PARTIAL | Traceability matrix and catalogue exist; some runtime integrations pending |
| AC-03 | Six typed JSON Schema contracts exist and parse | PASS-LOCAL | 6 JSON files parsed by Python stdlib tests |
| AC-04 | JSON Schema 2020-12 schema checks and representative instances | PASS-LOCAL | Draft202012Validator 4.17.3 checked all six schemas; positive and missing-required-field negative samples passed/rejected as expected; see SCHEMA_VALIDATION_REPORT_V1.md |
| AC-05 | Fail-closed authorization primitive | PASS-UNIT | authorization negative/positive tests |
| AC-06 | State-transition guard and terminal states | PASS-UNIT | transition tests |
| AC-07 | Acceptance/closure gate and candidate checks | PASS-UNIT | closure and gate tests |
| AC-08 | Retry, blocker and report-state controls | PASS-UNIT | policy control tests |
| AC-09 | Evolution, change and recovery policy primitives | PASS-UNIT | evolution/recovery tests |
| AC-10 | Threat model and risk register documented | PASS-DESIGN | Threat model and risk register |
| AC-11 | Official source references and limitations recorded | PASS-DESIGN | SOURCE_REFERENCES_V1.md |
| AC-12 | BrainOrchestrator runtime integration | DEFERRED-OUT-OF-SCOPE | canonical baseline had README only and no executable runtime entrypoint; integrate after HG runtime exists |
| AC-13 | Append-oriented evidence ledger primitive | PASS-FOUNDATION-WITH-LIMITATION | single-writer JSONL append/fsync and duplicate-ID rejection tested; privileged filesystem tampering is not prevented |
| AC-14 | Independent review | NOT_PERFORMED-BY-DIRECTIVE | no independent review or signature is claimed |
| AC-15 | GitHub commit/push/merge/deploy | NOT A MAEP FUNCTIONAL GATE | publication and merge status are operational metadata, not a MAEP runtime acceptance criterion |
| AC-16 | Transition guards match STATE_TRANSITION_TABLE_V1 (VERIFYING entry, blocker reassessment, terminal continuation) | PASS-UNIT | T-032..T-034; guard values are still caller-supplied until a task-state owner exists (RUNTIME_ENFORCEMENT_PLAN_V1 RT-01) |
| AC-17 | Trusted policy boundary separates caller data from authority | PASS-UNIT; BLOCKED_FOR_TRUST_INTEGRATION | T-037; no trust root or authenticated principal exists; whoever constructs PolicyEvaluator is trusted |
| AC-18 | Owner trust root and standing delegation recorded with conditions and version (MAEP-1.1.0) | PASS-DESIGN | MAEP_OWNER_DELEGATION_V1.md; conditions are not runtime-enforced; machine-verifiable trust anchor (RT-06) remains BLOCKED |
| AC-19 | RT-01 TaskStore: guards derived from stored facts, CAS versioning, ledger-first writes | PASS-UNIT | T-038; 41 tests; 17/18 mutants killed, 1 equivalent; no runtime caller, no restart recovery (RT-05) |
| AC-20 | Agent guard hook blocks destructive git operations and delegation-file writes | PASS-UNIT | T-039; 29 tests incl. subprocess runs of the hook; 14/14 mutants killed; not observed firing inside a live Claude Code session; best-effort parser |
| AC-21 | CI runs MAEP and guard tests on push and pull request, and `main` requires them (RT-07) | PASS-CI; ENFORCED-BY-GITHUB | `.github/workflows/maep-tests.yml`, Python 3.13 and 3.14; ruleset `main-maep` read back via `GET /repos/OAI-GIANG/HG/rules/branches/main`: deletion, non_fast_forward, pull_request, required_status_checks |
| AC-22 | RT-05 restore and MAEP-006 single writer on the canonical TaskStore | PASS-UNIT, PASS-INTEGRATION (in-process) | T-006, T-040; 17 tests; see RT02_RT05_VALIDATION_RECORD_V1.md |
| AC-23 | RT-02..RT-04: tool boundary, acceptance gate and BrainOrchestrator on the runtime path | PASS-INTEGRATION (in-process) | T-041..T-045; 59 tests; 17/17 mutants killed; not production, not system-wide |

## Acceptance decision
MAEP V1 foundation package passes its local design, schema, and unit-test criteria. It is not a fully integrated HG runtime release. Do not label the whole HG system CLOSED_VERIFIED. AC-12 is deferred until BrainOrchestrator exists; AC-13 passes at foundation scope with the stated tamper-resistance limitation; AC-14 is intentionally not performed or claimed. Full runtime acceptance remains a later phase.
