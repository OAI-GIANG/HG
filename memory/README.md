# HG Memory & Knowledge — MAEP-bound storage adapter

Status: **implemented locally; production runtime integration NOT VERIFIED**.

## Authority and ownership

- MAEP policy and invariants remain defined by maep/core.py and the current MAEP-1.2.0 constitution.
- BrainOrchestrator remains the only task coordinator. This package does not dispatch tools, create authority, or independently plan tasks.
- SQLite is the single durable source inside this Memory adapter for task snapshots, event stream, evidence, knowledge versions, and checkpoints. This does not prove the complete HG runtime has adopted this store.
- Runtime integration must supply an authenticated principal provider, trusted policy evaluator, live-state observer, and trusted acceptance provider. The test adapter is fake and must never be used in production.
- Tools adapters must re-check exact action authority immediately before every external side effect. Recording AUTHORIZED or RUNNING in Memory does not execute the action.

## Implemented API

Import:

    from memory import MemoryStore

MemoryStore(db_path, ...) performs no filesystem writes at construction. Initialize explicitly under MAEP authorization with initialize(task_id=...). Existing unknown, empty, corrupt, or newer-version databases are not reset, repaired, or migrated automatically.

Core methods:
- create_task(task, candidate_ref=...) — accepts only a current-policy task in DRAFT.
- get_task(task_id) and get_events(task_id) — scoped, authorized reads.
- transition_task(...) — validates transitions through MAEP. AUTHORIZED/RUNNING require an action-specific trusted grant. ACCEPTED/CLOSED_VERIFIED require a trusted acceptance provider, matching mandatory gates, candidate-bound evidence and (for closure) a MAEP closure record.
- record_evidence(...) — validates MAEP evidence and binds it to task, candidate and policy.
- put_knowledge(...) — appends a provenance-bound claim version; new claims are UNVERIFIED by default.
- verify_knowledge(...) — requires trusted write authorization and linked evidence; adds a new immutable version rather than mutating history.
- search_knowledge(...) — returns latest versions per claim; stale candidate/policy records are excluded by default.
- save_checkpoint(...) and assess_resume(...) — checkpoint and assess continuity, digest, evidence, policy, task version and live resource versions. Resume assessment never performs the next action.
- check_integrity(...), backup_to(...) and restore_to(...) — inspect local integrity or backup/restore to a new isolated path. Existing targets are never overwritten.

## Persistence and security contract

- Python standard library only; SQLite database schema version 1.
- Local database file mode is restricted to 0600; a database already accessible by group/other is rejected, not silently chmod'ed. Newly created parent directories use 0700; existing parent permissions are not automatically altered.
- Transactions use BEGIN IMMEDIATE, foreign keys, a busy timeout and synchronous=FULL. SQLite serializes writers: callers must handle MAEPError rather than blindly retrying a non-idempotent action.
- Event, evidence, knowledge and checkpoint rows have database triggers that reject UPDATE/DELETE through ordinary SQL statements. This is append-only behavior through the local database, not tamper-proof storage; a privileged actor can replace the file or alter the schema.
- SQLite online backup is used; backup and restore validate integrity/schema and refuse an existing destination. Restore is to a new isolated target only.
- A field-name scanner blocks common secret-value keys but is not a general DLP scanner. Store references to secrets, never secret values.
- Checkpoint SHA-256 detects inconsistency against its stored digest, not authorship or trust if an attacker can change both database content and digest.
- No runtime service, endpoint, database path, or production storage is automatically created by this package. Actual BrainOrchestrator binding, Android process restart, crash/fault injection and production data migration remain NOT VERIFIED.
- No dependency on GitHub Actions, paid services, external model APIs, or non-standard Python packages.

## MAEP traceability

| Control | Enforcement in this adapter |
|---|---|
| MAEP-001, 028 | Validate task contract and exact current policy version |
| MAEP-003–005 | Re-evaluate trusted authorization for each store operation; fail closed if evaluator unavailable or grant mismatches |
| MAEP-006 | No dispatch API; BrainOrchestrator remains coordinator |
| MAEP-007, 026 | MAEP transition guard, optimistic row versions, terminal-state protection |
| MAEP-008, 010–013 | Candidate-bound evidence, mandatory-gate validation, closure validation and evidence linkage |
| MAEP-009, 019–020 | Claim-type validation; external content is data, research claims trace to sources/evidence |
| MAEP-012 | Candidate change emits affected evidence references; retrieval marks stale knowledge as STALE |
| MAEP-014, 018 | Fail-closed recovery; resume checks live state and never runs the next action |
| MAEP-015 | Event/evidence/knowledge/checkpoint history is append-only through normal APIs |
| MAEP-016, 027 | Changes are explicit; backup/restore destinations are not overwritten |
| MAEP-022 | This adapter is recorded as EXTEND_EXISTING: it reuses MAEP policy primitives and fills the repository's documented persistent Memory/checkpoint gap. The candidate-bound Capability Overlap & Superiority Gate is tracked separately; no source change is reported accepted until that gate validates the exact candidate fingerprint. |
| MAEP-023–025 | Read-only mode, status discipline and durable resume-decision event |
| MAEP-029/030 | No signature functionality or independent-review workflow added |
| MAEP-031 | Evidence-driven improvement is recorded in ADR, gate evidence and acceptance matrix; no claim of runtime-wide improvement before integration evidence |

This table describes the adapter's intended and locally tested scope. It does not establish whole-runtime enforcement without a real trusted runtime binding and end-to-end evidence.

## Local verification

Run from repository root:

    python -m unittest discover -s memory/tests -v
    python -m unittest discover -s maep/tests -v

Tests use a test-only fake policy evaluator and temporary databases. They prove local contract behavior only; they do not prove production authority or end-to-end BrainOrchestrator integration.
