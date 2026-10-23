# BrainOrchestrator Contract V1

- Status: **PROPOSED CONTRACT — NOT IMPLEMENTED**
- Contract version: BO-CONTRACT-1.0
- MAEP baseline: MAEP-1.0.0

## 1. Authority

BrainOrchestrator is the sole task coordinator. It owns task identity, plan lifecycle, branch dispatch, aggregate state, recovery coordination and the request to close. It does not own policy authority, grant itself permissions, bypass branch contracts or treat unverified results as facts.

## 2. Proposed API surface

These are logical interfaces, not existing Python functions or HTTP endpoints.

| Operation | Input | Output | Failure behavior |
|---|---|---|---|
| `submit_task(request)` | User intent, scope, inputs, output contract | Task reference or validation errors | Reject malformed/incomplete intake |
| `plan_task(task_ref)` | Valid task and constraints | Versioned plan with steps/gates | Remain PLANNED or BLOCKED if incomplete |
| `authorize_action(context)` | Principal, action, resource, scope, conditions, task, policy version | MAEP decision reference | Fail closed on missing/unknown decision |
| `dispatch(task_ref, branch, envelope)` | Authorized step and minimal envelope | Dispatch reference | Do not dispatch without valid authorization when required |
| `record_result(task_ref, result)` | Branch result and evidence refs | Recorded result reference | Reject identity mismatch; preserve uncertainty |
| `request_recovery(task_ref, failure)` | Failure, observed state, idempotency facts | Recovery plan/hold | No blind replay of uncertain non-idempotent action |
| `request_cancellation(task_ref, reason)` | Task reference and cancellation reason | Cancellation request reference and current reconciliation state | Cancellation is not rollback; keep task nonterminal while in-flight effects remain unresolved |
| `evaluate_acceptance(task_ref)` | Candidate, mandatory criteria and evidence map | PASS/BLOCKED result with reasons | Missing evidence is not PASS |
| `close_task(task_ref)` | Accepted task and closure evidence | CLOSED_VERIFIED or blocker | Never close with a failed mandatory gate |
| `get_task_state(task_ref)` | Task reference | Read-only state snapshot | No side effects |

## 3. Dispatch envelope

Required logical fields:
- `contract_version`, `task_id`, `correlation_id`, `step_id`
- `branch_id`, `operation_id`, `input_refs`
- `authorization_ref` when action is controlled
- `policy_version`, `deadline`, `idempotency_key` where applicable
- `requested_effect` (READ_ONLY or a typed effect)
- `required_evidence`, `candidate_ref`, `scope_ref`

Do not pass ambient credentials, unrestricted filesystem roots, raw policy mutation capabilities or unbounded tool handles in an envelope. References should be scoped and resolved by the owning adapter.

## 4. Branch result contract

Required fields: contract version; task/correlation/step IDs; status (SUCCEEDED, FAILED, BLOCKED or UNKNOWN); output/data references; evidence references; observed effects; limitations; and structured error details where applicable.

A timeout after dispatch is UNKNOWN until reconciled. A tool claiming SUCCEEDED is not by itself acceptance evidence. Security & Verification and the MAEP acceptance gate evaluate whether the evidence supports the claim.

## 5. State, deadlines, concurrency and idempotency

All transitions pass through the MAEP transition guard. Every side effect is preceded by an action-specific authorization re-check. A terminal task continues only via a linked task or amendment.

Normative timing semantics:
- Every dispatch has an absolute deadline with a documented clock basis. The coordinator rejects a dispatch whose deadline has already elapsed; the adapter re-checks the deadline immediately before starting a side effect.
- A deadline limits waiting/starting work; it does not prove that an already-started side effect was cancelled or rolled back. If the outcome cannot be observed conclusively, record UNKNOWN and reconcile live state before retry.
- Cancellation is a request to stop work, not proof of rollback. Report cancellation separately from observed side effects and reconcile any in-flight action.
- Authorization expiry and task deadline are separate checks. A valid task deadline never extends an expired authorization decision.

Normative idempotency semantics:
- For a side effect that supports idempotency, create a key for one logical operation and persist its association with task, step, action, target/resource and payload identity before dispatch.
- Reuse a key only when retrying the same logical operation with the same action, target and payload identity. A mismatch is rejected and requires a new authorized operation.
- Where the target cannot guarantee idempotency, the adapter/coordinator must reconcile the observed state before replaying an uncertain operation; never infer safe replay from a timeout alone.
- State changes must be serialized or protected by a version/compare-and-set check so concurrent results cannot silently overwrite a newer task state. A conflict is surfaced for reconciliation, not silently retried.

Retry decisions consider attempt history, the MAEP meaningful-failure limit, safety/no-progress stop conditions, deadline, authorization validity, observed state and idempotency facts. These are contract requirements for future implementation; they are not claims that runtime enforcement currently exists.

## 6. Security and trust

User input, retrieved documents, web pages, model output, branch results and tool output are untrusted data unless validated for the specific use. None of them can grant authority or modify policy. Enforce scope at both coordinator and action-adapter boundaries.

## 7. Observability

Every dispatch and result must be traceable using task, correlation and step IDs. Evidence records must bind source, candidate, collector, method, result, time and limitations as required by MAEP. Logs must avoid secrets and must preserve failure history.

## 8. Compatibility and evolution

Version contracts explicitly. A breaking change requires a new contract version, compatibility decision, rule-impact analysis, tests and a documented migration. MAEP-028 applies. No runtime implementation is included in this contract.
