# Data Flow & Trust Boundary V1

Status: **DESIGN — NOT IMPLEMENTED**

## 1. Normal flow

1. Intake: validate request shape and preserve the user's declared scope.
2. Plan: BrainOrchestrator asks HG Brain for candidate reasoning and assembles a versioned plan.
3. Context: Memory & Knowledge returns references with provenance and quality/limitation metadata.
4. Research: Creativity & Research returns source-backed findings, disagreement and uncertainty.
5. Gate: MAEP validates the task, policy version and action-specific authority.
6. Dispatch: BrainOrchestrator sends the minimal scoped envelope to one branch.
7. Execute: Tools & Automation checks the authorization again at the action boundary and executes only the permitted operation.
8. Record: capture actual result/effects and evidence references; preserve errors.
9. Verify: Security & Verification evaluates the result against the declared test/evidence contract.
10. Accept: MAEP acceptance gate evaluates mandatory criteria and candidate binding.
11. Close: closure guard permits CLOSED_VERIFIED only when all required gates pass with evidence.

## 2. Trust boundaries

| Boundary | Data crossing it | Threat | Required control |
|---|---|---|---|
| User/external content → Brain | Requests, documents, retrieved text | Prompt injection, scope confusion | Treat as data; explicit policy/authority source only |
| Brain → MAEP | Task and action request | Self-granted permission | MAEP evaluates exact principal/action/resource/scope/task/policy |
| MAEP → Tools | Decision reference and scoped envelope | Confused deputy, stale grant | Re-check immediately before side effect; adapter scope enforcement |
| Branch → Memory | Proposed knowledge/write | Poisoning, false provenance | Authorized writes, source metadata, versioning and validation |
| Tools → Evidence | Output, logs, effect summary | Fabricated or incomplete result | Collector/method/time/candidate/scope and limitations |
| Evidence → Verification | Candidate and evidence references | Candidate mismatch, stale evidence | Exact candidate/scope binding and change-impact invalidation |
| Recovery → Tools | Retry/reconcile request | Duplicate side effect | Inspect live state, idempotency guard, stop condition |
| Runtime → Ledger | Event/evidence append | Corruption, failed write, privileged tampering | Fail closed where required; detect malformed history; do not claim tamper-proof storage |

## 3. Data classes

- **Control data:** task state, authorization decisions, policy version, gate status. Only owning control interfaces can mutate it.
- **Content data:** user text, research content, memory items, tool output. It cannot create authority.
- **Evidence data:** observations and test records tied to candidate/scope. It supports a claim only within its recorded limits.
- **Secrets:** credentials and tokens. Never embed them in plans, envelopes, reports or ordinary logs; adapters resolve them from approved secret facilities.
- **Policy data:** versioned MAEP rules. Runtime agents cannot self-relax policy or approve their own candidate.

## 4. Failure semantics

- MAEP unavailable, malformed decision, or scope mismatch: BLOCK.
- Evidence capture failure when required for a controlled operation: do not report PASS; stop or hold according to recovery policy.
- Timeout after action submission: UNKNOWN until live-state reconciliation.
- Candidate or policy version changes: assess impact and invalidate affected evidence until rechecked.
- Ledger corruption: fail closed for operations requiring trustworthy event history.
- Coordinator restart: restore task/checkpoint and reconcile dispatched operations before resuming side effects.

## 5. Data minimization

Pass references rather than large unrestricted objects where practical. Give each branch only the minimum data needed. Redact secrets and unrelated personal data from evidence. Retention, deletion and encryption requirements must be specified before production persistence is implemented.

## 6. Limitations

This is a logical flow design. It does not prove runtime enforcement, storage durability, cryptographic integrity, isolation or recovery behavior. Those require implementation and integration tests.
