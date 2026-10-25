# MAEP Rule Traceability Matrix V1
| Rules | Mechanism | Test coverage | Required evidence |
|---|---|---|---|
| 001-002 | task contract validator | valid/missing required fields | validator result |
| 003-005 | authorization guard | exact scope allow; missing/wrong scope deny | decision/input record |
| 006 | BrainOrchestrator boundary | integration ownership test | dispatch trace |
| 007 | transition guard | valid/forbidden transitions | transition record |
| 008,013 | acceptance/closure guard | missing gate blocks closure | gate ledger |
| 009 | claim classification guard | fact/inference/proposal tests | claim record with evidence/limitations |
| 024 | report-state discipline | NOT_RUN/FAIL cannot be reported PASS | claim/evidence mapping |
| 025 | blocker record contract | incomplete blocker rejected; valid blocker accepted | blocker record with knowns, unknowns, next action and reopening conditions |
| 010-012 | evidence contract/candidate binding | missing fields/mismatch/change impact | evidence record |
| 014 | retry controller policy | three failures stop same approach | attempt history |
| 015 | amendment record + single-writer JSONL ledger | amendment/duplicate-ID/corrupt-ledger tests | ledger history; not tamper-proof against privileged edits |
| 026 | transition guard | terminal-state test | transition record |
| 016,027 | change/recovery plan | side effect missing plan rejected | change record |
| 017,028 | policy version guard | self-relaxation rejected; versioned changes | policy change record |
| 018 | recovery controller | unknown non-idempotent action not replayed | recovery record |
| 019 | input trust boundary | injection cannot change authority | adversarial test output |
| 020 | research protocol | limitations/disagreement recorded | research record |
| 021, 030 | review label guard | internal critique allowed; INDEPENDENT always rejected, even with evidence | policy-control test output |
| 029 | system-wide policy prohibition | no signature feature/workflow or signature-based acceptance gate; no such capability is provided by MAEP Foundation | policy inspection and scoped source scan; runtime-wide enforcement remains NOT_VERIFIED |
| 022 | mandatory Capability Overlap & Superiority Gate in execution protocol plus `validate_capability_evolution_decision` | unit tests reject incomplete inventory, UNKNOWN, mismatched candidate, missing overlap comparison, non-PASS gate, unproven superiority and unauthorized retirement; runtime authorization integration still requires end-to-end proof | candidate/policy-bound decision record, inventory/comparison evidence, impact analysis, regression/migration tests, retirement authority and recovery reference |
| 031 | continuous-evolution process in execution protocol | process rule mapped to task/change planning; unit layer partially exercised through capability-decision guard; proactive discovery is not yet runtime-automated | existing task/change plan or ledger opportunity, baseline comparison, acceptance tests, risk and next action |
| 023 | read-only mode guard | writes denied | action audit |

MAEP-029/030 are normative system-wide prohibitions. This Foundation implements the MAEP-030 review-label guard; MAEP-029 has no signature capability in this package and requires continued scope inspection. Neither statement proves enforcement in runtime components outside this package.

Reverse traceability: every test names rules; every evidence record names test and candidate; every mechanism lists rules it enforces. MAEP-006 still needs a BrainOrchestrator integration test. Unit tests for MAEP-020-023 exist but do not prove runtime integration. Unit tests do not prove full HG runtime behavior.

## Anti-forgetting protocol proposal (design-only; no implementation claim)

| Control area | Existing basis | Proposed protocol requirement | Current evidence/status |
|---|---|---|---|
| Task continuity fields | MAEP-001; task schema | AFCP section 3: completed/pending steps, blockers, decisions, checkpoint, next action | Design-only; runtime schema not changed |
| Provenance and stale evidence | MAEP-010–012; R-06/R-09 | AFCP sections 2, 5–6: candidate-bound evidence and freshness reconciliation | Existing partial controls; end-to-end stale-state guard NOT_VERIFIED |
| Recovery/resume | MAEP-018; MAEP Execution Protocol V1; R-13 | AFCP section 5: mandatory load-validate-inspect-reconcile-before-action | Design-only; no mandatory runtime resume guard proven |
| History/terminal state | MAEP-015/026; JSONL ledger primitive | AFCP sections 4, 6: preserve events and use linked continuation | Existing partial controls; durable checkpoint/restore NOT_VERIFIED |
| Restart/persistence | Risk R-02/R-08; ledger primitive | AFCP sections 4, 8–10: restart, fault-injection, backup/restore and E2E acceptance | NOT IMPLEMENTED / NOT VERIFIED |
