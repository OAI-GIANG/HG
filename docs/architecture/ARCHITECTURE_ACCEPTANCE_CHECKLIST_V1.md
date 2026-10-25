# Architecture Acceptance Checklist V1

Status: **DESIGN GATE — NOT YET ACCEPTED**

Use three values for each item: PASS (with evidence ref), FAIL (with evidence ref), or NOT_RUN/BLOCKED (with reason and reopening condition). A checked box without evidence is not a PASS.

## Gate separation

- **Design acceptance** evaluates whether the proposed architecture and contracts are coherent, complete, traceable to MAEP-001..MAEP-028, explicit about trust/failure semantics, and free of known contradictions. It may use source inventory and static design review as evidence.
- **Implementation acceptance** evaluates actual module/import graphs, runtime authorization enforcement, state/evidence persistence, recovery, and executable unit/integration tests. These items cannot be marked PASS merely because the design describes them.
- Where a runtime-only item has no implementation to inspect, record `NOT_APPLICABLE_PENDING_IMPLEMENTATION` for the design review and carry it forward as a mandatory implementation gate. Do not treat it as proof that the runtime passes.
- Design acceptance and implementation acceptance are separate decisions. A design acceptance does not authorize implementation, merge, or deployment.

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
- [ ] The MAEP-022 Capability Overlap & Superiority Gate is recorded in the existing task/change plan and passes before authorization; UNKNOWN/incomplete inventory/unresolved evidence blocks the change.
- [ ] Overlapping capabilities are compared on evidence across correctness, security, reliability, functional coverage, compatibility/interoperability, performance/resource cost, and maintainability; the superior safe implementation is retained and obsolete duplicates are retired only with explicit authorization, tests, migration and recovery evidence.
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

## Current evidence status (final design-gate review)

The design branch contains 17 architecture Markdown files: seven primary documents and ADR-001 through ADR-010. The MAEP constitution and architecture traceability matrix both enumerate MAEP-001..MAEP-028; the architecture matrix contains each ID exactly once, with no missing or extra rule IDs. Repository identity, branch/HEAD, remote branch SHA, unchanged `main`, MAEP baseline ancestry, clean initial worktree, and documentation-only scope were checked during the review.

The initial static review identified underspecified deadline/idempotency semantics in the BrainOrchestrator contract and ambiguity between design acceptance and implementation acceptance. The contract and this gate-separation section were amended in the review changeset. The accompanying `ARCHITECTURE_FINAL_DESIGN_GATE_REVIEW_V1.md` records the review scope, checks, findings, evidence and remaining limitations.

This checklist does not assert that BrainOrchestrator or any functional branch exists at runtime, nor that end-to-end authorization, persistence, restart recovery, or integration tests have passed. Those remain mandatory implementation gates. Final design acceptance is determined by the accompanying review report; user authorization is still required before implementation begins.
