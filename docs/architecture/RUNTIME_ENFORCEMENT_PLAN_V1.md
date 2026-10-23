# Runtime Enforcement Plan V1

- Status: **DESIGN — RT-01 IMPLEMENTED and UNIT_TESTED (2026-10-23); RT-02..RT-06 not implemented; RT-07 done (CI plus ruleset `main-maep` on `main`)**
- Base: MAEP-1.0.0 at `f7f00a75c6a1b1363993c2fb9bc023171f080038` plus the Phase 2 fixes on the same branch as this file.
- Inputs: `HG_ARCHITECTURE_V1.md`, `BRAIN_ORCHESTRATOR_CONTRACT_V1.md`, `MAEP_INTEGRATION_DESIGN_V1.md`, `DATA_FLOW_TRUST_BOUNDARY_V1.md`.
- Not available: `BRAIN_ORCHESTRATOR_MASTER_PLAN_V1.md` was never committed to any accessible ref; nothing here depends on it.

## 1. Inventory (observed, not assumed)

The only executable code is the `maep` package: `core.py` (stateless validators and guards), `policy.py` (PolicyEvaluator), `ledger.py` (single-writer JSONL). No module imports `maep` outside `maep/tests/`. There is no entry point, task store, orchestrator, tool adapter, network or file side effect, CI workflow or deployment.

Consequence: every MAEP guard is currently advisory. `transition()` accepts guard booleans from its caller, so it can only be as honest as the caller. Enforcement requires a component that owns the facts the guards are derived from.

## 2. Current enforcement matrix

| Control | Rule | Implementation | Runtime call site | Status |
|---|---|---|---|---|
| Task contract | 001-002 | `validate_task` | none | IMPLEMENTED, UNIT_TESTED |
| Action authorization | 003-005, 019 | `PolicyEvaluator.evaluate` over `authorize_action` | none | IMPLEMENTED, UNIT_TESTED; BLOCKED_FOR_TRUST_INTEGRATION |
| Sole coordinator | 006 | none | none | MISSING |
| State transitions | 007, 026 | `transition`, `validate_linked_task`; `TaskStore.apply_transition` derives guards from stored facts (RT-01) | none | IMPLEMENTED, UNIT_TESTED; no runtime caller yet |
| Acceptance/closure | 008, 013 | `evaluate_gate`, `validate_closure` | none | IMPLEMENTED, UNIT_TESTED |
| Evidence binding | 010-012 | `validate_evidence`, `assess_candidate_change` | none | IMPLEMENTED, UNIT_TESTED |
| Retry/recovery | 014, 018 | `retry_decision`, `recovery_decision` | none | IMPLEMENTED, UNIT_TESTED |
| Event history | 015 | `ledger.append_event` | none | IMPLEMENTED, UNIT_TESTED; single writer, not tamper-proof |
| Read-only mode | 023 | `enforce_execution_mode` | none | IMPLEMENTED, UNIT_TESTED |

No row is ENFORCED or INTEGRATION_TESTED. Agent-side, the PreToolUse guard hook (`.claude/hooks/maep_guard.py`) blocks destructive git operations and writes to the delegation file in Claude Code sessions; see `maep/spec/RT01_VALIDATION_RECORD_V1.md`.

## 3. Target components

Each component reuses an existing primitive; none adds a dependency (architecture invariant 9, MAEP-022).

1. **TaskStore (task-state owner).** Holds task records and is the only mutation path: `apply_transition(task_id, target, *, expected_version)`. It derives guard values from facts it recorded itself (validated task contract, a PolicyEvaluator ALLOW decision, recorded results and candidate, gate outcomes) rather than accepting booleans, then calls `transition()`. Compare-and-set on `expected_version` rejects concurrent overwrite. Every accepted transition is appended to the ledger before the in-memory state changes.
2. **Authority provider.** Loads grants into `PolicyEvaluator` and supplies the condition provider. BLOCKED_FOR_TRUST_INTEGRATION: the owner must choose the trust root (see Q-5). Until then grants can only come from test fixtures.
3. **ActionGateway (tool execution boundary).** The only object that holds side-effect capabilities. Immediately before each effect: `enforce_execution_mode`, then `PolicyEvaluator.evaluate` on the exact request; DENY stops the effect. Returns SUCCEEDED, FAILED or UNKNOWN; a timeout is UNKNOWN and goes to `recovery_decision`.
4. **Evidence recorder.** Wraps `ledger.append_event`; one writer per ledger file. If audit capture is mandatory and the append fails, the action is held (fail closed).
5. **AcceptanceGate.** Runs `evaluate_gate` and `validate_closure` on evidence read from the recorder, not on caller-supplied maps.
6. **BrainOrchestrator.** Implements `BRAIN_ORCHESTRATOR_CONTRACT_V1.md`: intake via `validate_task`, dispatch only through ActionGateway, and the only holder of the TaskStore write handle.

## 4. Implementation tasks

Order matters: each task's tests run against real objects, not mocks of MAEP.

| ID | Task | Depends on | Acceptance tests (negative tests mandatory) | Rules |
|---|---|---|---|---|
| RT-01 | TaskStore with derived guards, CAS versioning and ledger-first writes | — | direct state mutation impossible through public API; RUNNING→VERIFYING denied with no recorded result; stale `expected_version` rejected; ledger append failure leaves state unchanged | 007, 015, 026 |
| RT-02 | ActionGateway with a fake in-memory side-effect target | RT-01 | effect denied without ALLOW decision; denied in READ_ONLY; denied after grant expiry between plan and execution; timeout reported UNKNOWN, not retried | 003, 005, 018, 023 |
| RT-03 | Evidence recorder and AcceptanceGate over stored evidence | RT-01 | closure denied when evidence is for another candidate or a gate is NOT_RUN; evidence recorded by a different task rejected | 008, 010-013 |
| RT-04 | Minimal BrainOrchestrator (`submit_task`, `dispatch`, `record_result`, `close_task`) | RT-01..03 | a second dispatcher cannot obtain the TaskStore write handle; full happy path reaches CLOSED_VERIFIED only with linked evidence | 006, 008 |
| RT-05 | Restart recovery from the ledger | RT-01, RT-02 | after restart, an UNKNOWN non-idempotent action blocks new effects until reconciled | 018 |
| RT-06 | Authority provider on the chosen trust root | Q-5 decision | grants not from the trust root are rejected; tampered grant rejected | 004, 005, 017 |
| RT-07 | CI running the suite on push/PR, then branch protection | owner approval | CI fails on a deliberately failing test | 024 |

RT-01 to RT-05 are in-process integration tests. They would justify INTEGRATION_TESTED for those boundaries only; they are not end-to-end or production evidence.

## 5. Open questions for the owner

- **Q-1 Non-expiring grants.** `authorization.schema.json` allows `expires_at: null`; `PolicyEvaluator` rejects such grants unless built with `allow_non_expiring=True`. Confirm or change the default.
- **Q-2 CLOSED_VERIFIED continuation.** The state table names only FAILED/CANCELLED → new linked DRAFT; MAEP-026 covers terminal states generally. `validate_linked_task` accepts all three terminal states.
- **Q-3 Meaning of "VERIFYING requires a result/candidate".** Implemented as both `result_recorded is True` and a non-empty `candidate_ref`.
- **Q-4 Guard names.** `state-transition.schema.json` leaves `guard_id` free-form. New names used: `result_recorded`, `candidate_ref`, `blocker_resolution_evidence_refs`, `authority_reassessed`, `risk_reassessed`.
- **Q-5 Trust root.** Options: (a) grants file changed only through owner-reviewed PRs to a protected branch; (b) owner-signed grants (needs key management); (c) an external identity provider. Each has different tooling and recovery costs.
- **Q-6 Version.** The Phase 2 changes align code with existing spec text and keep `POLICY_VERSION = "MAEP-1.0.0"`. Removing `transition(new_task=...)` is an API change; decide whether MAEP-028 calls for a new version.

**Resolution (2026-10-23, MAEP-1.1.0):** Q-1 to Q-4 accepted as implemented; Q-5 trust root is the owner `OAI-GIANG`; Q-6 `POLICY_VERSION` raised to `MAEP-1.1.0`. RT-06 now depends on choosing a machine-verifiable anchor for that trust root. Details and who decided each item: `maep/spec/MAEP_OWNER_DELEGATION_V1.md` §4.
