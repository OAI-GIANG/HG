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
| 010-012 | evidence contract/candidate binding | missing fields/mismatch/change impact | evidence record |
| 014 | retry controller policy | three failures stop same approach | attempt history |
| 015 | amendment record + single-writer JSONL ledger | amendment/duplicate-ID/corrupt-ledger tests | ledger history; not tamper-proof against privileged edits |
| 026 | transition guard | terminal-state test | transition record |
| 016,027 | change/recovery plan | side effect missing plan rejected | change record |
| 017,028 | policy version guard | self-relaxation rejected; versioned changes | policy change record |
| 018 | recovery controller | unknown non-idempotent action not replayed | recovery record |
| 019 | input trust boundary | injection cannot change authority | adversarial test output |
| 020 | research protocol | limitations/disagreement recorded | research record |
| 021 | review label guard | internal critique not independent | review metadata |
| 022 | architecture economy gate | redundant module proposal challenged | ADR |
| 023 | read-only mode guard | writes denied | action audit |

Reverse traceability: every test names rules; every evidence record names test and candidate; every mechanism lists rules it enforces. MAEP-006 still needs a BrainOrchestrator integration test. Unit tests for MAEP-020-023 exist but do not prove runtime integration. Unit tests do not prove full HG runtime behavior.
