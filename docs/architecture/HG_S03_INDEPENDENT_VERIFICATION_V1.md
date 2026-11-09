# HG S03 — Independent Verification & Evidence V1

**Status:** Implemented and fully regression-tested on candidate branch; PR/CI and merge acceptance pending.
**Branch:** `stt/s03-independent-verification-20261103`
**Base:** `e99c83e8d53cb9fd0b1ab22514a942b7d168db8b` (current `origin/main` at preflight)
**Runtime target:** Termux / Android ARM64 / Python 3.14.8 / SQLite 3.54.1
**Policy owner:** MAEP 1.1.0. No MAEP policy version change is required.

## 1. Purpose and scope

S03 supplies verifiable observations and evidence handling for HG. Its purpose is not to create a second task ledger, a second state authority, a parallel orchestrator, or a separate database. It strengthens the existing Security & Verification branch and uses MAEP as the canonical owner of task state and evidence metadata.

S03 V1 implements four capabilities:

1. Content-addressed raw evidence payload storage with SHA-256 and bounded size.
2. MAEP-linked evidence metadata and recovery-safe orphan detection.
3. A separate-process deterministic verifier for Python syntax and SQLite snapshot integrity.
4. Bounded log/error excerpts linked to the immutable raw payload hash.

Authorization remains MAEP's responsibility. A verifier PASS is not an authorization grant. A successful syntax check is not proof of semantic correctness or safe runtime behavior.

## 2. Actual baseline and architectural decisions

The preflight found these existing mechanisms:

- `maep.task_store.TaskStore` is the canonical task-state owner. It appends facts to `tasks.jsonl`, validates them on replay, enforces expected-version checks and accepts mutations through the single coordinator writer.
- `maep.ledger` provides append-only event records, fsync and cross-process locking after G1. It is not tamper-proof against a privileged same-UID filesystem writer.
- `hg.verification.evidence.AcceptanceGate` computes criteria and closure from MAEP snapshots.
- `BrainOrchestrator` previously ran registered verifier callbacks inside the same Python process and labelled these results as internal checks, not independent review.
- MAEP already provides evidence candidate binding, NOT_RUN/FAIL/UNVERIFIED semantics, failure preservation, and MAEP-014's three-meaningful-failure retry cutoff.
- G1 provides a lifetime writer session for runtime state and read-only operator views. S03 evidence writes must use the same state directory and writer session.

**Decisions:**

- Metadata stays in the existing MAEP task ledger. Do not add a SQLite evidence database.
- Raw payloads stay in a content-addressed directory under the runtime state directory: `evidence-artifacts/sha256/<first-two-hex>/<sha256>`.
- The payload is durably published before the metadata reference is appended. This is a two-step cross-store protocol, not an atomic cross-store transaction.
- An unreferenced payload after a crash is an orphan: detect and report it, never silently delete it.
- A missing or hash-mismatched payload cannot support a passing verification.
- Independent worker code runs with `python -I -B`, uses only the standard library and exposes only allowlisted checks. The worker is a separate process, but it has the same Android UID and filesystem privileges. This is process separation, not an OS sandbox or protection against hostile same-UID code.
- Do not use a model to decide deterministic checks.

## 3. Evidence storage contract

### 3.1 Metadata

The canonical record remains a MAEP Evidence record with the existing required fields: evidence ID/type, source reference, candidate reference, collection time, collector, method, result and limitations.

For stored raw payloads, `integrity_metadata` contains scalar fields:

- `payload_ref`: `sha256:<hex>`
- `sha256`: lowercase SHA-256 digest
- `payload_bytes`: exact byte length
- `payload_store`: storage implementation identifier
- `payload_kind`: declared content type/description

No new evidence database or second metadata owner is introduced.

### 3.2 Write protocol

1. Validate type and configured payload size (default maximum 4 MiB).
2. Compute SHA-256.
3. Write a private temporary file under the target digest directory.
4. fsync the payload.
5. Atomically publish the complete file using `os.replace`.
6. fsync the containing directory.
7. Append the evidence metadata to MAEP through the BrainOrchestrator's existing writer.

Crash semantics:

- Crash before publication: no valid blob is visible.
- Blob published but ledger append not completed: an orphan may remain; it is discoverable and not a valid task evidence record.
- Ledger points to missing or modified blob: verification fails closed.
- No automated orphan deletion or payload replacement is provided.

The SHA-256 reference detects content change relative to the trusted metadata reference. It does not prove the original producer identity or protect against a privileged same-UID attacker who can rewrite both payload and metadata.

### 3.3 Read and recovery

Reads require a SHA-256 reference, owner-owned regular file, no symlink at the final payload, a configured byte limit, exact length and digest match. `find_orphans()` only lists unreferenced blobs; it is deliberately non-destructive.

### 3.4 Evidence operation idempotency (EC07 part 2, revision 2026-11-09)

Additive revision. Before it, a caller that lost the acknowledgement of an evidence append could only recover by reading the ledger itself (the S03 recovery test); a plain retry appended a second record, because `BrainOrchestrator` mints a new random `evidence_id` per call.

Five layers stay separate:

| Layer | Owner | Guarantee |
|---|---|---|
| HTTP request idempotency | `hg/http_api.py` `IdempotencyStore` | One POST per Idempotency-Key; STARTED/COMPLETE/IN_DOUBT receipts. No evidence route. |
| Event ID uniqueness | `maep/ledger.py` | `task@version` appended once (re-read under the exclusive lock). |
| Evidence ID uniqueness | `TaskStore.record_evidence` | One record per `evidence_id` per task. |
| Artifact deduplication | `EvidenceArtifactStore.put` | Same bytes, same blob. |
| Evidence-operation idempotency | `TaskStore.record_evidence(..., operation_id=)` | One record per logical operation per task. |

The fifth layer relies on the second: two writers that race one operation on one task both build the same `task@version`, and the ledger refuses the second. It does not replace any other layer.

Contract:

- `operation_id` is optional: 1–128 characters from `A-Z a-z 0-9 . _ : -`, unique within one task. `BrainOrchestrator.record_artifact_evidence` and `record_observation` accept it and pass it through.
- It is stored in the EVIDENCE_RECORDED event data next to `evidence`, never inside the evidence object (`evidence.schema.json` forbids extra properties). It is written only when given.
- Canonical content: the evidence object without `evidence_id` and `collected_at`, as JSON with sorted keys and compact separators, hashed with SHA-256. Evidence sent with an `operation_id` must be deterministic apart from those two fields.
- Same task, same `operation_id`, same content: the committed `evidence_id` is returned and nothing is appended, whatever `expected_version` the retry carries. The ledger is fsynced before the replay reports success; if that fails, `LedgerOutcomeUnknown`. Limit: after an earlier fsync error, Linux may report a later fsync on a new descriptor as successful although the failed pages never reached the disk. A replay that follows a `LedgerOutcomeUnknown` from an fsync error therefore shows the record is in the ledger as read now, not that it survives a power loss.
- Same task, same `operation_id`, different content: conflict, nothing appended. Through `record_artifact_evidence`, the refused bytes remain an unlinked orphan blob.
- A replay keeps the claimed-writer, read-only and STALE-policy checks. A terminal task replays a committed operation but accepts no new one.
- Events without `operation_id` are never matched to an operation, by content or by time.
- Restore rebuilds the index from the ledger. A task holding one `operation_id` twice, or an invalid one, refuses to restore (only reachable by editing the ledger).
- The torn-tail rule (C1) applies unchanged: a torn ledger refuses replays as it refuses appends.
- Append outcome (every event type): when the append raises, the store re-reads the ledger. The exact event present, or the ledger unreadable: `LedgerOutcomeUnknown` (IN_DOUBT). Absent: "ledger append failed; state unchanged". A lock timeout followed by an unreadable ledger is reported IN_DOUBT although nothing may have been written; that is the conservative side.
- Not provided: atomicity across the artifact store and the ledger, exactly-once effects, or idempotency for internal orchestrator evidence. A re-run of verification is a new attempt (MAEP-014) and does not reuse an earlier operation.

Rollback: older releases read the new field harmlessly (they read `data["evidence"]` only). No migration.

Tests: `maep/tests/test_evidence_operations.py`, `hg/tests/test_evidence_operations_runtime.py`.

## 4. Independent-process verification contract

### 4.1 Process boundary

`IndependentVerifier` launches the repository's standalone `worker.py` using the current Python executable with `-I -B`, no shell, a fixed JSON request, an explicit working directory, a timeout and bounded response size. The worker SHA-256 is pinned when the verifier object is created and rechecked before each invocation.

This design isolates the deterministic check from the Executor's Python call stack and prevents the worker from importing HG runtime modules. It does not create a different UID, kernel sandbox, container, or complete mediation boundary. A hostile process with the same UID can still modify files or replace code outside this control.

### 4.2 Python syntax

- Allowlisted operation: `python_syntax`.
- Reads one owner-owned regular file beneath a declared root; rejects path traversal and symlink targets.
- The parent pins the worker SHA-256 before use and returns INCONCLUSIVE if the worker file changes.
- Default source size limit: 2 MiB.
- Decodes UTF-8 and calls Python `compile(source, filename, "exec", dont_inherit=True)` in memory.
- Does not execute the code and does not write `.pyc` or `__pycache__`.
- Returns PASS only for successful compilation of the exact observed bytes.
- The parent may bind the result to an expected SHA-256 for the task candidate.

The syntax result proves parse/compile acceptance by the current Python interpreter only. It does not prove behavior, imports, type correctness, security, runtime success or business logic.

### 4.3 SQLite integrity

- Allowlisted operation: `sqlite_integrity`.
- Maximum database file size: 64 MiB; verifier deadline: 5 seconds.
- Rejects adjacent `-wal`, `-shm` and `-journal` files. Only a closed, standalone, consistent snapshot may be checked.
- Opens using SQLite URI `mode=ro`, sets `PRAGMA query_only=ON` and runs `PRAGMA integrity_check(1)`.
- Keeps the O_NOFOLLOW-opened file descriptor and compares its device/inode with the pathname after SQLite opens the database, rejecting a changed path.
- Only a single result equal to `ok` is PASS. Open, timeout, malformed database or snapshot-state uncertainty is BLOCKED/INCONCLUSIVE, never PASS.

The checker must not be pointed at a live production database. A consistent offline snapshot must be captured through the owning service's approved backup procedure first.

### 4.4 Result handling

Verifier outcomes may be PASS, FAIL, BLOCKED, INCONCLUSIVE or STALE. Structured BLOCKED/INCONCLUSIVE results are preserved as such; AcceptanceGate maps them to a blocking gate. Only PASS can satisfy a mandatory gate. An unavailable verifier, malformed output, timeout, worker hash drift or candidate hash mismatch cannot create a passing gate.

The separate-process evidence limitation is recorded in the evidence record. It is not labelled as an independent human review and does not claim OS-level isolation.

## 5. Bounded evidence windows

`extract_log_window()` implements the bounded-evidence objective raised in review:

- Raw input cap: 4 MiB by default.
- Output cap: 8 KiB by default.
- Up to 8 error/exception matches with 2 context lines on either side.
- If there are no error matches, use the last 50 lines.
- Remove ANSI escape sequences and NULs in the derived excerpt.
- Preserve source SHA-256, byte length, line ranges and selection method.
- Mark the excerpt as DERIVED evidence and retain the raw payload separately.
- Mark that redaction is required before external or model disclosure.

The project repository did not contain a GTEW-1.0 specification during preflight. Therefore this implementation does not claim GTEW-1.0 conformance; it provides the bounded window behavior required by S03 until the authoritative GTEW contract is located and compared.

The extractor is not a general secret detector. Callers must redact tokens, passwords, personal data and unrelated sensitive content before model/external disclosure.

## 6. Circuit breaker and retry policy

MAEP-014 already mandates stopping an approach after three meaningful failures, with earlier stop for safety or no progress. The current BrainOrchestrator retries a known FAILED tool action at most three times, and the test suite confirms that it then becomes BLOCKED. A failed verification returns UNVERIFIED and stops the current execution path; it does not automatically call the Executor again.

S03 deliberately does not add a second in-memory retry counter or parallel retry engine. That would duplicate MAEP and could reset after a process restart. If HG later introduces an automatic verify-repair loop, it must persist its attempt/failure facts through MAEP TaskStore, use the task/candidate identity, stop after three meaningful failures, open a BLOCKED state and preserve the evidence. Reset must require fresh authorized resolution. Rollback is a separately authorized action, not an automatic consequence of a breaker opening.

## 7. READ-ONLY and production boundary

P0 inspection and baseline tests ran from a dedicated Git worktree based on the fetched `origin/main` commit. The original `~/HG` worktree already had three modified files and they were not reset, stashed, checked out or overwritten. The source-tree tests use `python -B` and `PYTHONDONTWRITEBYTECODE=1`; test outputs are stored outside the repository.

Git pre/post checks detect repository changes but are not full-filesystem monitoring. Same-UID code can write outside Git. The S03 implementation does not claim OS-level read-only protection or complete mediation against shell/Desktop Commander/other same-UID processes.

No production configuration, service process, active release, trust root, deployment state or production database is changed by this candidate implementation. Merge and deployment are separate release gates.

## 8. Acceptance matrix

| ID | Requirement | Candidate evidence/test |
|---|---|---|
| S03-AC01 | Existing MAEP/G1 authority is reused; no duplicate task store | Runtime assembly review |
| S03-AC02 | Raw evidence payload has a bounded size | Artifact store size tests |
| S03-AC03 | Payload is content-addressed and SHA-256 checked | Artifact store read/write/tamper tests |
| S03-AC04 | Evidence metadata remains in MAEP ledger | Runtime evidence integration/replay test |
| S03-AC05 | Orphan payloads are discoverable and not deleted | Orphan inventory test |
| S03-AC06 | Symlink and path traversal attempts are refused | Artifact/worker negative tests |
| S03-AC07 | Read-only evidence store refuses writes | Read-only store test |
| S03-AC08 | Python syntax is checked in a separate process | Worker and Orchestrator integration tests |
| S03-AC09 | Python check writes no bytecode | No-`__pycache__` integration test |
| S03-AC10 | Candidate hash mismatch cannot close task | Negative Orchestrator integration test |
| S03-AC11 | SQLite integrity uses read-only open on a closed snapshot | SQLite integrity and unchanged-byte tests |
| S03-AC12 | WAL/SHM/journal sidecars block snapshot check | Sidecar rejection test |
| S03-AC13 | Verifier timeout/unavailable/uncertain status cannot PASS | Structured INCONCLUSIVE gate test |
| S03-AC14 | Evidence excerpt has source hash, line refs and byte cap | Bounded window tests |
| S03-AC15 | Raw evidence is not replaced by excerpt | API contract and raw-payload store tests |
| S03-AC16 | Retry policy stops after three meaningful failures | Existing MAEP-014 RetryLimitTests |
| S03-AC17 | Existing task closure invariants remain intact | Existing Orchestrator/MAEP regression suites |
| S03-AC18 | Termux ARM64 works without new package dependency | On-device targeted and full suite |
| S03-AC19 | No production mutation/deploy from candidate | Release boundary review |
| S03-AC20 | Limitations and provenance are documented | This ADR/design and closure report |

## 9. External references

1. OWASP, Logging Cheat Sheet — event source trust, data minimization, log size/resource exhaustion, tamper detection, access control and testing: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
2. NIST IR 8397, Guidelines on Minimum Standards for Developer Verification of Software — threat modeling, automated testing, static checks, black-box/structural tests and fuzzing: https://csrc.nist.gov/pubs/ir/8397/final
3. NIST SP 800-218, SSDF 1.1 — secure software development practices and provenance: https://csrc.nist.gov/pubs/sp/800/218/final
4. NIST SP 800-218 Rev. 1 / SSDF 1.2 — Initial Public Draft published 2025-12-17; informative only, not treated as a final standard: https://csrc.nist.gov/pubs/sp/800/218/r1/ipd
5. SQLite PRAGMA documentation — integrity_check and quick_check coverage/performance: https://sqlite.org/pragma.html
6. SQLite URI filenames — `mode=ro` opens a database read-only: https://sqlite.org/uri.html
7. Python built-in `compile()` — compiles source to a code object; S03 does not execute that object: https://docs.python.org/3/library/functions.html#compile
8. Python `py_compile` — writes bytecode files; S03 therefore uses in-memory compilation for the no-write syntax check: https://docs.python.org/3/library/py_compile.html
9. Git `worktree` — supports separate linked working trees for isolated branch work: https://git-scm.com/docs/git-worktree

These references inform design decisions; they do not certify HG or establish complete security independence.
