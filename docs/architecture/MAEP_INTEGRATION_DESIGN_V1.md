# MAEP Integration Design V1

Status: **DESIGN — RUNTIME INTEGRATION NOT IMPLEMENTED**

Baseline: MAEP-1.0.0, commit `c13b758d3160899582e62248abfd7ac2b13bb161`.

## 1. Existing foundation confirmed in source

At the baseline commit, the repository contains:
- `maep/core.py`: task, evidence, authorization, transition, gate, closure, execution-mode, report-status, retry, policy-change, review-label, blocker, candidate-change, architecture-economy, amendment, change-plan, recovery, untrusted-content, research-record and claim-validation primitives.
- `maep/ledger.py`: JSONL event reader and append function; single-writer assumptions apply and privileged filesystem edits are not prevented.
- Six Draft 2020-12 JSON Schema files for task, authorization, state transition, evidence, acceptance gate and closure.
- A constitution registering MAEP-001 through MAEP-028.
- Unit tests under `maep/tests/`.
- Existing rule traceability states MAEP-006 still needs a BrainOrchestrator integration test; unit tests for MAEP-020 through MAEP-023 do not prove runtime integration.

These are source-inventory observations, not proof of an integrated HG runtime.

## 2. Proposed integration seams

| Seam | Existing foundation | Proposed runtime caller | Required contract |
|---|---|---|---|
| Task intake | `validate_task` | BrainOrchestrator intake | Schema + policy version + stop/acceptance fields |
| Action authorization | `authorize_action` | Coordinator and tool adapter | Exact principal/action/resource/scope/task/policy |
| State transition | `transition` | Single task-state repository/service | All state mutation passes guard |
| Evidence | `validate_evidence`, candidate change assessment | Result/evidence recorder | Candidate/scope binding and limitations |
| Acceptance/closure | `evaluate_gate`, `validate_closure` | Acceptance service | Mandatory gates plus linked evidence |
| Execution mode | `enforce_execution_mode` | Every action adapter | Read-only and side-effect restrictions |
| Result claims | `validate_report_status`, `validate_claim` | Reporter and result aggregator | Claim type and observed status remain distinct |
| Retry/recovery | `retry_decision`, `recovery_decision` | Recovery coordinator | Attempts, safety stop, live-state reconciliation |
| Policy evolution | `validate_policy_change` | Versioned policy-change path | No self-approval; superseded version recorded |
| Audit history | `append_event`, `read_events` | Evidence/event recorder | Single writer, corruption handling, event IDs |

## 3. Authorization protocol

1. Coordinator constructs an action request from the plan and exact execution target.
2. MAEP validates the grant, trusted policy allow, principal, action, resource, scope, conditions, task, policy version and expiry.
3. Coordinator passes only the decision reference and bounded envelope to the adapter.
4. Adapter re-checks immediately before the side effect; a stale, missing or mismatched decision denies execution.
5. Adapter returns actual outcome and effects. Timeout is UNKNOWN, not success or failure by assumption.
6. Result and evidence are recorded; verification and acceptance remain separate from execution.

No branch may use an authorization decision for a different action or task. Authorization must not be cached as a blanket permission.

## 4. Evidence and closure protocol

Evidence references bind source, candidate, collector, method, result, time and limitations. Candidate/policy changes trigger impact assessment; affected evidence is invalid until rechecked. Every mandatory criterion must be PASS and point to appropriate evidence before closure. A missing evidence item, failed gate or unknown action outcome blocks closure.

## 5. Failure behavior

- MAEP or policy unavailable: block controlled side effects.
- Invalid/missing authorization: deny.
- Ledger append failure when audit capture is mandatory: hold/fail closed; never report success unsupported by evidence.
- Corrupt ledger: reject unsafe continuation until explicitly reconciled.
- Timeout after possible side effect: UNKNOWN; reconcile live state before retry.
- Test or verification not run: NOT_RUN, never PASS.
- Policy version changes: assess affected decisions, plans and evidence before continuation.

## 6. Runtime integration acceptance

Integration is not accepted until there are executable tests showing:
- coordinator is the sole task dispatcher;
- every controlled side effect is denied without matching authorization;
- tool adapter independently enforces scope;
- all state mutations pass the transition guard;
- task/result/evidence/candidate IDs remain bound end-to-end;
- failed/missing gates prevent closure;
- read-only mode blocks writes;
- uncertain non-idempotent outcomes are reconciled before retry;
- restart recovery resumes only after reconciling outstanding operations;
- failures are retained and reported accurately.

No runtime files are added by this design document.
