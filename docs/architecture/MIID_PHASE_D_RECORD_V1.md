# MIID-1.0 Phase D — Intelligence Capabilities Record V1

- Directive: MIID-1.0 Phase D, owner instruction 2026-10-23 19:02 +07:00 ("Triển khai đến khi hoàn toàn kết thúc thì báo cáo chủ nhân").
- Base: `main` @ `29a26573938e7589c774adfb6f6b16e64da5849e`. Branch: `stt/miid-phase-d-intelligence`.
- Executor: STT under `MAEP_OWNER_DELEGATION_V1.md`. Python 3.13.17 locally; CI on 3.13 and 3.14.
- Review: internal only (MAEP-021). Status labels per CLAUDE.md.

## 1. What was built, where, and how it is reached

| ID | Capability | Code | Runtime call path | Tests | Status |
|---|---|---|---|---|---|
| C-12 | Model provider abstraction | `hg/brain/providers.py` | `ModelPlanner` / `Researcher` / `proposals_from_model` → `ModelRouter.complete` → provider | `hg/tests/test_providers.py` (20) | IMPLEMENTED, INTEGRATION_TESTED with test doubles; live model BLOCKED_EXTERNAL (§4) |
| C-13 | Planning engine | `hg/brain/planner.py`; `maep/authority/issuer.py` | `BrainOrchestrator.execute_goal` → planner → `check_plan` → `record_plan` → `TaskGrantIssuer` → authorize/run/verify/close | `hg/tests/test_planner.py` (19), `maep/tests/test_issuer.py` (9) | IMPLEMENTED, INTEGRATION_TESTED; live with the structured planner (§3) |
| C-14 | Layered memory | `hg/memory/store.py`, `hg/memory/index.py` | `build_runtime(memory=True)`; every task outcome → EPISODIC; research → SEMANTIC HYPOTHESIS; lessons → PROJECT HYPOTHESIS | `hg/tests/test_memory.py` (23 incl. context) | IMPLEMENTED, INTEGRATION_TESTED; live (§3) |
| C-15 | Context management | `hg/brain/context.py` | `execute_goal` builds context from memory for model planners | `test_memory.ContextTests`, `test_planner.test_memory_context_reaches_the_model_planner` | IMPLEMENTED, INTEGRATION_TESTED |
| C-16 | Research synthesis | `hg/research/research.py` | gateway outcomes (`fs.read`, `url.read`, `code.search`) → `documents_from_outcomes` → `Researcher.investigate` → `to_memory` | `hg/tests/test_tools_research.py` ResearchTests | IMPLEMENTED, INTEGRATION_TESTED (extractive); model summary only with test doubles |
| C-17 | Creative options | `hg/research/options.py` | `OptionGenerator.generate`; `proposals_from_model` | `test_tools_research.OptionTests` | IMPLEMENTED, UNIT_TESTED (no runtime caller in a task flow yet) |
| C-18 | Learning loop | `hg/verification/learning.py` | ledgers → `analyze` → lessons → `record_lessons` (memory) + proposed guard cases; `python -m hg learn` | `hg/tests/test_learning_ops.py` LearningTests | IMPLEMENTED, INTEGRATION_TESTED (real ledgers) |
| C-19 | Benchmark + regression cases | `hg/verification/benchmark.py`, `regressions.py`, `regression_cases.json` | `python -m hg bench`; CI step in the required `unittest` jobs | BenchmarkTests, RegressionCaseTests | IMPLEMENTED, INTEGRATION_TESTED, ENFORCED in CI (a violated invariant fails the required check) |
| C-20 | Code-intelligence tools | `hg/tools/code.py` | planner → gateway (permit) → `code.search`, `code.symbols`, `code.diff`, `test.run`, `url.read` | CodeToolTests, UrlReadTests | IMPLEMENTED, INTEGRATION_TESTED; `test.run` live under the trust root (§3) |
| C-21 | Observability | `hg/ops.py` | `python -m hg health` | HealthTests | IMPLEMENTED, INTEGRATION_TESTED; live (§3) |

Design rules that hold across the layer (each has negative tests):
- **A model proposes, HG decides.** Planners return only tool + params; HG derives action, resource, scope and authorization ID from the registered adapter. A plan is checked against tools, parameters, real-vs-planned effect and task scope (include/exclude). Invalid plans are revised at most three times (MAEP-014), then the task stays ASSESSED with the problems as evidence.
- **Autonomy never exceeds the owner's grant.** In `issue_task_grants` mode, per-task grants exist only if the live manifest on `main` permits every step. Their expiry is capped by the manifest grant, and every effect re-checks the manifest.
- **Memory and research are data, not authority.** No authorization path reads memory. Retrieved text is fenced as data in prompts. Research claims are INFERENCE and are stored as HYPOTHESIS; nothing becomes FACT without evidence.
- **No silent success.** Unavailable models leave the task ASSESSED with no effect. Failed checks give UNVERIFIED. An interrupted `test.run` stays UNKNOWN and blocks the task.

## 2. Tests and checks (local, Python 3.13.17)

| Suite | Before (`29a2657`) | After |
|---|---|---|
| `python -m unittest discover -s maep/tests -v` | 244 | 253 OK |
| `python -m unittest discover -s hg/tests -t . -v` | 82 | 185 OK |
| `python -m unittest discover -s .claude/hooks -p "test_*.py" -v` | 32 | 32 OK |
| `python -m hg selfcheck` | PASS | PASS |
| `python -m hg bench` | — | PASS: 10/10 cases, completion 1.0, correct denial 1.0, recovery 1.0, evidence-backed closures 1.0, unauthorized effects 0, false closures 0 |

Mutation check (scratch copies, not committed): 26 sabotages of the new guards; 24 killed. 2 are equivalent:
- "planner trusts a resource in params": params are validated to exact keys first, so the key cannot exist.
- "promote without evidence": `validate_claim` independently refuses a FACT without evidence.
Three survivors of the first run revealed real test gaps (unexpected-effect detection in the case runner, the credentials check reached for the wrong reason, the `test.run` contract). Tests were added and those mutants are now killed.

Defects found and fixed while building:
- `test.run` passed `-t <root>`, which made `unittest` require a package chain.
- A missing API key was classified as retryable (the router waited and retried a configuration problem). It is now `NOT_CONFIGURED`, which is not retried.

## 3. Live verification against the real trust root (2026-10-23, real network)

Runtime: `build_runtime(authority=CanonicalManifest.from_github(), issue_task_grants=True, memory=True)`; manifest on `main` at `29a2657`, fingerprint `99cca2b9…`.

| Goal (StructuredGoalPlanner) | Result |
|---|---|
| write `out/phase-d.txt` | CLOSED_VERIFIED; evidence "ISSUED 1 grant(s)" derived from the manifest |
| `test.run out/livetests` (EXECUTE) | CLOSED_VERIFIED |
| `url.read https://example.org/` | PLANNED; denied by the manifest (no `url:` scope); 0 effects |
| episodic memory after the three goals | `CLOSED_VERIFIED`, `CLOSED_VERIFIED`, `PLANNED` |
| `health` with trust check | OK (task ledger, action ledger, memory, trust root) |

## 4. Not done / blocked

| Item | Status | Evidence | Needed |
|---|---|---|---|
| Live model reasoning (Claude or local) | BLOCKED_EXTERNAL | `ANTHROPIC_API_KEY` not set in this session; no Ollama at `127.0.0.1:11434` (connection refused); router fails closed (`UNAVAILABLE`) | owner: provide an API key as a session/environment secret (never in the repo), or run a local model (Ollama) where HG runs |
| URL research under the trust root | blocked by policy, as designed | manifest has no `url:` scope | owner: add the URL prefixes HG may read to the manifest |
| T-1 (agents share the owner's GitHub identity) | open | RT06 record §5 | owner: separate agent identity + push ruleset |
| Semantic (vector) retrieval | NOT_JUSTIFIED yet | BM25 is enough for the current suite (MIID §11) | add only when a benchmark case shows a need |

## 5. What the numbers do and do not mean

The benchmark measures this fixed suite: safety invariants, completion of permitted tasks, correct denials, recovery and evidence-backed closure. It does not measure general intelligence or the quality of model reasoning. No model ran live in this phase. HG's reasoning layer is real, but it is a governed interface that a model plugs into; it is not a model.
