# MAEP Execution Protocol V1
1. Intake: validate task envelope and canonical input references.
2. Assess: classify read-only/side-effecting actions, scope, trust boundary, risk and dependencies. Perform the MAEP-022 Capability Overlap & Superiority Gate only when the assessed change adds, replaces, expands, duplicates, consolidates, deprecates or removes an HG capability; ordinary authorization and Memory data-plane operations do not trigger this gate unless their assessed effect changes HG capability.
3. Plan: define ordered actions, acceptance, evidence, stop conditions and recovery; include the gate decision and any consolidation/deprecation steps in the existing change plan.
4. Authorize: evaluate principal/action/resource/scope/conditions against current policy. For a capability-changing action, also deny authorization unless the MAEP-022 gate is PASS, candidate-bound and evidence-complete. Do not make MAEP-022 a blanket prerequisite inside the generic authorization primitive.
5. Execute: re-check authorization before each side effect; record action identity/outcome.
6. Verify: compare observed results with criteria using candidate-bound evidence.
7. Accept: all mandatory criteria and gates must PASS.
8. Close: record final state, limitations, gate/evidence references and timestamp.

## Capability Overlap & Superiority Gate — mandatory under MAEP-022

**Trigger:** any task that adds, replaces, duplicates, expands, migrates, consolidates, deprecates or removes a capability, module, tool, workflow, policy control or user-visible function. If applicability cannot be determined, treat the gate as required.

**Use existing records only:** record the decision in the task's existing change plan and existing evidence/ledger mechanism. Do not create a new governance module, competing coordinator, standalone database or new mandatory service for this gate.

**Required assessment sequence:**
1. Inventory relevant current and proposed capabilities, owners, callers, trust boundaries, dependencies, feature coverage and existing tests. Link source-backed evidence to the exact candidate and policy version.
2. Classify overlap and decision: `EXISTING_REUSE`, `EXTEND_EXISTING`, `CONSOLIDATE_KEEP_SUPERIOR`, `DEPRECATE_OBSOLETE`, `GENUINE_GAP`, or `UNKNOWN`.
3. If there is overlap, compare candidates using evidence for correctness, security, reliability, functional completeness, interoperability/compatibility, performance/resource cost, maintainability and operational burden. Record trade-offs and limitations. A claimed advantage without evidence does not establish superiority. Prefer a demonstrated superior safe implementation; where dimensions conflict and no defensible winner exists, preserve current safe behavior and block the change pending evidence.
4. Record the selected owner/implementation, rationale, inventory and comparison evidence references, dependency/impact analysis, regression and migration tests, rollback/recovery plan, and any deprecation/removal authorization reference.
5. `DEPRECATE_OBSOLETE` or retirement under `CONSOLIDATE_KEEP_SUPERIOR` requires explicit scoped authorization, compatibility/deprecation handling where needed, a recovery path, and passing regression evidence before destructive removal. Do not erase historical evidence or user data. MAEP-027 also applies.

**Decision acceptance:** only a completed, candidate-bound gate with `gate_status=PASS` may satisfy MAEP-022. `UNKNOWN`, incomplete inventory, missing owner/boundary, missing/mismatched/stale evidence, untested claims of superiority, unresolved material trade-offs, missing impact/tests, unauthorized retirement, or `FAIL`/`BLOCKED`/`NOT_RUN` MUST fail closed. A `GENUINE_GAP` is permission to evaluate a proposal, not automatic authorization to implement it. Re-run the gate after candidate, configuration, policy, dependency or material evidence changes, and invalidate affected results per MAEP-012.

**Authorization and closure:** when the assessed action changes an HG capability, authorization MUST check the MAEP-022 gate before any side effect; a skipped applicable gate denies authorization. The generic authorization primitive continues to enforce MAEP-003/004/005 for all actions and does not itself require MAEP-022 evidence for unrelated actions. Verification MUST confirm the built change matches the selected decision and that the retired capability is not still relied on. Acceptance/`CLOSED_VERIFIED` requires the decision and all required evidence/test references to resolve and pass. If the gate is not applicable, record a reason in the existing task record and establish that no capability is being changed; uncertainty means the gate applies.

## Continuous evolution — MAEP-031

During assessment and verification, actively identify worthwhile improvements and regressions against the current baseline. Record actionable opportunities in the existing plan/ledger, prioritize evidenced improvements by benefit, safety, reliability and cost, and use MAEP authorization, regression tests and acceptance gates. Initiative and creativity must stay within authorized scope; do not invent work, expand scope silently or describe a proposal as implemented. If blocked, record the missing evidence/prerequisite and next action.

Lifecycle: DRAFT -> READY -> ASSESSED -> PLANNED -> AUTHORIZED -> RUNNING -> VERIFYING -> ACCEPTED -> CLOSED_VERIFIED. Alternative outcomes: BLOCKED, FAILED, CANCELLED, UNVERIFIED. Only transitions in STATE_TRANSITION_TABLE_V1.md are allowed.

Drafts may be incomplete but cannot execute. A blocker is not success or failure: record knowns, unknowns, missing prerequisite, next action and reopen condition. After three meaningful failed attempts on the same approach, stop it; do not repeat identical calls merely to increment count. Stop earlier for safety, irreversible risk or no progress.

Stop if authority is missing, target/candidate is uncertain, required evidence cannot be preserved, recovery is unsafe or scope is exceeded. Inspect live state before resuming. Never blindly replay an uncertain non-idempotent action.
