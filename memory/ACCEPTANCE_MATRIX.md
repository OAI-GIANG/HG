# Memory & Knowledge acceptance matrix

- Governing policy: MAEP-1.2.0.
- Candidate: computed from the exact local Memory package, tests, schemas, docs and root README by memory/tests/test_maep022_gate.py.
- Test layers: local package tests are not production-runtime integration tests.

| Criterion | Required evidence | Current implementation/test | Status boundary |
|---|---|---|---|
| AC-MK-01: Versioned task/knowledge/continuity contracts reject missing or invalid core fields | Contract validators and schema checks | MAEP task/evidence/claim validators plus continuity validator; schema JSON parse tests | LOCAL PASS within exercised cases; no claim of standards-validator conformance until a Draft 2020-12 validator is available |
| AC-MK-02: Durable data survives closing/reopening the adapter/process | Reopen an independent store object on the same temporary DB and resolve task/events | test_database_reopen_preserves_task_and_event_history; backup/restore test | LOCAL PASS; Android process-kill/restart drill NOT RUN |
| AC-MK-03: Resume requires checkpoint validation and live-state reconciliation | Current, stale, conflicting, unknown, missing-observer and terminal-task cases | Checkpoint digest/reconcile, candidate conflict, missing observer and terminal tests | LOCAL PASS; actual runtime live-state adapter NOT IMPLEMENTED |
| AC-MK-04: Stale/wrong-candidate evidence cannot establish a fact | Candidate-bound evidence and stale-retrieval checks | Evidence mismatch and old-candidate knowledge filtering tests | LOCAL PASS |
| AC-MK-05: Every write requires current trusted MAEP authorization | No evaluator, mismatched grant, READ_ONLY and revocation at write boundary | Fail-closed, READ_ONLY and policy-revocation-before-write tests | LOCAL PASS with test-only policy evaluator; production authority NOT VERIFIED |
| AC-MK-06: Corrupt state never becomes fabricated success | Event-chain mutation, schema mismatch, rollback and integrity inspection | Event tampering, transaction-scoped state + event and integrity tests | LOCAL PASS for tested conditions; exhaustive crash/fault injection NOT RUN |
| AC-MK-07: Task state, events and evidence use one task/candidate/policy identity | Full MAEP task lifecycle trace with gate/evidence binding | Full MAEP task lifecycle test | IN-PACKAGE PASS using fake acceptance/policy adapters; BrainOrchestrator integration NOT VERIFIED |
| AC-MK-08: Backup/restore do not overwrite data and target an isolated path | Backup from source, restore from selected backup, validate schema/integrity and reopen result | Online backup/isolated restore test; existing destination preservation test | LOCAL PASS; off-device restore/provenance and crash interruption NOT RUN |
| AC-MK-09: History is retained and terminal tasks cannot resume in place | Append-only triggers, knowledge supersession, terminal-state checks | Event/evidence immutability, knowledge versioning and terminal-task test | LOCAL PASS for ordinary SQL/API use; privileged database edits remain outside protection |
| AC-MK-10: Evidence and authorization boundaries are documented and tested | MAEP traceability, authorization ID in event records, secret-field rejection, permissions | Local authorization, file mode, secret-key tests and docs | LOCAL PASS within tests; field-name scanner is not DLP and hashes do not prove authorship |

## Hard blockers for full HG acceptance

- No executable BrainOrchestrator runtime was present in the inspected repository inventory; real providers are not connected.
- No genuine production identity/policy evaluator is available to this local package.
- No Termux process-kill/restart or Android crash/fault-injection drill was performed.
- No production database path was initialized, migrated, restored, or changed.
- MAEP-022 candidate gate evaluation is recorded separately and must validate the exact fingerprint; this gate was completed after the initial local implementation draft, so it cannot establish that the earliest design/coding began after gate approval.
- MAEP-031 improvements are limited to this uncommitted local candidate; no commit, push, deployment or system-wide closure is claimed.
