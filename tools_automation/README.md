# Tools & Automation — Adapter Contract V1

Status: **IMPLEMENTED CONTRACT / UNIT TESTED / RUNTIME INTEGRATION NOT VERIFIED**

## Ownership and authority

Tools & Automation owns bounded tool-adapter interfaces and execution-boundary validation. It does not own task planning, policy authority, persistent knowledge, research decisions, or final acceptance. `BrainOrchestrator` remains the only coordinator. MAEP and NativePolicyEngine determine whether a requested action is authorized.

## Implemented files

- `tools_automation/contracts.py`: standard-library-only typed request/context/outcome contracts and structural validators.
- `tools_automation/__init__.py`: stable public exports.
- `tools_automation/tests/test_contracts.py`: positive and negative contract tests.

## Boundary contract

- Contract identifier: `hg.tool-adapter.v1`.
- An adapter request identifies task, action, resource, non-empty bounded scope, idempotency key and optional deadline.
- Structural validation is not authorization. A valid request must still pass the MAEP/NativePolicyEngine chain.
- Adapter registration alone grants no capability.
- Adapters must independently enforce exact action/resource/scope immediately before side effects.
- Results use only `SUCCESS`, `FAILURE`, or `UNKNOWN`. A timeout or ambiguous post-dispatch error must remain `UNKNOWN` until reconciled.
- Provider/evidence references are identifiers, not self-authenticating proof.
- No ambient credentials, unrestricted handles, network clients, process adapters, or production defaults are supplied by this contract package.
- `tools_automation/file_write_adapter.py` `RootedFileWriteAdapter` (`fs.write`, MAEP-022 EXTEND_EXISTING of hg serve's adapter): rooted relative paths, no `..` or symlink components, authorization must be an unexpired ALLOW binding this exact request digest/action/resource/task, resource `file:<path>` inside a `file:` scope prefix, atomic write + fsync + replace, read-back digest; invalid input is FAILURE with no effect; `intent()`/`reconcile()` for UNKNOWN outcomes; `timeout_s` bounds the call (BrainOrchestrator then records UNKNOWN). Not registered in production.

## Cross-branch flow

1. Brain creates a task/step and sends the minimal operation request.
2. MAEP/NativePolicyEngine authorizes the exact action, resource, candidate and scope.
3. Brain reserves durable idempotency and rechecks authorization immediately before calling the registered adapter.
4. Tools & Automation validates its input and enforces scope at the point of action.
5. The adapter returns a structured outcome and evidence/effect references.
6. Brain records the durable receipt; Memory & Knowledge may persist only through its approved API.
7. Security & Verification and MAEP acceptance criteria evaluate the evidence; missing/ambiguous evidence blocks closure.
8. Creativity & Research may propose operations or analyze results but cannot dispatch side effects or grant authority.

## Validation record

- Python: 3.14.6, Termux / Android aarch64.
- Targeted tests: `8 passed, 10 subtests passed`.
- Full suite after additions: `178 passed, 35 subtests passed`.
- Regression delta: baseline `170 passed, 25 subtests passed`; eight new test methods and ten new subtest cases passed.
- Limitations: contract unit tests do not prove real adapters, production authority, persistent receipt durability, or end-to-end effects. Runtime integration is not verified.

## Next stages

1. Review existing Brain request/authorization/result shapes against this contract without duplicating the coordinator.
2. Add one explicitly scoped adapter only after defining its target, permitted resources/actions, credential boundary and independent tests.
3. Add integration tests proving authorization denial prevents adapter invocation, revalidation is honored, duplicate keys do not repeat effects, and uncertain outcomes are reconciled.
4. Obtain independent security review and MAEP acceptance evidence before deployment.


## Integration update — 2026-10-22

Status: **INTEGRATION TESTED LOCALLY / END-TO-END PRODUCTION NOT VERIFIED**

The single existing `BrainOrchestrator` now invokes the branch-4 structural request validator before authorization and validates adapter results after invocation. Invalid requests are blocked before authorization and before adapter effects. Malformed results become `UNKNOWN`; they are never promoted to `SUCCESS`. Existing MAEP/NativePolicyEngine authorization, durable idempotency reservation, pre-effect authorization recheck and receipt recording remain owned by Brain.

Additional integration tests cover:
- Missing scope rejected before authority evidence or adapter invocation.
- Malformed provider reference returned by an adapter becomes UNKNOWN and is receipted for reconciliation.
- An explicit UNKNOWN adapter outcome remains UNKNOWN.

Local evidence on Termux / Python 3.14.6:
- `brain/tests/test_orchestrator.py` + `tools_automation/tests/test_contracts.py`: 17 passed, 10 subtests passed.
- Full-suite and hash evidence are recorded in the MAEP execution report when generated.
- `MemoryStore` and its native-authority adapter exist, and runtime composition accepts the Brain/adapter registry and durable receipt/evidence dependencies. This change does not directly write into MemoryStore; persistence of task knowledge remains behind its existing approved interface.
- Security & Verification is represented here by NativePolicyEngine, evidence sinks, fail-closed dispatch and the tests above; a separately deployed security-verification branch and independent security review have not been demonstrated.

Residual risks:
- Adapter result references are structurally checked but their underlying evidence is not independently dereferenced or verified by this package.
- No production adapter was added; all current dispatch tests use fixtures.
- Runtime composition tests do not constitute an end-to-end production deployment.
