# MAEP Acceptance Checklist V1

| ID | Criterion | Status | Evidence / gap |
|---|---|---|---|
| AC-01 | Every rule has ID and normative level | PASS-DESIGN | Current constitution MAEP-001..031; see MAEP-1.2.0 |
| AC-02 | Rule-to-mechanism/test/evidence traceability within MAEP Foundation | PASS-FOUNDATION-WITH-LIMITATION | MAEP-001..031 mapped to Foundation mechanisms/tests/evidence where implemented; MAEP-006 runtime integration and mandatory MAEP-022 end-to-end authorization enforcement remain unverified |
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
| AC-14 | Independent-review workflow | PROHIBITED-BY-POLICY | MAEP-1.2.0 / MAEP-030 prohibits independent-review workflows system-wide; executable label guard rejects INDEPENDENT even when evidence is supplied |
| AC-15 | GitHub commit/push/merge/deploy | NOT A MAEP FUNCTIONAL GATE | publication and merge status are operational metadata, not a MAEP runtime acceptance criterion |
| AC-16 | Signature functionality/workflow | PROHIBITED-BY-POLICY | MAEP-1.2.0 / MAEP-029 prohibits signature functionality/workflows and signature-based gates system-wide; Foundation package contains no such feature; whole-runtime enforcement remains NOT_VERIFIED |
| AC-17 | MAEP-022 mandatory Capability Overlap & Superiority Gate | PASS-UNIT / RUNTIME-NOT-VERIFIED | Fail-closed validator and authorization-guard tests cover decision requirements; BrainOrchestrator/end-to-end runtime enforcement remains unverified |

## Acceptance decision
MAEP Foundation design, schema, traceability and unit-test criteria are recorded as passing only within their stated scope; this is not a fully integrated HG runtime release. Do not label the whole HG system CLOSED_VERIFIED. The current governing policy is MAEP-1.2.0 (`MAEP_CONSTITUTION_V1_2.md`), which supersedes MAEP-1.1.0 for current/future work, mandates the MAEP-022 capability overlap/superiority gate, adds MAEP-031 continuous evolution, and carries forward MAEP-029/030 unchanged. AC-12 remains deferred until BrainOrchestrator exists; AC-13 passes at foundation scope with the stated tamper-resistance limitation; AC-14 is prohibited by current policy, not an unperformed mandatory gate. MAEP-1.2.0 is reflected in the Foundation policy version constant and MAEP-022 capability-gate guard. MAEP-029 is a normative prohibition; this package has no signature feature, but enforcement across the whole HG runtime remains NOT_VERIFIED.
