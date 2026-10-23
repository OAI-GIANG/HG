# HG Architecture V1

- Status: **DESIGN PROPOSAL — NOT IMPLEMENTED**
- Product: HG
- Governance baseline: MAEP-1.0.0 at `c13b758d3160899582e62248abfd7ac2b13bb161`
- Architecture version: HG-ARCH-1.0
- Scope: clean-room architecture only; no runtime contract is claimed to exist.

## 1. Purpose and invariants

HG is organized around one logical coordinator, `BrainOrchestrator`, and five functional branches: HG Brain; Memory & Knowledge; Creativity & Research; Tools & Automation; Security & Verification. MAEP is a cross-cutting governance layer, not a sixth branch.

Normative invariants:

1. BrainOrchestrator is the sole owner of task lifecycle and inter-branch dispatch.
2. Each capability has one authoritative owner; branches do not duplicate orchestration or policy authority.
3. MAEP policy and authorization checks precede every controlled side effect. Enforcement must also exist at the tool adapter boundary.
4. Missing, malformed, stale, mismatched or unavailable authorization fails closed.
5. Branches exchange versioned contracts and references, not private implementation objects.
6. Claims, execution results and verification status are distinct. A proposal or inference is not a verified fact.
7. A task cannot reach CLOSED_VERIFIED unless all mandatory acceptance gates pass with evidence bound to the exact candidate and scope.
8. Unknown side-effect outcomes are reconciled against live state before retry; non-idempotent actions are never blindly replayed.
9. The core should be offline-first and use Python standard library unless a documented ADR proves a dependency is necessary.
10. No new module or service is introduced without a distinct responsibility, trust boundary, lifecycle or measurable operational benefit.

## 2. Logical architecture

- **BrainOrchestrator:** intake, task identity, planning, dispatch, state coordination, recovery orchestration, result aggregation and closure request.
- **HG Brain:** reasoning, decomposition, candidate plans and trade-off analysis. It does not own dispatch or authorization.
- **Memory & Knowledge:** retrieval, persistence, provenance, versioning and trust/quality metadata for stored knowledge.
- **Creativity & Research:** research plans, source collection, synthesis, hypothesis generation and limitation/disagreement reporting.
- **Tools & Automation:** bounded adapters for file, process, network or other tools. Each adapter enforces the action scope it receives.
- **Security & Verification:** threat analysis, result checking, test/evidence validation and discrepancy reporting. It reports findings; it does not grant authority.
- **MAEP:** policy rules, authorization evaluation, state-transition guards, evidence contracts, acceptance/closure gates, retry/recovery controls and policy-change governance.

## 3. Dependency rules

Allowed logical dependencies:
- BrainOrchestrator may call MAEP contracts and branch interfaces.
- A branch may use shared pure-value types and its own internal modules.
- Tools & Automation may call a MAEP enforcement interface at the point of action.
- Security & Verification may read results/evidence and return assessments to BrainOrchestrator/MAEP.
- Memory & Knowledge owns persistence APIs; callers must not bypass its authorization-aware write interface.

Forbidden dependencies:
- A branch must not instantiate or call a second task orchestrator.
- Branches must not import each other's private implementation modules.
- Security & Verification must not issue authorization grants.
- Research output, memory content or tool output must not mutate MAEP policy.
- Tools must not execute side effects based only on a plan or on untrusted content.
- No component may silently bypass state-transition, evidence or closure guards.

The dependency graph must be acyclic. Cross-branch workflows route through BrainOrchestrator using contracts. Shared pure utilities are allowed only when they contain no hidden orchestration, persistence or authority.

## 4. Task lifecycle

The canonical state vocabulary and allowed transitions are defined by `maep/spec/STATE_TRANSITION_TABLE_V1.md` and implemented as local primitives in `maep/core.py`: DRAFT, READY, ASSESSED, PLANNED, AUTHORIZED, RUNNING, VERIFYING, ACCEPTED, CLOSED_VERIFIED, BLOCKED, FAILED, CANCELLED, UNVERIFIED. This architecture must not introduce a parallel state vocabulary or bypass those transition edges.

Cancellation is a request/event, not a new task state, and does not itself mutate task state. For a RUNNING task, use the allowed RUNNING -> BLOCKED transition to stop new dispatch; reconcile in-flight effects while BLOCKED; only then use the allowed BLOCKED -> CANCELLED transition. CANCELLED is terminal and does not imply rollback. Terminal-state continuation creates a linked task or amendment; it does not silently reopen a terminal task. ACCEPTED is not CLOSED_VERIFIED until closure criteria and evidence are validated.

## 5. Standard interaction

1. Validate intake against the MAEP task contract.
2. Assign task/correlation IDs and preserve requested scope.
3. Plan with acceptance criteria, risks, evidence needs and stop condition.
4. Request action-specific authorization from MAEP immediately before each side effect.
5. Dispatch a minimal envelope to one branch.
6. Capture result, actual effects and evidence references.
7. Verify evidence and candidate/scope binding.
8. Reconcile uncertain outcomes before recovery.
9. Evaluate mandatory gates; close only with linked evidence.
10. Report facts, inferences, hypotheses, proposals and blockers distinctly.

## 6. Single-point-of-failure controls

BrainOrchestrator is a logical single coordinator, not a requirement for one giant module or one fragile in-memory process. The design requires durable task state/checkpoints, recoverable dispatch records, bounded deadlines, idempotency keys where applicable, and startup reconciliation. If the coordinator is unavailable, new side effects stop; already-dispatched actions are reconciled before resumption.

The MAEP ledger is currently documented as single-writer append-oriented JSONL and is not tamper-proof against a privileged filesystem actor. Do not describe it as cryptographically immutable or independently witnessed.

## 7. Deployment and non-goals

This document does not create runtime modules, endpoints, background services, tool adapters, databases or deployment configuration. Runtime integration, end-to-end authorization enforcement, restart recovery and operational resilience remain unimplemented until separately authorized.

## 8. Acceptance gate

See `ARCHITECTURE_ACCEPTANCE_CHECKLIST_V1.md`. Design acceptance requires complete contracts, rule-level traceability, a reviewed dependency inventory, documented failure semantics and no contradictions. Passing design acceptance does not mean HG runtime is implemented or HG is complete.
