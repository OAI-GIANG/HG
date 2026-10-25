# HG Intelligence Upgrade Checkpoint — 2026-10-23

## Status
- Result: **IMPLEMENTED_LOCALLY_TESTED; PRODUCTION INTEGRATION UNVERIFIED; LV5 NOT CERTIFIED**.
- Repository: `OAI-GIANG/HG`
- Local root: `/data/data/com.termux/files/home/HG`
- Branch: `stt/maep-v1-20261022`
- HEAD: `f7f00a75c6a1b1363993c2fb9bc023171f080038`
- MAEP policy: `MAEP-1.2.0`
- Method: Remote Desktop Commander on Termux.
- No commit, push, merge, deploy, checkout, reset, stash, cleanup or service restart was performed.
- Pre-existing working tree changes were preserved.

## Delivered in this checkpoint

1. `brain/planning.py`
   - Introduces a bounded structured PlanningEngine for canonical MAEP tasks in ASSESSED state.
   - Requires current MAEP policy metadata and a candidate reference.
   - Supports explicitly injected JSON reasoning provider and optional candidate/policy-bound verified context resolver.
   - Enforces strict JSON shape, duplicate-key rejection, step/response/context bounds, known input references, exact resource scope/exclusions, DAG dependencies and topological ordering.
   - Requires coverage of all acceptance criteria and evidence requirements.
   - Side-effect steps must declare action-specific MAEP authorization, preconditions, evidence, verification, recovery and stop conditions.
   - Returns `VALIDATED_PLAN_NOT_AUTHORIZED`; it never grants authority, mutates state, writes Memory or executes steps.
   - Includes plan digest verification and at most one bounded correction for a rejected plan proposal.
   - Includes an optional standard-library OpenAI-compatible model adapter restricted to HTTP loopback; no public endpoint, proxy use, redirect following, implicit secret discovery, model service start/stop or remote deployment.

2. `brain/orchestrator.py`
   - Adds opt-in `plan_task(...)`.
   - Before invoking the reasoning provider, checks the canonical task ID, integrity-checked active trust root, active policy status/root/version/provenance/digest/approval evidence, verified candidate, repository identity `OAI-GIANG/HG`, and task/candidate binding.
   - Does not authorize or execute a planned action.

3. `runtime/composition.py`
   - Accepts optional explicit `reasoning_provider` and `context_resolver`.
   - Keeps planning disabled when a provider is not injected; no test/mock default was introduced.
   - Injects the planner into the Brain object only when configured.

4. `brain/tests/test_planning.py`
   - Positive/negative tests for valid planning, state/policy/candidate binding, wrong repository, scope escapes, incomplete acceptance/evidence coverage, unknown inputs, dependency cycles, unsafe side effects, malformed/duplicate JSON, context provenance mismatch, provider failure, local-only model endpoint, redirect safety, tamper detection and bounded correction.

5. `brain/schemas/task-plan-v1.schema.json` and `brain/README.md`
   - Add the versioned task-plan output schema and describe implementation boundaries.

## Evidence

- Targeted planning suite: **34 tests passed** at the last targeted run before the final regression.
- Full regression command:
  `python -m pytest maep/tests memory/tests brain/tests runtime/tests creativity_research/tests tools_automation/tests -q --disable-warnings --maxfail=1`
- Full regression result after implementation changes: **262 passed, 1 warning, 52 subtests passed**.
- `python -m compileall -q brain runtime`: PASS.
- `git diff --check`: PASS.
- Schema JSON parsing and required-field presence: PASS.
- Full JSON Schema Draft 2020-12 validator run: **NOT RUN** because `jsonschema` is not installed; no dependency was added.
- Live inference against the local model: NOT RUN.
- Trusted production context resolver: NOT provisioned/verified.
- Live HTTP/CLI/service entrypoint-to-plan E2E: NOT RUN.
- Production binding to the current HG candidate: NOT VERIFIED.

### Selected SHA-256 values
- `brain/planning.py`: `b715c80727ee987df852251ba40a3c83dda769950d5660217f3a70bcc0e30a7a`
- `brain/orchestrator.py`: `a0402d3d3e775738f7bbac832f10c2e3f0d1eabc16de4f4506436368fe5b03ef`
- `brain/tests/test_planning.py`: `18dd83a817b43c4e678bf653460ef67417e63a9f34c099e58e65abb5b1d47731`
- `brain/schemas/task-plan-v1.schema.json`: `0aef7026631c546bc3fa71b8efeb70b2bbc079a0e44df555691ce8770e2e35bc`
- `brain/README.md`: `ffbb64a211bc23205b8debcd4cfb7318e27a6bad0e0b906b3b837962c92cc0aa`
- `runtime/composition.py`: `b58be22d392ec3a7ed97f2a17db8a4c4e648b2a2b24979b13958f8ef90d15458`

## Runtime preservation and blocker

Observed Termux supervisor state after tests:
- `hg2-model`: running (PID 15010)
- `hg2-runtime`: running (PID 15005)
- `hg-backend`: down
- `hg-runtime`: down

Previously inspected live runtime source directory:
`/data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676`

The live service is a separately named HG2 release, not proven to be built from or bound to the current `OAI-GIANG/HG` candidate. It was intentionally not restarted, replaced or patched.

## Next acceptance gates

P0. Establish exact source/candidate identity and approved production runtime binding.
P1. Provision/verify approved production root, policy and evidence/context resolver providers.
P2. Configure the optional local model provider through a verified runtime configuration boundary; do not read secrets from repository files or embed them in code.
P3. Run live but non-destructive end-to-end tests: bad policy/candidate blocks before model call; invalid plans are rejected; no planning call causes adapter invocation; candidate/policy changes block; timeout/UNKNOWN is surfaced.
P4. Verify Memory integration and persist/reconcile plan records only under an explicit MAEP-governed contract.
P5. Establish a repeatable reasoning benchmark and evaluate factual accuracy, planning success, evidence grounding, uncertainty handling, adversarial prompts and recovery.

**Stop condition:** keep Lv5 and production claims blocked until the exact HG candidate, approved live providers, real model quality and end-to-end runtime behavior are all demonstrated with current evidence.
