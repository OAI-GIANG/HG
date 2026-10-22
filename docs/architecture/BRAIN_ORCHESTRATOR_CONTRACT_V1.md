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

## 5. State and idempotency

All transitions pass through the MAEP transition guard. Every side effect is preceded by an action-specific authorization re-check. Retry decisions consider attempt history, safety stop, progress and idempotency. A terminal task continues only via a linked task or amendment.

## 6. Security and trust

User input, retrieved documents, web pages, model output, branch results and tool output are untrusted data unless validated for the specific use. None of them can grant authority or modify policy. Enforce scope at both coordinator and action-adapter boundaries.

## 7. Observability

Every dispatch and result must be traceable using task, correlation and step IDs. Evidence records must bind source, candidate, collector, method, result, time and limitations as required by MAEP. Logs must avoid secrets and must preserve failure history.

## 8. Compatibility and evolution

Version contracts explicitly. A breaking change requires a new contract version, compatibility decision, rule-impact analysis, tests and a documented migration. MAEP-028 applies. No runtime implementation is included in this contract.
