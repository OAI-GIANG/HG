# HG Memory Continuity V2 — R3 acceptance crosswalk K1–K8

**Date:** 2026-11-01 (Asia/Bangkok)
**Candidate:** `feature/memory-continuity-v2`
**Canonical baseline:** `main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`
**Review basis:** The owner-supplied `R3 TASK — REQUIRED FIXES` and `R3 TASK ADDENDUM — OWNER DECISION & MISSING ACCEPTANCE GATES` messages in this conversation. This crosswalk records the requirements as supplied there; it does not claim an independent owner sign-off.

## Executive result

**Engineering disposition: `ENGINEERING_COMPLETE / READY_FOR_INTEGRATION_REVIEW`.** All eight gates have implementation and test evidence. K4 and K6 carry explicit scope/identity qualifications below. This is not a merge, deployment, production-readiness or owner-acceptance declaration.

## Gate-by-gate mapping

| Gate | Requirement mapped from owner task | Implementation and evidence | Result |
|---|---|---|---|
| K1 | Restrict cross-subject conflict detection so episodic/event records do not become false conflicts. | `hg/memory/curation.py`: cross-subject semantic conflict applies only to FACT, DECISION, NOTE and PREFERENCE. EPISODIC/EVENT cross-subject output is limited to exact normalized content plus exact structured-value match. | **PASS** |
| K2 | Exercise five Brain terminal episodes and require zero false conflicts while retaining exact duplicate detection. | `BrainEpisodeCurationTests` builds five terminal outcomes through `MemoryStore.record_task_outcome` (CLOSED_VERIFIED, CLOSED_VERIFIED, FAILED, CANCELLED, CLOSED_VERIFIED), asserts no conflict/near-duplicate/cross-subject result for differing task episodes, and verifies an exact match remains visible. | **PASS** |
| K3 | Prove process-level serialization from an empty durable state and a negative control without the lock. | `hg/tests/test_memory.py`: four subprocesses begin from the same empty-ledger condition behind a barrier; locked execution yields one episode and contiguous sequence. The negative control disables `_outcome_file_lock`, synchronizes stale reloads, and demonstrates the duplicate-sequence race. | **PASS** |
| K4 / D-K4 | Apply the owner decision: `REQUIRE A NEW ASK RECEIPT AND FRESH OWNER CONFIRMATION AFTER RETRACTION OR SUPERSESSION`. An inactive receipt must not be reused to recreate a note. | Notebook binds receipt ID to subject, content digest and immutable provenance identity; exact inactive replay returns `NoteInactive` / HTTP 409. A new ASK receipt and fresh confirmation are required to save again. Tests cover retraction/supersession, changed identity, replay and new-receipt flow. | **PASS WITH IDENTITY QUALIFICATION** |
| K5 | `MODEL_DERIVED` must have verifiable model-output provenance; caller-authored/rephrased text cannot self-label as model output. | Preview accepts only an exact excerpt of the immutable ANSWERED ASK output. Answer hash, excerpt offsets, content hash and owner-confirmation digest are bound into `source_ref`; `MemoryStore` independently verifies the ASK receipt and exact excerpt for new writes. Tests reject owner-entered text, altered spans and direct Notebook forgery. Legacy replay compatibility is retained; new writes require proof fields. | **PASS** |
| K6 | Inventory durable writers and ensure all writers to the shared memory ledger use one serialization boundary. | See the writer inventory below. Every append path to the memory ledger uses the same `*.outcome.lock` sidecar lock; Notebook paths additionally take the HOME lock. `hg repair` takes the same sidecar lock while inspecting/repairing. | **PASS WITH SCOPE BOUNDARY** |
| K7 | Verify UI behavior, not source strings only: stale preview, async races, identity drift, save lock/unlock, duplicate submit and 4,000/4,001 boundary. | Shared `hg/ui/memory-save-flow.js` controller is exercised by seven Node behavioral tests; HTTP integration tests cover static asset delivery, preview identity and API length boundary. | **PASS** |
| K8 | Preserve reproducible verification evidence linked to the exact candidate, including command, HEAD, time, environment, output and exit status; rerun curation evaluation/benchmarks. | Full-suite log records command, HEAD, branch, timestamp, Android ARM64/Python/Node environment, combined console output and exit 0. Static log records revision, branch, time, 20/20 AST parses, JS checks, 7/7 Node tests and exit codes. Synthetic VI evaluation and 800/10,000-record benchmarks are included. Package evidence manifest binds the exact patch hash and hashes of all evidence files. | **PASS** |

## K4 — owner decision and identity qualification

The selected D-K4 behavior is implemented: after a note becomes RETRACTED or SUPERSEDED, the old receipt is permanently inactive; re-save requires a new ASK receipt and a fresh owner confirmation. The immutable save identity binds receipt ID, subject, canonical content digest, origin/provenance reference and a confirmation digest.

The current implementation records the authorizing principal as the `OWNER` role and retains a digest of the confirmation evidence. It does **not** bind that confirmation to a unique authenticated account/user identifier. The required re-confirmation semantics pass; a requirement for cryptographically authenticated per-user identity would be an additional design/security gate, not something this package claims to provide.

## K6 — durable writer / lock inventory

| Durable store | Append-capable entry point(s) | Serialization boundary | Scope note |
|---|---|---|---|
| Memory ledger (`memories.jsonl`) | `MemoryStore.remember` for durable layers; `promote`; `retract`; `record_task_outcome`; Notebook add/forget; Notebook trust (`NOTE_TRUST`). | `MemoryStore` instance `RLock` plus OS `fcntl.flock` on `<ledger>.outcome.lock`; reload-before-write before checking/appending. Notebook add/forget/trust also take exclusive HOME lock. `repair` takes the same per-ledger sidecar lock while inspect/repair. | This is the shared ledger governed by K6. `WORKING` layer is in-memory only and does not append. `trusted_ids` is a read path and takes the sidecar lock. |
| ASK receipt ledger (`asks-YYYY-MM.jsonl`) | `append_receipt` for ASK and SUMMARY receipts. | Exclusive HOME `flock`; `private_file` enforces private regular-file handling. `ask_archive` reads only. | Separate ledger, not a writer to `memories.jsonl`; it is the source of model provenance. |
| Model-call, action, verification/evidence journals and MAEP task store | Their own subsystem-specific writers. | Separate stores/contracts; not shared memory-ledger append paths. | They are not silently certified by this memory-ledger K6 inventory. Their independent cross-process lock/transaction contracts are outside this R3 K6 scope. |

This inventory covers all append-capable paths found for the shared memory ledger in the candidate. Generic `EventLog` instances for other journals are not treated as if they were protected by the memory sidecar lock.

## K8 — evidence bundle

The handoff ZIP includes the complete full-suite log, preliminary diagnostic log, static-check log, stress log, synthetic evaluation JSON, 800-record benchmark JSONs, the UI behavioral test source, implementation report and this crosswalk. Its `BUILD-METADATA.txt` records the exact patch SHA-256 and environment; `SHA256SUMS` binds the package's evidence/report files, and the outer checksum file binds both patch and ZIP.

Evidence limits: the 64-case Vietnamese evaluation is synthetic fixture performance, not a claim of real-world semantic accuracy. The 10,000-record stress result is a bounded local synthetic workload, not a production workload guarantee. Three full-suite skips are platform limitations (two hard-link support, one root-only chown).

## Operational boundary

- Candidate only: `~/HG-memory-continuity`, branch `feature/memory-continuity-v2`.
- Baseline: `2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`.
- Primary `~/HG` was not modified; real private `HG_HOME` ledger content was not read or written.
- No dependency installation, commit, push, merge, deployment or production operation occurred.
- DeepSeek CLI was not installed in the Termux environment. The code/test work in this candidate was performed directly by STT through Remote Desktop Commander; it is not represented as DeepSeek execution.
