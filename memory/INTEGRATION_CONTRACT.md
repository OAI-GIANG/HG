# Memory & Knowledge — runtime integration contract

- Status: REQUIRED CONTRACT FOR FUTURE BINDING; NOT IMPLEMENTED in this repository.
- Governing policy observed in the current worktree: MAEP-1.2.0.
- Coordinator: BrainOrchestrator only.
- Memory data owner: memory.MemoryStore; it never executes tools or self-authorizes.

## Required dependency injection

The caller must provide real runtime-owned adapters. The test fixture in memory/tests/test_store.py is forbidden for production use.

1. principal_provider() returns a principal ID derived from the actual runtime/session identity source; never accept an identity merely copied from user input, memory content, or a branch result.
2. policy_evaluator(request) evaluates the full current MAEP policy and returns a trusted authorization grant scoped to principal, action, resource, scope, task, policy version, validity interval and conditions. The evaluator must resolve MAEP-022 evidence whenever a capability-affecting change is requested. A data-plane non-applicability declaration does not authorize an architectural/code change.
3. live_state_provider(task_id) reads authoritative repository/runtime/policy/resource state named by the checkpoint. An unimplemented, unavailable, malformed or ambiguous observer makes resume UNKNOWN/BLOCKED.
4. acceptance_provider(task_id, target) resolves mandatory task criteria to candidate-bound MAEP gates and evidence from the authoritative verification subsystem. Missing evidence, model assertions, or planned tests cannot be converted into PASS.

## BrainOrchestrator contract

BrainOrchestrator must:
- create and own task identity and plan;
- call Memory APIs through a scoped integration boundary;
- treat retrieved knowledge as data with provenance and verification status;
- call assess_resume(task_id) before continuing a resumed task;
- proceed only when the result is CURRENT and can_resume=true, then perform fresh MAEP authorization and Tools-side authorization immediately before each side effect;
- treat STALE, CONFLICTING, UNKNOWN, PARTIAL and BLOCKED as non-resumable; reconcile or create a linked continuation under MAEP-026;
- use expected row_version for state updates and resolve conflicts through reloading/reconciliation, not blind retry;
- pass the same task/candidate/policy identities through dispatch, results, evidence, acceptance and closure;
- never bypass MAEP or delegate task coordination to Memory.

## Side-effect and transaction ordering

For each Memory mutation:
1. Validate input and schema using MAEP/Memory validators.
2. Resolve current authenticated principal and exact action/resource/scope.
3. Evaluate the trusted MAEP decision; unknown or malformed decisions block.
4. Begin a SQLite transaction and inspect canonical state/version.
5. Re-evaluate the relevant write authorization immediately before its first persistent mutation (MAEP-003).
6. Apply the MAEP state transition or data invariant and append the corresponding event in the same transaction.
7. Commit or roll back as one unit. Do not automatically delete partial artifacts when doing so would erase failure provenance.
8. Report the operation result and limitations without claiming that an external action ran merely because state was persisted.

The Tools adapter remains a separate trust boundary and must re-check its action-specific grant just before external execution. Memory's AUTHORIZED and RUNNING labels are task-state records, not proof that an external side effect executed.

## Acceptance and current blocker

This repository currently contains the Memory adapter and a contract, but no executable BrainOrchestrator/runtime component to wire these providers. Therefore actual end-to-end runtime binding, cross-session restart, live repo/runtime inspection, production authorization, external side-effect ordering and full-system anti-forgetting are NOT VERIFIED. Do not instantiate the test fake as a production fallback.
