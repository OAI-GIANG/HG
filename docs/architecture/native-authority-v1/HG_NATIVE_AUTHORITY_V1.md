# HG Native Authority V1 — MAEP-Controlled Design

**Document ID:** HG-NATIVE-AUTHORITY-V1
**Status:** DESIGN_ONLY
**Repository:** OAI-GIANG/HG
**Design baseline observed before writing:** branch `stt/maep-v1-20261022`, HEAD `f7f00a75c6a1b1363993c2fb9bc023171f080038`
**Operational note:** the worktree was already dirty before this document was added. This specification does not claim implementation, test, or runtime verification.
**Scope exclusion:** MAEP-029 and MAEP-030 are not modified by this design.

## 1. Purpose and decision

HG should own a coherent, offline-first authority mechanism rather than indefinitely waiting for a legacy implementation to be found. This document defines a new design for the authority boundary used by MAEP, MAEP-022, Runtime, BrainOrchestrator, Unified Memory and functional branches.

The design reuses existing MAEP governance records and ledger mechanisms where available. It does **not** introduce a competing coordinator, standalone mandatory database, or second governance lifecycle. New authority components are library-level contracts, composed through one runtime composition root.

The system must not confuse "newly designed" with "trusted". A newly written provider is untrusted until its bootstrap process, state protection, provenance, tests and runtime behavior have been verified.

## 2. Goals and non-goals

### Goals

- Establish an explicit, owner-approved bootstrap trust root.
- Resolve principal identity from authenticated context, not caller-provided display fields.
- Evaluate policy against exact principal, action, resource, scope, task, policy version, time and required gates.
- Independently classify capability applicability using reviewed rules and repository-derived facts.
- Bind decisions and evidence to the exact candidate, policy version, task, and requested action.
- Fail closed on missing, stale, mismatched, malformed or unverifiable authority inputs.
- Persist auditable decisions and state transitions using HG's approved existing evidence/ledger path.
- Remain offline-first and compatible with Termux / Android ARM64 using Python standard library where practical.

### Non-goals

- Automatically granting HG authority to mutate its own trust root or relax its own policy.
- Treating a hash alone as proof of authorship, authorization, or independent provenance.
- Treating a self-reported status or an unanchored content digest as proof that a policy is authorized.
- Automatically authorizing deploy, deletion, migration, push, merge, or other high-risk actions.
- Claiming runtime readiness, Level 5, or CLOSED_VERIFIED from a design document.
- Reading authority or secrets from HG2, other repositories, or unrelated runtimes.

## 3. Status vocabulary

Every component, contract and acceptance criterion has one of these labels:

- `DESIGN_ONLY`: specified here; not asserted to exist in executable form.
- `IMPLEMENTED`: source implementation has been identified at a precise revision; does not imply tests passed.
- `TESTED`: named, reproducible tests passed against the stated source/candidate.
- `RUNTIME_VERIFIED`: behavior observed in the identified target runtime with candidate-bound evidence.
- `BLOCKED`: a required prerequisite or proof is missing.
- `NOT_RUN`: no execution evidence was produced.

This artifact's status is `DESIGN_ONLY`. No component becomes IMPLEMENTED merely because an interface is described.

## 4. Trust and threat model

### 4.1 Assets

1. Bootstrap trust-root record and its owner authorization.
2. Principal registry and role/capability assignments.
3. Active policy version and policy-change approvals.
4. Applicability rules and their version/provenance.
5. Candidate identity (repository, commit/tree, source manifest and build identity where applicable).
6. Task plan, authorization decisions, gate results and evidence records.
7. Runtime effects and side-effect idempotency records.
8. Memory state, continuity records, recovery metadata and append-only audit history.

### 4.2 Adversaries and failure sources

- Prompt-injected or malicious user/tool/repository content.
- A caller that supplies `trusted_policy_allow=true`, `capability_affecting=false`, or similar self-asserted facts.
- A compromised branch adapter attempting to bypass Brain or the gate.
- Replay of an old authorization, evidence record, nonce, or successful operation.
- Concurrent policy, candidate, memory or task changes between check and effect (TOCTOU).
- Clock skew, unavailable clock, corrupt storage, truncated writes, process crash or partial tool output.
- Incorrect test fixtures accidentally wired into production.
- A developer or runtime that accidentally executes from an unintended checkout.
- A legitimate but incomplete new implementation whose authors confuse its own assertions with independent proof.

### 4.3 Trust zones

- **TZ0 — Owner-controlled bootstrap:** initial authorization and out-of-band approval for the first trust-root record. Only the owner-approved bootstrap process can create the initial root.
- **TZ1 — Protected local authority state:** trust root, principals, active policy pointer, versions, revocations and monotonic sequence. This state is protected by host filesystem permissions and integrity checks; these controls are defence-in-depth, not proof against a fully compromised device owner/root.
- **TZ2 — HG governance/runtime:** MAEP, policy evaluator, gate coordinator and BrainOrchestrator.
- **TZ3 — Scoped branch adapters:** Memory, research, creativity, tools and automation. They receive narrow action grants, never root authority.
- **TZ4 — Untrusted inputs:** user text, tool output, repository content, imported records, model claims and external data.
- **TZ5 — Test-only fixtures:** fake principals/policies/providers and simulated outcomes; they must be explicitly marked and impossible to select in production mode by implicit fallback.

### 4.4 Security assumptions and limits

- The initial trust-root approval requires an explicit owner-controlled step that is separate from the task being authorized. It cannot be manufactured by the task itself.
- A local file hash detects change only when compared with a trusted reference; a local hash stored beside the file does not provide independent tamper resistance.
- A content digest is only an integrity identifier; it does not establish authorization. A trust reference must come from the owner-approved authority source, not from a neighboring mutable file.
- Offline operation means no network service is required for normal decisions. It does not eliminate the need for owner-controlled bootstrap authorization, secure local permissions, backups and scoped regression checks for root changes.
- On a device fully controlled by an attacker with equivalent privileges, purely local software cannot guarantee an untampered trust root. In that case, high-risk actions remain blocked until a stronger external or hardware-backed trust mechanism is available.
- No clock, storage, candidate identity or evidence source may silently degrade to caller-provided data when its trusted source is unavailable.

## 5. Architecture and dependency map

```text
Owner-approved bootstrap ceremony
             |
             v
        TrustRoot
             |
             +--------------------+
             v                    v
 PrincipalRegistry         Policy version store
             |                    |
             +----------+---------+
                        v
                PolicyEngine
                        |
 Repository / candidate facts --> CandidateIdentityProvider
                        |
 Reviewed rules + observed facts --> ApplicabilityEngine
                        |
 Existing MAEP task / evidence / ledger records
                        v
         MAEP + MAEP-022 Capability Gate
                        |
           authorization decision bound
          to task + action + candidate +
              policy + evidence versions
                        v
             Runtime composition root
                        |
                 BrainOrchestrator
                  /      |       \
                 v       v        v
              Memory  Research  Tools/Automation
                 \      |       /
                  narrow scoped adapters
                        |
              pre-effect authorization
                        |
            effect receipt / reconciliation
                        v
                Existing evidence ledger
                        |
               RecoveryManager
```

Authority is not a coordinator. BrainOrchestrator remains the single coordinator. MAEP remains the mandatory governance protocol. MAEP-022 remains an applicability/overlap/superiority gate under the existing protocol. Memory and branch adapters cannot override either.

### 5.1 Composition root

One production composition root must explicitly construct providers and inject them into MAEP, Brain, Memory and each adapter. It must:
- Resolve its repository root and source/build identity at startup.
- Refuse an unknown or mismatched checkout/candidate.
- Load only the selected production authority store.
- Reject test providers, missing providers and implicit fallback.
- Validate required schemas, active root/policy versions and provider provenance before accepting requests.
- Expose read-only diagnostics that disclose component status/version without exposing secrets.
- Refuse side effects if initialization is partial or any required provider is unhealthy.

**Current implementation status:** `DESIGN_ONLY / NOT_VERIFIED`. This design does not assert that a valid production composition root already exists.

## 6. Components and contracts

### 6.1 TrustRoot

**Responsibility:** identify the root of trust, bootstrap event, owner authorization, root generation, approved public verification material (if used), current root state and revocation policy.

**Bootstrap state machine:**
`UNINITIALIZED -> BOOTSTRAP_PENDING -> ACTIVE`; failures lead to `BLOCKED`, not a guessed/default root. Root replacement follows `ACTIVE -> ROTATION_PENDING -> ACTIVE` only after independently authorized rotation, old/new root cross-reference where feasible, audit event and recovery plan. Suspected compromise leads to `QUARANTINED`.

**Required fields:**
- `schema_version`
- `root_id`
- `generation` (monotonically increasing)
- `status`
- `created_at`
- `bootstrap_authorization_ref`
- `verification_method`
- `verification_material_ref` (reference only; never private key bytes)
- `previous_root_digest` for rotation, nullable only for generation 1
- `policy_change_threshold` / approval rules
- `record_digest`
- `evidence_ref`

Bootstrap is a distinct, visible user-approved operation. It must not occur automatically at import time, on first request, or as a side effect of testing. If no approved bootstrap exists, the only allowed operations are safe diagnostics, design/read-only inspection, and the explicitly approved bootstrap ceremony itself.

### 6.2 PrincipalRegistry

**Responsibility:** map authenticated principal identifiers to status, role, allowed capabilities, resource scope and expiry/revocation metadata.

**Rules:**
- Principal IDs are stable opaque identifiers; display names are metadata, not authentication.
- A task's claimed principal is not proof of identity.
- The caller identity comes from an authenticated runtime/session boundary or a separately verified signed assertion.
- Roles are not free-form strings that automatically grant permission; policy maps explicit capabilities to exact actions/resources.
- Revocation and expiry are checked at decision time.
- Unknown, disabled, expired or revoked principal => `DENY` for side effects; unavailable identity verifier => `BLOCKED`.

### 6.3 PolicyEngine

**Responsibility:** evaluate requests against an active, versioned policy and trusted factual inputs.

**Input contract (conceptual):**
`evaluate(principal_context, action, resource, scope, task_ref, candidate_ref, policy_ref, condition_facts, gate_ref, now_ref) -> Decision`

Caller-supplied booleans such as `trusted_policy_allow`, `gate_passed` or `is_owner` are treated as untrusted data and cannot satisfy an authority predicate.

**Decision result:**
- `decision_id`
- `decision`: `ALLOW | DENY | BLOCKED`
- `reason_codes[]`
- `principal_ref`
- `action`, `resource`, `scope`
- `task_ref`, `candidate_ref`
- `policy_version`, `root_generation`
- `applicability_ref`, `gate_ref`
- `evidence_refs[]`
- `issued_at`, `expires_at`
- `request_digest`, `decision_digest`

`ALLOW` is possible only when all required facts are verified and current. A known policy denial is `DENY`; a missing/indeterminate mandatory fact is `BLOCKED`. Both block the side effect. There is no permissive default.

### 6.4 ApplicabilityEngine

**Responsibility:** independently determine whether a request changes/adds/replaces/removes/expands a capability and whether MAEP-022 is mandatory.

**Inputs:** canonical task and diff/reference; candidate/source identity; reviewed applicability-rule version; trusted repository facts; impact/dependency inventory; prior capability map and evidence references.

**Outputs:** `applicability_id`, `classification`, `rule_version`, `candidate_ref`, `facts_used[]`, `evidence_refs[]`, `confidence/status`, `reason_codes[]`, `created_at`.

Classification values: `REQUIRED`, `NOT_REQUIRED`, `UNKNOWN`. Uncertain analysis maps to `REQUIRED` for gate planning and `BLOCKED` for authorization until resolved. The engine must not accept a caller-declared `capability_affecting=false` as the classification. It derives the result from reviewed rules and source/plan evidence. Rule updates require policy-change authorization and regression tests.

### 6.5 CandidateIdentityProvider

**Responsibility:** identify exactly what code/configuration is being evaluated or executed.

Candidate identity should include, when applicable:
- canonical repository identity `OAI-GIANG/HG`;
- branch/ref and commit ID;
- source tree digest derived from a deterministic manifest;
- dirty-worktree summary and explicit changed-path set;
- dependency/runtime versions relevant to the decision;
- build/artifact digest and source-to-artifact linkage for deployed artifacts.

A branch name, local path, user assertion or commit ID alone is insufficient to prove runtime provenance. If the worktree is dirty, the candidate identity must explicitly bind the uncommitted diff; otherwise high-risk authorization is blocked. Tests against a candidate do not automatically apply to a different candidate.

### 6.6 EvidenceLedger

**Responsibility:** append authority decisions, bootstrap events, policy changes, applicability/gate results, action attempts, receipts, recovery actions and closure records to the existing approved ledger/evidence mechanism.

**Invariants:**
- Events have unique IDs, monotonic sequence within the active ledger, timestamp source metadata, schema version, actor/principal ref, event type, candidate ref, previous-event digest and canonical payload digest.
- Corrections append a superseding/amendment record; they do not silently rewrite earlier evidence.
- A hash chain can reveal a missing/changed event only relative to a trusted checkpoint or separately protected anchor. It is not independent proof if all data and checkpoint are mutable together.
- Failed writes, sequence rollback, chain mismatch, unsupported schema, or missing durable receipt blocks side effects/closure requiring evidence.
- Secrets and credential bytes are never written to the ledger. Use opaque references and redacted reason codes.

This design prefers the existing MAEP ledger/evidence path; it does not mandate a second database. Transactional requirements and exact ledger API must be mapped to the implementation before coding.

### 6.7 CapabilityGate (MAEP-022 integration)

**Responsibility:** run the existing MAEP-022 assessment under MAEP's current execution protocol, with candidate-bound and policy-bound evidence.

The gate must assess:
1. Current and proposed capability inventory, ownership, callers, dependencies and trust boundaries.
2. Decision category: `EXISTING_REUSE`, `EXTEND_EXISTING`, `CONSOLIDATE_KEEP_SUPERIOR`, `DEPRECATE_OBSOLETE`, `GENUINE_GAP`, or `UNKNOWN`.
3. Evidence-supported comparison of correctness, security, reliability, completeness, interoperability, performance/resource cost, maintenance and operational burden.
4. Impact, regression/migration tests, rollback/recovery and retirement authorization where relevant.
5. Exact candidate identity, rule version, policy version and evidence references.

Only complete `PASS` on the exact current candidate may satisfy the gate. `UNKNOWN`, missing evidence, stale result, candidate mismatch, or required test not run means `BLOCKED`/not passed. A `GENUINE_GAP` permits consideration of an implementation; it does not grant permission to perform it.

### 6.8 Runtime authorization boundary

Every side-effect adapter must call a centralized action boundary immediately before the effect. No branch may make an equivalent external mutation directly.

Conceptual API:
`authorize_effect(request) -> short_lived_effect_grant`
`execute_effect(grant, idempotency_key, operation) -> effect_receipt`
`record_outcome(receipt) -> durable_evidence_ref`

The grant is narrow and bound to:
- one principal;
- one action and resource;
- one exact scope;
- one task and candidate;
- one policy/root generation;
- required gate and evidence versions;
- one idempotency key;
- a short validity interval.

The adapter re-validates the grant and current root/policy/candidate state immediately before use. A stale or consumed grant cannot be reused. This narrows TOCTOU risk but cannot make an external non-transactional operation atomic; uncertain outcomes require reconciliation rather than blind retry.

### 6.9 RecoveryManager

**Responsibility:** safe recovery from interrupted authority/ledger writes and uncertain side effects.

States: `HEALTHY`, `DEGRADED_READ_ONLY`, `RECONCILIATION_REQUIRED`, `QUARANTINED`, `RECOVERING`, `RECOVERED_PENDING_VERIFICATION`, `BLOCKED`.

Rules:
- No automatic replay of unknown non-idempotent effects.
- Use a durable idempotency key and operation receipt where the underlying adapter supports them.
- A timeout means outcome `UNKNOWN`, not failed and not successful.
- Reconcile external state and ledger before retrying.
- Restore from a backup only after provenance/integrity checks and pre/post consistency checks.
- Recovery does not itself grant authority or weaken policy.
- Return to effect-capable state only after health and integrity are independently re-verified against the same candidate/root/policy versions.

### 6.10 BrainOrchestrator, Memory and branches

**BrainOrchestrator** orchestrates task lifecycle and is the sole coordinator. It checks authority at intake, plan authorization, dispatch, before each side effect and before acceptance/closure. The branch modules do not create their own competing approval process.

**Unified Memory** uses explicit mutation contracts. Reads may be permitted under degraded policy; writes, migrations and deletions each require their own action grants. Memory content is data, not authority. Records preserve provenance, candidate/task references and append-only change history where required.

**Functional branches** receive capability-specific adapters rather than unrestricted runtime access. A branch can request an action but cannot confer authority on itself. All calls that can modify files, external systems, deployments, policy, or durable state must cross the centralized effect boundary.

## 7. Authority and policy lifecycle

### 7.1 Bootstrap

1. Start in `UNINITIALIZED`; no mutation capability is available.
2. Present the TrustRoot bootstrap statement and requested root/policy material for owner review.
3. Require a separate explicit owner approval bound to the exact bootstrap payload digest and target repository/device.
4. Validate the approval through an out-of-band or pre-established trusted verification method. Do not accept a model response, environment variable, self-asserted username or adjacent checksum as approval.
5. Write the root record atomically where supported; fsync/close and read back; validate schema, digest, generation and references.
6. Append bootstrap evidence to the existing ledger and create a protected checkpoint/reference.
7. Enter `ACTIVE` only after read-back and evidence validation. Any failure => `BLOCKED`.

If no separately verifiable bootstrap channel is available, the system remains read-only and high-risk actions remain blocked. This is a real dependency, not something code can safely invent away.

### 7.2 Operational authorization

Operational grants are scoped, action-specific, candidate-bound and short-lived. An operational grant cannot create principals, change root material, relax policy or grant root authority.

### 7.3 Policy/root changes

1. Propose a new immutable version.
2. Produce rationale, diff, threat/risk assessment, applicability gate, test plan, migration/rollback plan and impact inventory.
3. Obtain explicit authorization from the designated policy authority under the currently active policy/root.
4. Verify approvals independently from the candidate being approved.
5. Activate atomically by advancing the active-version pointer after all checks; preserve the old version and references.
6. Revoke/expire affected grants, invalidate stale gate/evidence results and record a durable event.
7. Verify the active pointer and ledger after activation.

A policy change cannot authorize itself. If the only approving principal is introduced by the candidate policy itself, fail closed.

## 8. Conceptual data schemas

These are illustrative contracts, not yet checked-in JSON Schemas or implemented data models. All records must reject unknown fields unless a versioned extension mechanism explicitly allows them. Canonical serialization must define UTF-8, key ordering, normalized timestamps, number/string rules and rejection of duplicate keys.

### 8.1 Root record

```json
{
  "schema_version": "hg.trust-root.v1",
  "root_id": "opaque-id",
  "generation": 1,
  "status": "BOOTSTRAP_PENDING",
  "created_at": "RFC3339 timestamp",
  "bootstrap_authorization_ref": "evidence-ref",
  "verification_method": "explicit-approved-method",
  "verification_material_ref": "opaque-ref",
  "previous_root_digest": null,
  "policy_change_rule_ref": "policy-rule-ref",
  "record_digest": "sha256:...",
  "evidence_ref": "ledger-event-ref"
}
```

### 8.2 Principal record

```json
{
  "schema_version": "hg.principal.v1",
  "principal_id": "opaque-id",
  "status": "ACTIVE",
  "authn_method": "runtime-session-or-verified-assertion",
  "role_refs": ["role-ref"],
  "capability_refs": ["capability-ref"],
  "resource_scopes": ["narrow-resource-scope"],
  "not_before": "RFC3339 timestamp",
  "expires_at": "RFC3339 timestamp-or-null",
  "revocation_ref": null,
  "record_version": 1,
  "evidence_ref": "ledger-event-ref"
}
```

### 8.3 Policy record

```json
{
  "schema_version": "hg.policy.v1",
  "policy_id": "opaque-id",
  "version": 1,
  "status": "PROPOSED",
  "parent_policy_digest": "sha256:...",
  "rules_ref": "immutable-rules-ref",
  "approved_by": ["verified-principal-ref"],
  "approval_evidence_refs": ["evidence-ref"],
  "effective_at": "RFC3339 timestamp",
  "record_digest": "sha256:...",
  "change_task_ref": "task-ref"
}
```

### 8.4 Decision and gate result

```json
{
  "schema_version": "hg.authorization-decision.v1",
  "decision_id": "opaque-id",
  "decision": "BLOCKED",
  "reason_codes": ["MISSING_BOOTSTRAP_AUTHORITY"],
  "principal_ref": "verified-principal-ref-or-null",
  "action": "WRITE",
  "resource": "hg://repository/path",
  "scope": ["exact-path-or-operation"],
  "task_ref": "task-ref",
  "candidate_ref": "candidate-ref",
  "root_generation": 1,
  "policy_version": 1,
  "applicability_ref": "applicability-record-ref",
  "gate_ref": "maep-022-gate-record-ref",
  "evidence_refs": [],
  "issued_at": "RFC3339 timestamp",
  "expires_at": null,
  "request_digest": "sha256:...",
  "decision_digest": "sha256:..."
}
```

A `BLOCKED` example is deliberate: until bootstrap is approved and current, the system cannot issue effect-capable `ALLOW`.

### 8.5 Effect receipt and recovery record

Every adapter should return a structured receipt containing `effect_id`, `idempotency_key`, `decision_id`, `candidate_ref`, `started_at`, `completed_at`, `outcome` (`SUCCESS | FAILURE | UNKNOWN`), external reference, observed state digest and evidence reference. Recovery records additionally include the reason for reconciliation, observations, attempted recovery operation, approval reference where needed, and verification result. Never infer success from a missing exception or empty output.

## 9. API contracts and typed outcomes

All API outcomes are closed enums; unrecognized values fail closed.

- `IdentityProvider.resolve(context) -> VerifiedPrincipal | Denied | Blocked`
- `CandidateIdentityProvider.inspect(target) -> VerifiedCandidate | Mismatch | Blocked`
- `PolicyProvider.load_active(root_ref) -> VerifiedPolicy | Invalid | Blocked`
- `ApplicabilityEngine.classify(task_ref, candidate_ref, rules_ref) -> Required | NotRequired | Unknown`
- `GateProvider.evaluate(task_ref, candidate_ref, policy_ref) -> Pass | Fail | Blocked`
- `EvidenceLedger.append(event) -> DurableEvidenceRef | Failed`
- `PolicyEngine.evaluate(request) -> Allow | Deny | Blocked`
- `CapabilityGate.check(request) -> Pass | Fail | Blocked`
- `EffectBoundary.execute(grant, operation) -> Receipt | ReconciliationRequired`
- `RecoveryManager.inspect(operation_ref) -> SafeToContinue | ReadOnlyOnly | Blocked`

No default/mock provider is selected implicitly. Test dependency injection must be explicit and rejected when runtime profile is production. `Allow` must include the exact authority/evidence references used, not just a boolean.

## 10. Canonicalization, integrity and provenance

- Use deterministic canonical JSON or the existing MAEP canonical serializer after its contract is confirmed. Do not create a second serializer without a documented need.
- Reject duplicate JSON keys, unsupported encodings, invalid timestamps, unknown enum values and ambiguous paths.
- Use `hashlib.sha256` for content digesting; hashes are integrity identifiers, not authentication.
- MAEP-029 prohibits digital-signature/HMAC features and workflows; do not implement them. Use owner-controlled bootstrap authorization, approved record provenance and local integrity checks, and block whenever the approved source cannot be established.
- Use atomic temporary-write + flush/fsync + replace/read-back where the filesystem supports it; document Android/filesystem limitations and test crash behavior.
- Set restrictive permissions on local authority material, but do not describe file permissions as protection from a privileged attacker.
- Use monotonic sequence/generation checks to reject rollback; anchor checkpoints independently if rollback resistance is required.
- Bind every authorization, gate and test report to candidate identity and policy/root versions.
- Avoid secret content in diagnostics; report only opaque IDs, reason codes and redacted locations.

## 11. State machine and fail-closed rules

### Request decision path

```text
RECEIVED
  -> VALIDATING
  -> IDENTITY_VERIFIED
  -> CANDIDATE_VERIFIED
  -> POLICY_VERIFIED
  -> APPLICABILITY_CLASSIFIED
  -> GATE_VERIFIED (when required)
  -> AUTHORIZATION_EVALUATED
  -> GRANT_ISSUED
  -> PRE_EFFECT_RECHECK
  -> EFFECT_ATTEMPTED
  -> RECEIPT_RECORDED
  -> OUTCOME_VERIFIED
```

At any stage, a known violation transitions to `DENIED`; a missing/indeterminate mandatory fact transitions to `BLOCKED`. An effect timeout transitions to `OUTCOME_UNKNOWN -> RECONCILIATION_REQUIRED`, never straight to retry. The gate result cannot be bypassed by forcing a state value.

### Invariants

1. **I-01 No root, no side effect:** no active approved root means no high-risk effects.
2. **I-02 Verified identity:** no mutation authorization from an unverified principal.
3. **I-03 Least privilege:** each grant is restricted to one exact action/resource/scope.
4. **I-04 No self-approval:** a candidate cannot approve its own trust root or policy relaxation.
5. **I-05 Independent applicability:** callers cannot mark their own capability change as not applicable.
6. **I-06 MAEP-022 before effect:** required gate must PASS and match task/candidate/policy.
7. **I-07 Candidate binding:** evidence and tests do not transfer across candidate changes.
8. **I-08 Freshness:** expired, revoked, superseded or mismatched grants are invalid.
9. **I-09 Pre-effect enforcement:** every side-effect path passes a central boundary immediately before execution.
10. **I-10 Durable evidence:** required ledger write failure blocks effect or closure as required by policy.
11. **I-11 No blind retry:** unknown non-idempotent effects must be reconciled.
12. **I-12 Monotonic governance:** root/policy/ledger generations cannot silently roll back.
13. **I-13 Single orchestrator:** only BrainOrchestrator coordinates task execution; specialist branches remain scoped.
14. **I-14 No false closure:** CLOSED_VERIFIED requires all mandatory gates and runtime evidence.
15. **I-15 Honest degradation:** unavailable verifier/storage yields BLOCKED or policy-permitted read-only mode, never implicit ALLOW.
16. **I-16 Protected exclusions:** this design does not edit MAEP-029/030.

## 12. Threat-to-control matrix

| ID | Threat | Required control | Test evidence | Status |
|---|---|---|---|---|
| T-01 | Forged principal/display name | Authenticated context + registry verification | Fake identity denied before adapter call | DESIGN_ONLY |
| T-02 | Caller supplies ALLOW boolean | Ignore as authority; recompute decision | Caller boolean cannot change decision | DESIGN_ONLY |
| T-03 | Caller marks capability unaffected | Applicability derived independently | False declaration still triggers gate | DESIGN_ONLY |
| T-04 | Policy self-relaxation | Separate approval under active parent policy/root | Candidate policy cannot approve itself | DESIGN_ONLY |
| T-05 | Stale/replayed grant | Expiry, nonce/use state, root/policy generation binding | Replayed grant rejected | DESIGN_ONLY |
| T-06 | TOCTOU mutation | Recheck immediately before effect and bind versions | Policy/candidate change between check and use blocks | DESIGN_ONLY |
| T-07 | Duplicate retry | Idempotency record and reconciliation | Retry creates no duplicate side effect | DESIGN_ONLY |
| T-08 | Ledger tampering/rollback | Digest chain + protected checkpoint/generation | Change/rollback detected or operation blocked | DESIGN_ONLY |
| T-09 | Stale/mismatched gate | Candidate/policy/rule binding | Old PASS rejected after change | DESIGN_ONLY |
| T-10 | Missing provider | Explicit provider health/contract checks | Composition fails closed | DESIGN_ONLY |
| T-11 | Test fixture in production | Explicit profiles and provider-type guard | Fake provider rejected in production mode | DESIGN_ONLY |
| T-12 | Wrong checkout/runtime | Root/source/build identity check | Runtime identity mismatch blocks startup/effect | DESIGN_ONLY |
| T-13 | Empty output/timeout | Distinguish empty, timeout, error, success | Unknown state enters reconciliation | DESIGN_ONLY |
| T-14 | Crash during ledger write | Atomic/durable append and recovery scan | No side effect without required durable event | DESIGN_ONLY |
| T-15 | Memory write bypass | Central Memory mutation contract | Direct bypass denied in integration test | DESIGN_ONLY |
| T-16 | Branch bypasses Brain | All mutation adapters require grant | Each adapter has deny-before-effect test | DESIGN_ONLY |

## 13. Test plan and acceptance matrix

Tests should use Python standard library `unittest` unless existing HG test conventions require otherwise. Tests must be deterministic, local/offline, use temporary directories/fake adapters, and clearly mark all fixtures as test-only. They are not proof of production runtime behavior.

| Gate | Required validation | Pass criteria | Current status |
|---|---|---|---|
| A0 Baseline preservation | Record HEAD, branch, dirty paths, protected paths | No unintended change to pre-existing paths | PRE-WRITE CHECK DONE; post-write confirmation pending |
| A1 Contract/schema | Required/forbidden fields, canonical serialization, enums | Invalid/ambiguous data rejected | NOT_RUN |
| A2 Bootstrap | Missing/invalid/forged/approved bootstrap | Only independently approved bootstrap activates root | NOT_RUN |
| A3 Identity | Unknown, revoked, expired, forged principal | All invalid cases deny/block before effect | NOT_RUN |
| A4 Policy | Least privilege, action separation, scope mismatch, self-relaxation | No escalation or self-approval | NOT_RUN |
| A5 Applicability | Add/replace/remove/expand/uncertain changes | Uncertainty triggers mandatory gate/block | NOT_RUN |
| A6 Evidence | Tampering, stale, reordered, rolled-back, candidate mismatch | Invalid evidence never satisfies a gate | NOT_RUN |
| A7 Pre-effect | Revoke/change candidate after grant issuance | Central boundary rejects before adapter effect | NOT_RUN |
| A8 Timeout/recovery | Crash and ambiguous non-idempotent response | No blind replay; state reconciled | NOT_RUN |
| A9 Idempotency | Duplicate operation key and lost receipt | At most one effect where adapter semantics permit; otherwise reconcile | NOT_RUN |
| A10 Memory/branches | Direct and indirect write routes | Every effect route denied absent valid grant | NOT_RUN |
| A11 Integration | Real composition root, real local persistence, Brain + Memory + adapters | Candidate-bound tests and durable events | NOT_RUN |
| A12 Runtime provenance | Executed checkout/build matches candidate manifest | Verified source-to-runtime identity | NOT_RUN |
| A13 E2E deny | Real runtime with intentionally invalid authority | Observable zero side effects and durable denial evidence | NOT_RUN |
| A14 E2E allow | Valid approved root, current policy, valid gate and authorized low-risk test effect | Effect and receipt match exact grant and candidate | NOT_RUN |
| A15 Closure | Gate references, acceptance records and actual runtime outputs resolve | All mandatory gates PASS; no blocker | NOT_RUN |

**High-risk action classes:** deploy, deletion, merge/push, production migration, policy/root modification, credential modification and irreversible external writes. These remain blocked until bootstrap, policy authority, MAEP-022, pre-effect enforcement, durable evidence and runtime provenance gates pass.

For the first allow-path E2E, use a deliberately low-risk local test resource and a dedicated test principal; do not test by deploying, deleting user data or modifying the trust root.

## 14. Implementation phases

### Phase 0 — Preserve and map (read-only)
- Reconfirm canonical repository, branch, HEAD, dirty worktree and protected paths.
- Map existing MAEP serializer, ledger, schema validation, state guards and Memory mutation APIs.
- Do not overwrite or reformat pre-existing user changes.
- Output: current-to-target component map and gap list.

### Phase 1 — Freeze contracts (design review)
- Review this threat model, root bootstrap assumptions and data/API contracts.
- Decide exact owner-approved bootstrap mechanism and what its independent verification source is.
- Decide the existing ledger integration and atomic persistence contract.
- Acceptance: signed/explicitly approved design decision and no unresolved root-of-trust circularity.

### Phase 2 — Pure core and schemas
- Implement typed result enums, deterministic request/evidence serialization, policy predicates and applicability rules as side-effect-free functions.
- Add JSON schemas/versioned contracts using existing repository patterns.
- Unit test adversarial inputs; use no real keys/secrets and no external network.
- Acceptance: full contract tests pass against exact candidate.

### Phase 3 — Protected local providers
- Implement principal/policy/root storage adapters and candidate identity provider.
- Atomic persistence, permission checks, generation/rollback detection and recovery behavior.
- Add explicit test/production provider separation.
- Acceptance: mutation/rollback/invalid-state tests pass; bootstrap remains blocked by default.

### Phase 4 — Composition and effect boundary
- Wire one runtime composition root.
- Connect MAEP and MAEP-022 to Brain; connect Memory and all branch mutations to the central pre-effect boundary.
- Eliminate or prove unreachable any direct mutation bypass.
- Acceptance: dependency map is source-backed; all side-effect routes covered by negative tests.

### Phase 5 — Runtime E2E and provenance
- Verify actual runtime path and source/build identity.
- Test deny-before-effect with invalid authority and allow-with-current-gate using a low-risk local effect.
- Verify durable ledger receipt and recovery/replay behavior.
- Acceptance: gates A11–A14 PASS with candidate-bound evidence and no excluded runtime/repository.

### Phase 6 — Review and closure
- Conduct scoped internal critique, owner-authorization checks, bypass-route tests and evidence-provenance checks. Do not create or require an independent-review workflow.
- Re-run relevant acceptance gates if candidate/policy/configuration changes.
- Update canonical records only under MAEP and authorized patch rules.
- CLOSED_VERIFIED only when A0–A15 required evidence resolves and all mandatory criteria pass; otherwise BLOCKED/UNVERIFIED.

## 15. Risks and unresolved decisions

| Risk / decision | Why it matters | Required resolution | Default |
|---|---|---|---|
| No approved bootstrap mechanism | Trust root can become circular/self-authorized | Owner selects an explicit owner-controlled authorization process, with evidence sourced outside the candidate being authorized | BLOCK high-risk actions |
| Fully compromised local device | Local state can be modified by privileged attacker | State threat assumptions and evaluate hardware/out-of-band anchor if needed | No claim of tamper-proof root |
| Existing serializer/ledger API not mapped | Duplicate mechanisms create inconsistent evidence | Map and reuse existing MAEP mechanisms | Do not create competing mandatory ledger |
| Runtime composition root unknown | Providers may not be wired into real runtime | Identify exact startup path and source/build evidence | No runtime authorization claim |
| Branch bypasses unknown | One direct path defeats global gate | Inventory every effect adapter and call graph | Block side effects until coverage proven |
| Candidate/worktree dirty | Tests may not identify exact source candidate | Bind dirty diff/tree and test report to manifest | Block if identity incomplete |
| Clock not trustworthy | Expiry/freshness checks may be unsound | Identify time source and fail safely on uncertainty | Block expiring grants if time invalid |
| External operation lacks idempotency | Timeout may leave effect status unknown | Reconcile provider state before retry | No blind replay |
| Evidence anchor co-located | Hash chain alone may not resist total rewrite | Define a separately protected checkpoint source and owner-authorized reconciliation record | Integrity claim limited to detection scope |

## 16. Current implementation/status matrix

**Updated after the implementation-mapping and native-authority work.** Unit/integration tests use controlled fixtures. No row below implies production runtime verification.

| Component | Design | Source implementation | Tests | Runtime verification |
|---|---|---|---|---|
| TrustRootManager | DESIGN_ONLY contract implemented | IMPLEMENTED: `maep/native_authority.py::TrustRootManager` and `TrustRootRecord` | TESTED: bootstrap rejection, approved test bootstrap, read-back and tamper detection | BLOCKED: no owner-approved production bootstrap/root store |
| PrincipalRegistry | DESIGN_ONLY contract | Provider interface and status/expiry/revocation checks IMPLEMENTED | TESTED: forged and revoked identity blocked | BLOCKED: production authenticated principal provider absent |
| PolicyEngine | DESIGN_ONLY contract | IMPLEMENTED: `NativePolicyEngine` validates policy provenance fields, root generation, exact resource/scope, TTL and decision | TESTED: allow/deny, scope escalation, stale policy, evidence failure | BLOCKED: production policy store/evaluator provenance absent |
| ApplicabilityEngine | DESIGN_ONLY contract | Provider interface and independent result validation IMPLEMENTED; rule engine itself remains provider responsibility | TESTED: unknown/conflicting applicability blocked | BLOCKED: reviewed production rules/provider absent |
| CandidateIdentityProvider | DESIGN_ONLY contract | Provider interface and repository/manifest/candidate binding checks IMPLEMENTED | TESTED with candidate-bound fixtures and mismatch paths | BLOCKED: real source manifest/build provider absent |
| EvidenceLedger | Reuse existing MAEP evidence path | Evidence-sink contract consumed by native authority; production sink not supplied by this task | TESTED: missing/failed sink blocks ALLOW | BLOCKED: durable production sink/checkpoint not wired |
| CapabilityGate / MAEP-022 | DESIGN_ONLY contract | Native gate-provider contract requires PASS, verified evidence, gate ID, candidate and policy binding | TESTED: missing, blocked and stale gate results fail closed | BLOCKED: production gate evidence resolver absent |
| Runtime composition root | DESIGN_ONLY target | IMPLEMENTED: `runtime/composition.py::build_runtime`; no implicit providers/default bootstrap | TESTED: missing root blocks before Memory DB creation | BLOCKED: approved production dependencies/root absent |
| BrainOrchestrator | DESIGN_ONLY target | IMPLEMENTED: `brain/orchestrator.py::BrainOrchestrator`; registered adapters, pre-effect recheck, idempotency and receipts | TESTED: deny-before-effect, duplicate key and timeout UNKNOWN | BLOCKED: no production adapters or durable idempotency ledger |
| Memory authorization boundary | DESIGN_ONLY target | IMPLEMENTED: `memory/authority_adapter.py`; candidate-bound bridge into NativePolicyEngine; MemoryStore accepts candidate identity provider | TESTED: native authority integration initializes only a temporary test database | BLOCKED: production Memory runtime composition and approved root absent |
| RecoveryManager | DESIGN_ONLY contract | IMPLEMENTED: `maep/native_authority.py::RecoveryManager` | TESTED: UNKNOWN requires reconciliation/fresh authority | BLOCKED: no production reconciliation provider |
| Deny-before-effect | Acceptance requirement | Brain checks authority before registered adapter invocation | TESTED with fake adapter and invalid candidate | BLOCKED: real runtime path not proven |
| Allow-with-current-gate | Acceptance requirement | Native engine issues short-lived candidate/policy-bound result; Brain rechecks before dispatch | TESTED with test-only providers | BLOCKED: no approved production root/gate/runtime evidence |

Latest local test command: `python3 -m pytest maep/tests memory/tests brain/tests runtime/tests -q --disable-warnings --maxfail=1` — **166 passed, 23 subtests passed**. These are local test results for the current dirty worktree, not independent review or production evidence.

## 17. Acceptance and stop conditions

This design is acceptable for review only if:
- Bootstrap authority is explicit, owner-approved and non-circular.
- Operational authority cannot modify the trust root or authorize policy relaxation.
- Caller-supplied assertions never substitute for verified identity, policy, applicability or gate evidence.
- MAEP-022 remains inside the existing MAEP execution lifecycle and evidence path.
- Every side effect is covered by a single, centrally enforced pre-effect check.
- Evidence binds to exact candidate, task, root/policy version, rule version and action.
- Test and production providers are separated without implicit fallback.
- Offline operation, recovery, rollback limitations and threat assumptions are explicit.
- Implementation can be accepted incrementally without ever treating a partial state as authorized.

Stop and remain read-only / BLOCKED if the root is not approved, principal identity is unknown, policy source is untrusted, applicability is unresolved, gate/evidence is stale, candidate is mismatched, durable evidence cannot be recorded, an adapter bypass exists, or recovery cannot establish a prior side-effect outcome.

## 18. Implementation and verification evidence

Implementation paths added during the controlled mapping/implementation work:
- `maep/native_authority.py`
- `maep/schemas/native-authority-v1.schema.json`
- `maep/tests/test_native_authority.py`
- `brain/orchestrator.py`, `brain/__init__.py`, `brain/tests/test_orchestrator.py`
- `memory/authority_adapter.py`, `memory/tests/test_authority_adapter.py`
- `runtime/composition.py`, `runtime/__init__.py`, `runtime/tests/test_composition.py`
- Existing `memory/store.py` received a candidate-reference provider seam; `memory/tests/test_store.py` had a test helper renamed so pytest does not collect a fixture function as a test.

The full local test suite passed: **170 passed, 25 subtests passed** (compileall, JSON schema parse and `git diff --check` also passed in the final verification run). Brain re-runs the complete authorization chain immediately before dispatch, re-evaluating current identity/revocation, candidate, policy, applicability and MAEP-022 gate. Memory repeats native authorization at its pre-effect seam before its database operation proceeds. Explicit matching DENY policy rules override overlapping ALLOW rules. These controls are covered by local tests only. This evidence is bound to the current local dirty worktree and has not been independently reviewed. No production TrustRoot, authenticated principal provider, policy provider, applicability rules provider, durable evidence sink, durable idempotency ledger, branch adapter inventory, or runtime source/build provenance was verified. The composition root correctly blocks when no active verified root is supplied.

**Final status is not CLOSED_VERIFIED.** Runtime and high-risk effects remain BLOCKED until the owner-approved bootstrap ceremony and production providers are supplied, then real runtime deny-before-effect and allow-with-current-gate evidence is collected. No commit, push, merge, deployment, service restart, data deletion, or MAEP-029/030 edit was performed.



## Current MAEP conformance and verification addendum — 2026-10-22

- The current policy is MAEP-1.2.0. This addendum supersedes earlier design suggestions in this document that conflict with MAEP-029/030. No digital-signature/HMAC feature or workflow may be implemented, requested, used, or verified; no independent-review workflow may be requested or required. Owner-controlled authorization, internally executed tests/critique, approved-source provenance checks and evidence-based verification remain the allowed controls.
- The current local contract is `OwnerApprovalVerifier.validate_owner_approval` and `ApprovedRecordProvenanceVerifier.validate_record_provenance`. Implementations are required to use allowed owner-approved sources and fail closed; test fixtures are not production trust.
- Latest complete local test run after the source refactor: 200 passed, 52 subtests passed, 1 warning across MAEP, Memory, Brain, Runtime, Creativity & Research and Tools & Automation. This is local unit/regression evidence only.
- Production trust-root/bootstrap, production identity/policy providers, approved provenance resolver, deployed-source identity and end-to-end allow/deny-before-effect remain BLOCKED/NOT VERIFIED. Do not treat the local composition root as production-ready.
- Acceptance remains BLOCKED until current candidate-bound gate/evidence and real runtime provenance are resolved. No commit, push, merge, deployment or independent review was performed or requested.
