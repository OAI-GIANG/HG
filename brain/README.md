# HG Brain — bounded planning and reasoning boundary

## Status

- Planning engine: implemented locally; unit tests provide isolated contract evidence.
- Provider adapter: implemented for OpenAI-compatible endpoints bound to loopback only.
- Default mode: no provider is configured automatically.
- Runtime use: opt-in through `runtime.composition.build_runtime(reasoning_provider=...)`; current running HG2 service was not modified or restarted.
- Planning result: `VALIDATED_PLAN_NOT_AUTHORIZED`, never a grant to execute.

## Architecture

`PlanningEngine` accepts a canonical MAEP task snapshot and requires state `ASSESSED`, current `MAEP-1.2.0` policy metadata and a non-empty candidate reference. It asks an explicitly supplied `JSONReasoningProvider` for a plan candidate, then deterministically validates:

- bounded step count and strict JSON shape;
- exact task identity and allowed resource scope, including exclusions;
- input references and optional verified context resolved through an explicitly supplied `ContextResolver`;
- dependency identity, DAG cycles and topological execution order;
- coverage of every acceptance criterion and evidence requirement;
- action-specific authorization requirements, preconditions, evidence, recovery and stop controls for side-effect steps;
- candidate/policy binding and canonical SHA-256 plan digest.

The JSON output contract is `schemas/task-plan-v1.schema.json`. Python standard library only; no paid API or third-party dependency is required by this module.

## Local model adapter

`LocalOpenAICompatibleProvider` is optional and only accepts an HTTP loopback endpoint such as a caller-configured `http://127.0.0.1:<port>/v1/chat/completions`. It limits timeout and response size, requests JSON output, and requires the caller to inject any API key. It never discovers secrets from disk, connects to public hosts, or starts/stops/reconfigures a model server.

An endpoint being reachable does not prove that its served model is the approved HG model, is bound to the current repository candidate, or meets any intelligence benchmark. Those require separate runtime provenance and benchmark evidence.

## Safety and non-goals

- The model only proposes. Model output, task content, retrieved content and output references do not grant authority.
- Context is accepted only when the injected resolver returns VERIFIED records bound to the exact candidate and policy and carrying evidence references. Resolver trust/provenance still must be established at production composition.
- A plan never writes Memory, changes task state, calls an action adapter, or performs a side effect.
- Execution must separately flow through the existing Brain dispatch, canonical Memory task snapshot, native MAEP authority decision, idempotency reservation and pre-effect authorization recheck.
- The implementation is not proof of autonomous self-improvement, unrestricted self-healing, AGI, or Lv 5 capability. Model quality and end-to-end runtime behavior are not benchmarked by unit tests.

## Use

```python
from brain import LocalOpenAICompatibleProvider, PlanningEngine

provider = LocalOpenAICompatibleProvider(
    endpoint="http://127.0.0.1:8788/v1/chat/completions",
    model="caller-configured-local-model",
    api_key=caller_supplied_key,
)
planner = PlanningEngine(provider=provider)
# brain.plan_task(task_ref="...", candidate_target=<trusted current-candidate target>)
# is available only when this planner is explicitly injected into BrainOrchestrator/build_runtime.
```


## Bounded critique and scenario simulation

### CritiqueEngine

- Implementation: `brain/critique.py`; contract: `hg.critique.v1`; schema: `schemas/critique-v1.schema.json`.
- The caller must explicitly inject a critique `JSONReasoningProvider`. No provider is selected automatically. The provider must declare and actually enforce `timeout_seconds` in (0, 30]; a generic synchronous provider that cannot enforce a timeout is rejected. This is a declared adapter contract, not proof that a custom provider honors it.
- The critique input is bound to the exact task, candidate, MAEP policy version and validated plan digest.
- Every supplied claim and every plan step must be classified exactly once as `NO_BLOCKER`, `BLOCKER`, or `UNRESOLVED`.
- Cited references must come from the input allowlist. A `SOURCE_SUPPORTED` counterargument must cite at least one supplied reference.
- Verdicts: `ACCEPT`, `REVISE`, `REJECT`, `INSUFFICIENT_EVIDENCE`. ACCEPT means no blocking issue was found in the supplied material; it is not factual verification or permission to act.
- The engine performs one provider call only. It does not revise a plan, call tools, write Memory, mutate task state or grant authority.

### ScenarioEngine

- Implementation: `brain/simulation.py`; contract: `hg.scenario.v1`.
- Schemas: `schemas/scenario-request-v1.schema.json` and `schemas/scenario-result-v1.schema.json`.
- This is a local deterministic numerical state-transition engine, not a general-purpose code runner. Supported operations are SET, ADD, MULTIPLY, MIN and MAX. It never evaluates user-provided code.
- Inputs require named numeric state variables, explicit units/ranges, declared transitions, a finite horizon and explicit scenarios. Out-of-domain transitions stop that scenario rather than silently clamping the value.
- Default maximum: 20 scenarios, 20 steps per scenario, 16 state variables, 32 rules, 5-second wall-clock budget and 180,000-byte output bound. These are guardrails, not measured performance guarantees.
- Every outcome has `epistemic_label=SIMULATED`, `authority_effect=NONE` and `side_effects_performed=false`. Sensitivity ranges are only across supplied scenarios, not statistical confidence intervals.

### Orchestration

- `BrainOrchestrator.critique_plan(...)` rereads the canonical task, active trust root, active policy and candidate before invoking critique.
- `BrainOrchestrator.simulate_scenarios(...)` validates the task/candidate/policy binding before simulation.
- `BrainOrchestrator.review_and_simulate(...)` performs one critique pass; it runs one bounded scenario set only if the verdict is ACCEPT; it then critiques that simulated output once. It stops on any other verdict or on budget exhaustion.
- It does not automatically rewrite a plan. If the critique requests revision, the caller must explicitly request a new plan and review it separately; there is no recursive retry loop.
- The runtime composition root exposes the deterministic ScenarioEngine by default but enables CritiqueEngine only when `critique_provider` is explicitly injected.

### Verification boundary

The tests in `brain/tests/test_critique.py`, `test_simulation.py`, `test_critique_simulation_integration.py`, `test_critique_simulation_schemas.py`, and `runtime/tests/test_http_server.py` cover contract validation, invalid evidence references, verdict consistency, numeric bounds, unit mismatch, deterministic results, identity drift, bounded orchestration and HTTP boundary behavior.

### HTTP exposure (candidate runtime only)

`POST /api/tasks/{task_id}/review-and-simulate` uses the existing loopback-only `HGHTTPServer`, owner-approved request authenticator, and verified HG candidate provider. The request requires `plan`; optional fields are `claims`, `evidence_refs`, `assumptions`, `constraints` and `scenario_request`. Contract: `schemas/review-and-simulate-request-v1.schema.json`. If no critique provider is explicitly configured, the endpoint responds BLOCKED/503. It does not dispatch tools, write Memory or alter task state. This route exists in the candidate code only; active production runtime binding has not been verified.

Candidate code and tests do not prove that the active service imports these modules. Live runtime binding and production integration remain unverified until an authorized staging build has a reproducible source manifest and a demonstrated import/call path.


### Offline simulation benchmark

Run from the HG checkout:

```sh
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python3 -m brain.benchmarks.benchmark_scenario_engine --iterations 30
```

The benchmark uses the maximum configured 20 scenarios x 20 transitions, records wall-clock p50/p95, CPU time, output bytes and process VmHWM delta, and writes only JSON to stdout. It does not invoke a model or alter HG data. VmHWM delta is a process high-water delta, not a per-request peak-RAM guarantee.
