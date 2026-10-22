# Architecture Acceptance Checklist V1

Status: **DESIGN GATE — NOT YET ACCEPTED**

Use three values for each item: PASS (with evidence ref), FAIL (with evidence ref), or NOT_RUN/BLOCKED (with reason and reopening condition). A checked box without evidence is not a PASS.

## A. Design completeness
- [ ] HG Architecture V1 documents goals, invariants, five branches, dependency rules and lifecycle.
- [ ] BrainOrchestrator contract defines inputs, outputs, failures, deadlines and idempotency behavior.
- [ ] Each branch has one owner, explicit non-responsibilities and versioned interfaces.
- [ ] Data flow and trust boundaries cover user/external content, authorization, tools, evidence, memory and recovery.
- [ ] MAEP integration maps existing primitives to proposed call sites without claiming runtime integration.
- [ ] ADRs state context, decision, alternatives, consequences and status.
- [ ] Traceability maps all MAEP-001..MAEP-028 to owners and required tests.
- [ ] No contradiction exists between architecture, contracts, ADRs, MAEP rules and acceptance criteria.

## B. Dependency and architecture economy
- [ ] Repository inventory confirms no existing runtime or module was overlooked.
- [ ] Capability ownership has no unexplained duplication.
- [ ] Import/dependency graph is acyclic.
- [ ] No branch privately imports another branch's implementation.
- [ ] No second task coordinator or policy authority exists.
- [ ] Every proposed new module has a documented need and owner.

## C. Security and governance
- [ ] Every controlled side effect has action-specific authorization checked immediately before execution.
- [ ] Tool adapters independently enforce scope and reject stale/mismatched authorization.
- [ ] Unknown/missing policy or authority fails closed.
- [ ] Read-only tasks cannot mutate baseline/worktree or trigger side effects.
- [ ] External content cannot grant authority or alter policy.
- [ ] Candidate/policy changes invalidate affected evidence until reassessed.
- [ ] Secrets are not passed in plans, envelopes or ordinary logs.
- [ ] Destructive actions require a recovery plan or explicitly authorized irreversibility.

## D. State, evidence and recovery
- [ ] All task-state changes use the MAEP transition guard.
- [ ] Every evidence record binds candidate, scope, source, collector, method, result, time and limitations.
- [ ] Every mandatory acceptance criterion links to evidence.
- [ ] NOT_RUN, FAIL, UNKNOWN and BLOCKED cannot be reported as PASS.
- [ ] Terminal states cannot be silently reopened.
- [ ] Retry policy enforces the meaningful-failure limit and earlier safety stop.
- [ ] Unknown non-idempotent outcomes are reconciled against live state before retry.
- [ ] Restart recovery reconciles outstanding operations before new side effects.
- [ ] Ledger write/corruption failure behavior is tested and limitations are accurately stated.

## E. Documentation and repository integrity
- [ ] All required documents are present and Markdown/link checks pass.
- [ ] Every ADR is consistent with the final architecture.
- [ ] Rule-to-architecture matrix includes every rule MAEP-001..MAEP-028 exactly once or explains intentional multi-mapping.
- [ ] Existing dirty worktree, if any, is preserved and not overwritten.
- [ ] Main branch SHA remains unchanged.
- [ ] MAEP baseline commit remains reachable and unchanged.
- [ ] Diff contains documentation only; no runtime, deployment or generated binary changes.
- [ ] Commit/push evidence records branch and exact resulting SHA.

## F. Implementation gate (must be separate)
- [ ] Design gate explicitly accepted by the authorized user.
- [ ] Implementation scope, module inventory, migration plan and stop conditions approved.
- [ ] Unit and integration test plan covers all MAEP rules and failure modes.
- [ ] Runtime integration and end-to-end tests are not marked PASS until actually executed.
- [ ] No merge or deploy occurs without a separate explicit authorization.

## Current evidence status

At authoring time, the repository has MAEP Foundation V1 but no `docs/architecture/` tree. This checklist is newly authored design material. It does not assert that any runtime or integration test has run. Current acceptance is therefore NOT_RUN pending document validation and user review.
