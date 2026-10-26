# MAEP-022 inventory — tool adapters and acceptance (runtime.service vs hg serve)

Status: **INVENTORY ONLY.** This is not a gate decision. No capability is added, consolidated or retired here.
Date: 2026-10-26. Sources: `main` @ `f3dac34` (`hg serve`), `stt/maep-v1-20261022` @ `79e42c9` (`runtime.service`).
Purpose: the first step of the MAEP-022 Capability Overlap & Superiority Gate (MAEP_CONSTITUTION_V1_2 MAEP-022; ADR-012 decision 4). It covers the two production bindings that `runtime.service` still lacks: `tool-adapter-registry` and `acceptance-provider`.

Evidence levels: E3 means the source was read, E4 means tests were run (counts are listed). The comparison and superiority evidence that MAEP-022 requires is **NOT_RUN**.

## 1. Tool adapters

| Aspect | `hg serve` (main) | `runtime.service` (branch) |
|---|---|---|
| Contract | `hg/tools/gateway.py` `ToolAdapter`: `execute(params, permit)`, `validate_params`, `resource_for`, `in_scope`, `intent`, `verify`, `reconcile`, `describe` | `tools_automation/contracts.py` `ToolAdapter` (Protocol): `execute(*, request, authorization, idempotency_key) -> {"outcome": SUCCESS\|FAILURE\|UNKNOWN, ...}`; structural validation only (`validate_adapter_request`, `validate_adapter_result`) |
| Implementations | `fs.write`, `fs.read` (`LocalFileWriteAdapter`, `LocalFileReadAdapter`, rooted, no `..`); `code.search`, `code.symbols`, `code.diff`, `test.run`, `url.read` (`hg/tools/code.py`) | **none** (Protocol only) |
| Effect boundary | `ActionGateway` (`gateway.py:238`): per-effect permit bound to the adapter's own gateway and exact resource, single use; policy re-check, execution mode, planned vs real effect check | `BrainOrchestrator.dispatch` (`brain/orchestrator.py`): canonical Memory task must be RUNNING and in scope; NativePolicyEngine authorize → durable idempotency claim → fresh authorize → `recheck_before_effect` → `adapter.execute`; BLOCKED/DENY receipts |
| Unknown outcome / restart | `intent()` recorded before effect; `pending_from_events` (`gateway.py:222`) blocks further effects until `reconcile()` reports the live outcome (MAEP-018, RT-05) | Exception, timeout or invalid result → outcome `UNKNOWN` in the receipt; `RecoveryManager.classify_outcome` gives `RECONCILIATION_REQUIRED`; no adapter-level `reconcile()` in the contract |
| Exposed over HTTP | only `fs.write` / `fs.read` (`hg/http_api.py:102`) | `/api/dispatch` with any registered adapter name |
| Tests (E4) | `hg/tests/test_gateway.py` 24 tests | `tools_automation/tests/test_contracts.py` 8 tests |
| Live use | deployed, smoke CLOSED_VERIFIED on release `f7cfd766…` | none; dispatch through the production graph is BLOCKED by N1 (`runtime/tests/test_production_composition_e2e.py`) |

Overlap: **yes**. Both are effect boundaries for HG tool actions. Adding any production adapter to `runtime.service` duplicates a `hg serve` capability, so MAEP-022 is applicable: inventory → comparison → decision (`CONSOLIDATE_KEEP_SUPERIOR` / `EXTEND_EXISTING`, …) → impact → regression evidence. Retirement on the `hg serve` side also needs retirement authorization and a recovery plan.

Contract gap (E3): the two `ToolAdapter` contracts are not compatible. Porting `fs.write` needs either an adapter shim, which would lose `intent`/`reconcile` unless the branch contract gains them, or extending the branch contract with reconciliation. This must be settled in the comparison step, not assumed.

## 2. Acceptance

| Aspect | `hg serve` (main) | `runtime.service` (branch) |
|---|---|---|
| Component | `hg/verification/evidence.py` `AcceptanceGate`: one gate per acceptance criterion, built from task-store evidence whose `test_ids` contain the criterion, matching candidate and evidence type; `build_closure` validated by `validate_closure` | `MemoryStore.transition_task` consumes `acceptance_provider(task_id, target) -> {candidate_ref, policy_version, mandatory_gates[], closure}`; Memory itself re-checks that gates cover every mandatory criterion, `evaluate_gate` against Memory evidence, and `validate_closure` |
| Independent verifier | yes: `planned_write_readback_verifier` (`hg/http_api.py:136`) reads every planned write back from the confined root before AC-READBACK can pass | none: no provider produces gates; nothing reads effects back |
| Tests (E4) | `hg/tests/test_acceptance.py` 11 tests; deployed smoke reached CLOSED_VERIFIED with independent read-back | Memory contract tests with a test-only provider (`memory/tests/test_store.py`) |
| Production binding | in use | **missing** (`acceptance-provider` in `runtime/production_config.py` `REQUIRED_BINDINGS`) |

Overlap: **yes**. Both decide ACCEPTED/CLOSED_VERIFIED. What counts as passing evidence (which verifier, which evidence types) is acceptance semantics. Writing a provider that just turns criteria plus recorded evidence into gates would let any authorized evidence writer close a task, with no independent check like main's read-back. That must not be done without a comparison and decision.

## 3. What the MAEP-022 gate record still needs (NOT_RUN)

1. Comparison evidence on the same candidate across: correctness, security, reliability, functional coverage, compatibility, performance/resource cost, maintainability. Run both suites, apply mutation and negative tests to both boundaries, and check unknown-outcome behaviour on restart.
2. The decision with a stated superiority basis, and the selected implementation.
3. Impact analysis covering `/api/dispatch` exposure, the HTTP tool allowlist, the restart and reconciliation path, and the N1 dependency (no dispatch is possible until N1 is decided).
4. Regression evidence on 3.13, 3.14 and Termux.
5. For any retirement on `hg serve`: `retirement_authorization_ref` and `recovery_plan_ref`.

Blocking dependencies: **N1** (owner) — without it no task can be created and no dispatch can run on `runtime.service`, so a runtime comparison is impossible. **D4** — the acceptance provider must rely on Memory records whose approval rule is defined.
