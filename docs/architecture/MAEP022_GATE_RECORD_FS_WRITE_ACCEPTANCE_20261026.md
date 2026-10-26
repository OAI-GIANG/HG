# MAEP-022 gate record — fs.write adapter and read-back acceptance for runtime.service

Decision: **EXTEND_EXISTING** · gate_status: **PASS** (validated by `maep.core.validate_capability_evolution_decision`, test `runtime/tests/test_maep022_gate_record.py`).
Machine-readable record and evidence: `docs/architecture/maep022/fs-write-acceptance-gate-20261026.json`.
Candidate: `git:4fe69e1289e1b821f1c79599a0226143b0b193df` (branch `stt/fs-write-adapter-acceptance-20261026`). Policy version: MAEP-1.2.0. Date: 2026-10-26.

Scope: runtime.service gains `fs.write`, a read-back acceptance provider and MAEP-018 reconciliation. **Excluded:** registering them as production bindings (a separate, owner-confirmed change), any change to `hg serve` (main) or its deployed state, any retirement. A candidate, configuration, policy or dependency change re-opens this gate (MAEP-012).

## 1. Inventory
Source: `docs/architecture/MAEP022_INVENTORY_TOOLS_ACCEPTANCE_20261026.md` (PR #30), re-checked against main `261c5fa` and this candidate. Overlap: yes, for both the tool effect boundary and acceptance.

## 2. Decision and selected implementation
`hg serve`'s semantics are reused, not reinvented, and expressed in the runtime.service contract:

| hg serve (main) | runtime.service (this candidate) |
|---|---|
| `LocalFileWriteAdapter` (`hg/tools/gateway.py`) | `tools_automation/file_write_adapter.py` `RootedFileWriteAdapter` |
| `ActionGateway` pending actions + `reconcile` | `BrainOrchestrator.pending_effects` / `reconcile`, `POST /api/reconcile` |
| `AcceptanceGate` + `planned_write_readback_verifier` | `runtime/acceptance.py` `ReadbackAcceptanceProvider` |

## 3. Parity
| Property (main test) | Branch evidence |
|---|---|
| authorized write succeeds and is recorded (`test_authorized_write_succeeds_and_is_recorded`) | `test_authorized_write_is_atomic_verified_and_idempotent`; lifecycle E2E to CLOSED_VERIFIED |
| planned resource must match the real effect | adapter: resource must be `file:<path>`; E2E `test_adapter_refuses_a_path_that_differs_from_the_authorized_resource` |
| adapter enforces scope independently | `test_inputs_outside_the_planned_effect_are_refused_without_effect` |
| path traversal is invalid input | same test (`..`, absolute); plus symlink components refused (stricter) |
| grant expiring before the effect denies | Brain fresh authorization + `recheck_before_effect`; adapter refuses an expired decision |
| task not running / unknown task / step not in plan | Brain canonical task checks; E2E `test_dispatch_before_running_and_outside_scope_is_refused` |
| unknown tool unavailable, duplicate tool names | registry lookup; registry is a dict |
| known failure is FAILED, not pending | adapter FAILURE `effect: NONE`; only UNKNOWN is pending |
| unverified success is distinct | read-back digest mismatch → UNKNOWN (stricter: never SUCCESS) |
| raised and real timeout are UNKNOWN | `test_real_adapter_timeout_is_unknown`, E2E crash-after-write |
| unknown outcome blocks further effects; survives restart | `test_unknown_effect_blocks_further_effects_until_reconciled`, E2E `..._until_reconciled_applied`, `test_pending_unknown_effect_survives_a_restart` |
| reconcile inspects live state / detects not applied / unknown action rejected | same tests + `test_unknown_effect_reconciled_not_applied_allows_a_new_attempt` |
| acceptance: no/other-candidate/wrong-type/other-criterion/unlinked evidence not counted | `test_evidence_that_does_not_qualify_is_not_counted` (+ D4 approval required) |
| failing evidence fails even beside a pass | `test_failing_evidence_fails_even_beside_a_pass` |
| matching pass passes and closes | lifecycle E2E |
| read-back of every write before acceptance | `test_readback_failures`, E2E `test_file_changed_after_the_effect_blocks_acceptance` |

Not ported (limitations, outside this scope): `fs.read`, `code.*`, `test.run`, `url.read`; the READ_ONLY process mode (runtime.service governs writes through policy); the preflight API.

## 4. Comparison evidence
- Main baseline: `hg.tests.test_gateway` + `hg.tests.test_acceptance` 35 OK (3.13.17 cloud, 3.14.6 Termux); full main suite 234 OK.
- Branch: full suite OK (maep 280/1 skip, memory 70, brain 171, runtime 156, tools_automation 13) on 3.13.17; Termux 3.14.6: 702 tests all OK (runtime suite 225.6 s, was 57.7 s: the lifecycle E2E tests read whole ledgers per request).
- Mutations (one at a time, throwaway copies): branch 6/6 killed (request-digest binding, scope, symlink, MAEP-018 block, read-back compare, FAIL beside PASS). Main 2/3 killed: dropping the read-back **content compare** in `planned_write_readback_verifier` survives the full main suite — an untested safety check on the deployed line (MAEP-031 improvement: test-only PR #34 on main adds 5 direct tests that kill it).

## 5. Impact
- Receipts (additive): `task_ref`, `action`, `resource`, `scope`, `intent` on effect receipts; new `reconcile:` receipts.
- HTTP: new `POST /api/reconcile` (session + authority for the effect being reconciled).
- Composition: the receipt sink must support `read_all` (LocalReceiptSink does).
- Brain: an unreconciled UNKNOWN effect blocks further effects on that task, including after restart. Adapters with `timeout_s` run in a single-use worker thread.
- Acceptance depends on the D4 verifier and the D2-verified policy; with fixture seams it is only as strong as the fixtures.
- No production binding, no change to `hg serve`, its release or its state.

## 6. Recovery
Revert the merge commit on `stt/maep-v1-20261022`; nothing is registered or deployed, no data migration.
