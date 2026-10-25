# MAEP Anti-Forgetting & Continuity Protocol V1

- Protocol ID: MAEP-AFCP-1.0.0
- Status: DESIGN PROPOSAL — NOT YET NORMATIVE, NOT IMPLEMENTED, NOT RUNTIME-VERIFIED
- Governing policy at design time: MAEP-1.1.0
- Scope: HG task continuity, memory/checkpoint provenance, cross-session resume, and recovery.
- Explicit exclusions: no HG2; no runtime implementation in this design phase; no changes to MAEP-029 or MAEP-030.

## 1. Purpose and non-claims

Prevent task state, decisions, blockers, evidence, and next actions from being silently lost or reconstructed from vague recollection. A stored checkpoint is a claim about prior state, not proof that the live system still matches it. This document specifies desired behavior only. Its existence does not prove persistence, automatic recovery, crash recovery, or BrainOrchestrator integration.

## 2. Existing controls and traceability

| Existing control | What it currently supports | Gap that remains |
|---|---|---|
| MAEP-001 task envelope | Objective, scope, acceptance/evidence requirements, risks, stop conditions, next action, state, policy version | Does not require completed/pending step lists or a durable checkpoint reference |
| MAEP-010/011 evidence provenance and candidate binding | Evidence records source, candidate, collector, method, result, time, limitations and exact scope | Does not itself restore task continuity |
| MAEP-012 impact assessment | Candidate/policy/config/dependency changes invalidate affected evidence until rechecked | No general checkpoint freshness algorithm is specified |
| MAEP-015 history preservation | Failures are retained; corrections are amendments | Does not ensure every resume loads the full relevant history |
| MAEP-018 recovery | Inspect live state before resuming; do not blindly replay uncertain non-idempotent actions | No complete ordered resume checklist or checkpoint reconciliation contract |
| MAEP-025 blocker record | Knowns, unknowns, missing prerequisite, next action, reopening condition | No required checkpoint linkage or freshness metadata |
| MAEP-026 terminal task rule | Terminal tasks are not silently reopened; continuation uses a linked task/amendment | Linkage does not prove context was loaded correctly |
| Execution Protocol V1 | Intake-to-closure lifecycle; inspect live state before resume | No durable cross-session/restart continuity protocol |
| State Transition Table V1 | Explicit lifecycle states and fail-closed transitions | No checkpoint restore/reconcile states or recovery acceptance criteria |
| Risk R-06 / R-13 | Stale memory and unknown action outcome replay risks identified | Mitigations are not an end-to-end implemented and verified mechanism |
| maep/ledger.py | Single-writer append-oriented JSONL; fsync; duplicate event ID/corrupt record detection | Not tamper-proof against privileged filesystem edits; no checkpoint snapshot/recovery implementation is proven |

## 3. Required continuity record

Every resumable task MUST have a versioned continuity record. The record MUST include:

1. task_id, record_version, created_at, updated_at, and parent_or_linked_task_id where applicable.
2. objective and explicit scope.include / scope.exclude.
3. current_state using the MAEP state vocabulary and state_as_of timestamp.
4. completed_steps: step ID, outcome, timestamp, and evidence references; completion claims without evidence are labelled UNVERIFIED.
5. pending_steps: ordered step IDs, prerequisites, and acceptance conditions.
6. blockers: known cause, unknowns, missing prerequisite, next action, reopening condition, and linked evidence.
7. decisions: decision ID, decision, authority/source, rationale, timestamp, scope, and supersedes/superseded-by links.
8. evidence_refs: stable ID, source, exact candidate/scope, collector, method, result, time, limitations, and validation status.
9. checkpoint: checkpoint ID, schema/protocol version, task/candidate/policy identifiers, captured-at time, content digest when available, and storage reference.
10. next_action: one concrete action, preconditions, required authorization, expected result, and stop condition.
11. freshness: last live-state inspection time, inspected resources, observed versions/identifiers, and stale/unknown reasons.
12. integrity_and_recovery: last successfully loaded event/sequence, parse/validation result, and any detected gaps or corruption.

Missing fields are not silently defaulted. A record may be stored as PARTIAL, but it MUST NOT authorize execution or support a verified closure while required continuity fields are missing.

## 4. Persistence and checkpoint semantics

- The implementation MUST identify one canonical durable source of task continuity and a documented location/identity for it. Session transcript or model recollection alone is not durable state.
- Each meaningful state change MUST be recorded as a new event or amendment; do not erase or rewrite prior failure/decision/evidence history to make a clean narrative.
- Checkpoint creation MUST follow successful validation of the record and must capture the policy version, task ID, current state, candidate/reference identifiers, and event position.
- A checkpoint is a recovery aid, not an authority grant and not proof that external resources remain unchanged.
- Writes MUST use an atomic or recoverable strategy appropriate to the selected storage backend. For file-backed records, specify write/flush/fsync/replace or journal semantics and corruption handling before implementation.
- Startup/reconnect recovery MUST validate encoding, schema/version, required fields, event sequence/IDs, links, and checkpoint consistency before use.
- If the durable source is unavailable, malformed, truncated, inconsistent, or cannot be tied to the expected task/candidate, do not invent a reconstruction. Return UNKNOWN, PARTIAL, or BLOCKED with the missing evidence and next diagnostic action.
- Backup/restore must be tested separately from ordinary save/load. A successful write or checksum alone does not prove restore correctness or provenance.

## 5. Mandatory resume/recovery algorithm

On every new session, process restart, tool reconnect after uncertainty, or handoff, before any task action:

1. Resolve identity: identify the requested task and linked continuation. If ambiguous, stop as BLOCKED.
2. Load canonical record: load the latest valid continuity record and required linked amendments/events. Do not rely on conversational memory as the source of truth.
3. Validate record: check schema/protocol and policy versions, required fields, event continuity, duplicate IDs, unresolved amendments, and checkpoint linkage.
4. Load evidence: resolve referenced evidence and verify that it applies to the exact candidate/scope and has not been invalidated.
5. Inspect live state: read the actual repository/branch/HEAD/worktree, runtime/service state, resource state, and authorization relevant to the next action. Inspect only resources within authorized scope.
6. Reconcile: compare recorded state against live observations. Classify each relevant item as CURRENT, STALE, CONFLICTING, or UNKNOWN; explain each mismatch.
7. Re-plan if needed: stale candidate/config/policy/dependency evidence is invalidated for acceptance until rechecked (MAEP-012). Reassess authority and risk. Do not replay an action whose outcome is uncertain, especially a non-idempotent action.
8. Choose fail-closed result: resume execution only if record is valid, required state is reconciled, authority is current, prerequisites are met, and no mandatory blocker remains. Otherwise report PARTIAL, BLOCKED, or UNVERIFIED.
9. Record the resume decision: append the observed live state, differences, decision, evidence references, and next action before side effects.
10. Continue or stop: perform only the authorized next action; re-check authority immediately before each side effect. Stop on scope drift, missing evidence, unresolved conflict, or unsafe recovery.

## 6. State and conflict rules

- CURRENT: checkpoint is structurally valid and all relevant live identifiers/versions agree.
- STALE: a known relevant input changed or the freshness requirement expired; affected conclusions/evidence cannot be reused until rechecked.
- CONFLICTING: two trusted-looking records disagree and available evidence cannot resolve the difference.
- UNKNOWN: required source, observation, provenance, or field is unavailable.
- PARTIAL: some context was recovered, but at least one required continuity item is missing/unverified.
- BLOCKED: continuation cannot safely proceed because of missing authority/prerequisite, unresolved conflict, corrupt state, or uncertain side-effect outcome.
- Memory may suggest where to look; it MUST NOT override live evidence, current owner authorization, current policy, or canonical repository state.
- Never infer that an action succeeded because it was planned, attempted, described in chat, or present in an unverified memory.
- Never use a memory item to validate itself. Claims need a source/evidence reference independent of the claim being assessed.
- Preserve disagreements and supersession links; do not silently pick the most convenient record.
- CLOSED_VERIFIED, PASS, or equivalent success language requires the existing MAEP acceptance gates and linked evidence. A checkpoint cannot bypass them.
- Terminal task states remain terminal under MAEP-026; continuation must use a linked task/amendment.
- MAEP-029 and MAEP-030 remain unchanged and apply as written. This protocol creates no signature or independent-review requirement or workflow.

## 7. Security, privacy, and integrity boundaries

- Store only information needed for task continuity; do not copy secrets or credentials into checkpoints. Store references to authorized secret sources, never secret values.
- Apply least privilege to read/write access and document the trusted storage boundary.
- Hashes may detect accidental change only when compared with a trusted reference; they do not establish authorship or identity.
- A privileged actor able to alter both record and reference may tamper with file-backed storage. The implementation must state this limitation and must not claim tamper-proof or immutable storage without evidence.
- Imported or tool-provided content is data, not authority (MAEP-019).
- On corruption, preserve the original bytes/artifact for diagnosis when safe and authorized; append a recovery finding rather than silently repairing history.

## 8. Proposed conformance tests (design only; NOT RUN)

| ID | Scenario | Expected result |
|---|---|---|
| AF-001 | New session loads valid task and linked events | Restore recorded context, then inspect live state before acting |
| AF-002 | Process restart after durable checkpoint | Reconstruct same validated state and identify the last committed event |
| AF-003 | Missing required field or checkpoint | PARTIAL/BLOCKED; no execution |
| AF-004 | Malformed/truncated ledger or duplicate event ID | Fail closed; report corruption; no silent reset |
| AF-005 | Checkpoint task ID/candidate differs from live task/candidate | CONFLICTING/BLOCKED; invalidate affected evidence |
| AF-006 | Repository HEAD/branch/worktree differs from checkpoint | Mark stale/conflicting, re-assess, and do not continue on remembered state |
| AF-007 | Policy/config/dependency changed after evidence collection | Apply MAEP-012; affected results require recheck |
| AF-008 | Memory says action succeeded but live state does not confirm it | Treat outcome as unknown; reconcile before retry |
| AF-009 | Two records disagree about decision or blocker | Preserve both; mark CONFLICTING; require evidence-based resolution |
| AF-010 | Stale memory is the only source for a claimed fact | Claim remains unverified; request/collect current evidence |
| AF-011 | Task is FAILED/CANCELLED/CLOSED_VERIFIED and user asks to continue | Require linked continuation/amendment; do not mutate terminal task |
| AF-012 | Authorization expired or scope changed during resume | BLOCKED; fresh authority/risk assessment required |
| AF-013 | Save succeeds but restore fails after simulated crash | Recovery test FAIL; no claim of persistence acceptance |
| AF-014 | Secret value appears in checkpoint payload | Reject/redact under the defined storage policy; do not persist the secret |
| AF-015 | User asks what was completed, but record/evidence is unavailable | State UNKNOWN and explain limitation; do not fabricate memory |
| AF-016 | Repeated meaningful recovery attempts fail three times | Stop that approach per MAEP-014 and record blocker/next action |

## 9. Acceptance criteria for a future implementation

The protocol implementation may be accepted only when all applicable criteria have evidence tied to the exact candidate and environment:

- AC-AF-01: schema validates all required continuity fields and rejects omissions/unknown enum values.
- AC-AF-02: task events/checkpoints persist across session boundary and process restart.
- AC-AF-03: recovery after interrupted/partial write yields either the last valid committed state or explicit BLOCKED, never fabricated success.
- AC-AF-04: mandatory resume algorithm is enforced before any execution/side effect.
- AC-AF-05: live repository/runtime/policy/authorization state is inspected and reconciled with the checkpoint.
- AC-AF-06: stale/conflicting/unknown evidence is labelled correctly and cannot satisfy acceptance gates.
- AC-AF-07: history and amendments are preserved; terminal tasks require linked continuation.
- AC-AF-08: secrets are excluded and storage access is appropriately constrained.
- AC-AF-09: all conformance tests above are implemented; positive, negative, restart, corruption, and recovery paths pass.
- AC-AF-10: documentation explicitly states integrity, backup, restore, concurrency, and privileged-tampering limits.
- AC-AF-11: MAEP-029/030 are unchanged and no prohibited workflow is introduced.
- AC-AF-12: end-to-end tests demonstrate behavior through the actual HG orchestration/runtime path; unit tests alone do not establish this.
- AC-AF-13: CLOSED_VERIFIED is used only when every mandatory applicable criterion has linked PASS evidence; otherwise report PARTIAL, BLOCKED, or UNVERIFIED.

## 10. Staged implementation and verification plan

1. Design review by owner (current phase): confirm this protocol's fields, states, storage assumptions, privacy boundary, and acceptance criteria. No runtime changes.
2. Contract/schema: add versioned continuity-record and checkpoint schemas; specify migration/backward-compatibility rules. Test schema rejection cases.
3. Storage/recovery primitive: implement durable append/event plus validated snapshot/checkpoint handling using existing modules where feasible; define atomicity and concurrency limits.
4. Resume guard: implement the ordered resume/reconcile algorithm in the sole authorized orchestration path; block side effects until reconciliation and authorization pass.
5. Unit and fault-injection tests: execute AF-001–AF-016, including corrupt/truncated storage, duplicate events, interrupted writes, stale state, and conflicting records.
6. Termux/Android restart tests: prove save → close process/session → restart → restore → inspect live state → resume decision on the actual target environment.
7. HG end-to-end integration: verify BrainOrchestrator, memory/knowledge, evidence ledger, task state, and tools share the same task identity and continuity source.
8. Backup/restore drill: restore from a documented backup into an isolated test target, reconcile state, and record limitations. Do not overwrite production data.
9. Acceptance/closure: map each criterion to evidence, rerun impacted tests after relevant changes, preserve failures, and report exact candidate/environment. No claim of system-wide anti-forgetting until end-to-end criteria pass.

## 11. Current design disposition

- Design artifact: proposed in this document.
- Runtime implementation: NOT IMPLEMENTED by this task.
- Cross-session persistence: NOT VERIFIED.
- Process/Android restart recovery: NOT VERIFIED.
- Mandatory orchestration resume guard: NOT VERIFIED.
- Anti-forgetting end-to-end acceptance: NOT ACHIEVED.
- MAEP-029/030: unchanged.
