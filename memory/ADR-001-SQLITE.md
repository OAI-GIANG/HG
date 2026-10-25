# ADR-001 — MAEP-bound Memory persistence

- Status: Accepted as initial local adapter design; production runtime adoption remains NOT VERIFIED.
- Policy: MAEP-1.2.0.
- Scope: OAI-GIANG/HG/memory/.
- Decision: use one local SQLite database for the Memory adapter's task projection, append-only event history, candidate-bound evidence, versioned knowledge, and continuity checkpoints.

## Context

The existing MAEP Foundation has policy validators in maep/core.py and a single-writer JSONL primitive in maep/ledger.py. A separate JSONL file for the same Memory state would create a dual-write problem: a task record could persist while its event or checkpoint write failed. Reusing MAEP primitives avoids a parallel policy engine; a single SQLite transaction binds Memory state changes and their events atomically.

## MAEP-022 capability overlap and superiority assessment

Existing `maep.core` already owns policy primitives, and `maep.ledger` provides a single-writer JSONL event append/read primitive. This ADR does not replace either: Memory imports and calls the existing MAEP validators and does not mirror its event history into `maep.ledger`. The inspected repository did not contain an executable Memory/Knowledge runtime, durable checkpoint contract or mandatory resume implementation. The new adapter fills that documented integration/persistence gap while retaining MAEP and BrainOrchestrator authority boundaries. This is an `EXTEND_EXISTING` decision, not a claim that the source change is already accepted by MAEP-022; acceptance requires the candidate-bound gate and resolved evidence referenced in `MAEP-022-GATE.md`.

## Decision rationale

SQLite was selected for the adapter due to standard-library availability in Termux, transactional writes, constraints/indices, optimistic row versions, and the online backup API. Official references:
- SQLite transactions: https://www.sqlite.org/transactional.html
- SQLite isolation and single-writer model: https://www.sqlite.org/isolation.html
- SQLite backup API: https://www.sqlite.org/backup.html
- SQLite WAL: https://www.sqlite.org/wal.html
- Python sqlite3: https://docs.python.org/3/library/sqlite3.html

The implementation currently uses SQLite's default rollback-journal mode; it does not enable WAL. Each write operation uses a transaction with BEGIN IMMEDIATE, foreign keys, a busy timeout and synchronous=FULL. SQLite still serializes writes, so the adapter makes no multi-writer throughput claim.

## Data ownership

- tasks: canonical task snapshot inside this adapter, including row version, state, policy version, and candidate reference. Until BrainOrchestrator is connected, this must not be described as HG-wide canonical task state.
- maep_events: the single Memory event stream for this store; no mirror writes to the JSONL ledger.
- evidence: immutable evidence payloads bound to task, candidate and policy version.
- knowledge_records: immutable, numbered claim versions with provenance and explicit verification status.
- checkpoints: immutable continuity snapshots tied to task version, policy, candidate, event position, live-state observation and digest.
- MAEP remains the policy authority; BrainOrchestrator remains the task coordinator. Memory cannot grant permissions or execute external operations.

## Failure semantics

- Missing identity/policy evaluation, malformed grant, scope mismatch or READ_ONLY mutation: blocked/denied.
- Missing live-state observation, stale policy/candidate, unknown schema version, malformed database, bad digest, mismatched evidence or unresolved blocker: UNKNOWN/BLOCKED/STALE/CONFLICTING; no automatic repair, reset, migration or blind replay.
- A terminal task cannot resume in place; continuation requires a linked task/amendment.
- Backup/restore only targets a new path. Existing destinations are never overwritten.
- SHA-256 detects changes against the stored digest; it does not prove authorship, trusted origin, or resistance to an actor who can change both record and digest.
- Database mode is 0600; overly permissive existing database files are rejected. The obvious-secret-key-name scanner is not DLP.
- Local package tests use a fake policy evaluator. They do not satisfy runtime integration acceptance.

## Consequences and follow-up gates

1. Runtime must provide a real authenticated principal provider and trusted policy evaluator implementing the full current MAEP policy; the evaluator must not simply trust caller-supplied ALLOW data.
2. BrainOrchestrator integration must establish one task ID, dispatch/resume contract and explicit state ownership.
3. Tools adapters must independently re-check authority immediately before every side effect.
4. Restart, interrupted write, corruption and backup/restore fault-injection tests must run on the actual intended environment before production adoption.
5. Full acceptance requires evidence mapped to every Memory acceptance criterion and the exact candidate/environment. No production rollout or migration is authorized by this ADR.
6. MAEP-022 acceptance is candidate-bound. Any change to implementation, schemas, tests, this ADR, package documentation or declared fingerprint scope invalidates its fingerprint and requires gate revalidation before closure.
7. MAEP-031 improvement remains limited to this local candidate until all required gates pass; runtime-wide capability gain is not claimed.
