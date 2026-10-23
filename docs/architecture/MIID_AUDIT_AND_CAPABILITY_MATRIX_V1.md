# MIID-1.0 — Phase A Audit and Capability Matrix V1

- Directive: HG Master Intelligence Integration Directive MIID-1.0 (owner instruction, 2026-10-23)
- Baseline audited: `main` @ `ea2bdf14aef03cc17e33634b26ebc0b72ada6688` (merge of PR #2); re-based on `main` @ `e1c66ee2c03dfa708ccaea03385350b0eefef9cc` (merge of PR #3) after a parallel session landed RT-01, CI and an agent guard hook during this work
- Policy: MAEP-1.1.0
- Method: every file in the repository was read; the unit suite was run. Nothing below is inferred from a file or module name alone.
- Review: internal only (MAEP-021). No independent review is claimed.

## 1. Baseline (observed)

| Item | Observation |
|---|---|
| Remote / branch / HEAD | `https://github.com/OAI-GIANG/hg`, `main`, `ea2bdf1`; clean working tree |
| Executable code | `maep/core.py` (443 lines, stateless guards/validators), `maep/policy.py` (117, `PolicyEvaluator`), `maep/ledger.py` (56, single-writer JSONL) |
| Callers of `maep` outside tests | none |
| Entry point / runtime / orchestrator / tool adapter / task store | none |
| Dependencies | Python standard library only (Python 3.13.17 in this environment) |
| CI | none |
| Baseline tests | `python3 -m unittest discover -s maep/tests -v` → exit 0, **128 tests, OK** |
| Design documents | `docs/architecture/*` (HG-ARCH-1.0, BO-CONTRACT-1.0, runtime enforcement plan RT-01..RT-07, ADR-001..010), all marked DESIGN |

Consequence: every MAEP control is advisory. `transition()` trusts guard booleans from its caller; nothing owns the facts those guards should be derived from.

Update at `e1c66ee` (PR #3, merged while this audit was in progress): `maep/task_store.py` (RT-01 TaskStore, derived guards, CAS, ledger-first; 41 tests), `.claude/hooks/maep_guard.py` (agent PreToolUse guard; 29 tests) and `.github/workflows/maep-tests.yml` (CI) now exist. Baseline at `e1c66ee`: MAEP 169 tests OK, hook 29 tests OK. The TaskStore still had no runtime caller, no restart recovery and no single-writer claim.

Reconciliation: a first version of this work had its own TaskStore under `hg/`. Two task-state owners would violate MIID §7, MAEP-022 and ADR-009, so it was dropped; the merged `maep/task_store.py` is the single owner and was extended additively (restore, writer claim, plan) instead.

## 2. Mapping MIID layers to the existing HG architecture

MIID §7 lists twelve target layers and says to extend existing owners rather than duplicate them (also MAEP-022, ADR-009). HG already fixes five functional branches plus MAEP as cross-cutting governance (ADR-002). The MIID layers therefore map onto existing owners; no sixth branch and no parallel architecture is introduced.

| MIID layer | HG owner (existing design) | Code location (this work) |
|---|---|---|
| 1 Core / Domain | MAEP contracts + state table | `maep/core.py` (unchanged) |
| 2 Brain Orchestrator | BrainOrchestrator | `hg/brain/orchestrator.py` |
| — task-state owner | BrainOrchestrator (RT-01 TaskStore) | `maep/task_store.py` (from PR #3, extended here) |
| 3 Reasoning & Planning | HG Brain | not built (see matrix) |
| 4 Model Provider Abstraction | HG Brain | not built (see matrix) |
| 5 Tool Registry & Adapters | Tools & Automation | `hg/tools/gateway.py` |
| 6 Authorization & Execution Guard | MAEP `PolicyEvaluator` + ActionGateway boundary | `maep/policy.py`, `hg/tools/gateway.py` |
| 7 Memory & Knowledge | Memory & Knowledge | not built beyond the event ledger |
| 8 Retrieval & Research | Creativity & Research | not built |
| 9 Verification & Evaluation | Security & Verification | `hg/verification/evidence.py` (AcceptanceGate); evidence held by TaskStore |
| 10 Evidence Ledger & Audit | Security & Verification over `maep/ledger.py` | task ledger (TaskStore) + action ledger (`EventLog`) |
| 11 Runtime & Interface | BrainOrchestrator entry | `hg/runtime.py` (assembly), `hg/__main__.py` (CLI) |
| 12 Observability | cross-cutting | partial: structured ledger events + `status` command |

## 3. Capability matrix

Status vocabulary from MIID §14. "Value / cost / risk" are H/M/L judgements, not measurements. Priority follows MIID §14 ordering (system-wide impact, unlocks others, reliability, feasibility, cost, independence).

| ID | Capability (MIID group) | Status at baseline | Evidence | Value | Cost | Risk | Target location | Depends on | Acceptance test | Priority | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | Task state owner, transition guards derived from facts, CAS (B, Phase C #1) | PARTIALLY_IMPLEMENTED at `ea2bdf1`; EXISTS_AND_VERIFIED (unit) at `e1c66ee` | PR #3 `maep/task_store.py`, 41 tests; no runtime caller, no restart, no single-writer claim | H | M | M | `maep/task_store.py` | maep.core | as RT-01 plus: second writer refused; restore rejects inconsistent history | P0 | Reuse PR #3 store; extend with restore + writer claim + plan |
| C-02 | Authorization at the execution boundary (D, Phase C #2–3) | PARTIALLY_IMPLEMENTED | `PolicyEvaluator` unit-tested; no call site | H | M | M | ActionGateway | C-01 | effect denied without ALLOW, in READ_ONLY, after expiry; adapter enforces scope independently | P0 | Build now (RT-02) |
| C-03 | Tool registry with schema, risk, timeout, error taxonomy (D) | MISSING | no adapter exists | H | M | M | ActionGateway + ToolAdapter | C-02 | unknown tool → TOOL_UNAVAILABLE; bad input → INVALID_INPUT; timeout → UNKNOWN, not retried | P0 | Build now; one real adapter (local file write/read, confined root) |
| C-04 | Evidence capture bound to task and candidate (H, Phase C #4) | PARTIALLY_IMPLEMENTED | `validate_evidence`, `ledger.append_event`; `TaskStore.record_evidence` at `e1c66ee` | H | L | L | TaskStore evidence + AcceptanceGate | ledger | evidence for another task/candidate not usable; duplicate ID rejected | P0 | Use TaskStore evidence; link evidence to criteria via `test_ids` |
| C-05 | Acceptance gate on stored evidence (H, Phase C #5) | PARTIALLY_IMPLEMENTED | `evaluate_gate`, `validate_closure` take caller maps | H | L | L | AcceptanceGate | C-04 | closure denied for NOT_RUN gate, failed check, wrong candidate | P0 | Build now (RT-03) |
| C-06 | Single coordinator; plan→execute→verify→close loop (B, MIID §9) | MISSING | no orchestrator | H | M | M | BrainOrchestrator | C-01..05 | second writer handle refused; happy path closes only with linked evidence; failure path never closes | P0 | Build now (RT-04) |
| C-07 | Error recovery: reconcile before retry, restart continuity (B, E) | PARTIALLY_IMPLEMENTED | `recovery_decision` unit-tested only | H | M | M | ActionGateway + TaskStore restore | C-01, C-02 | after restart an unfinished non-idempotent action blocks new effects until reconciled | P1 | Build now (RT-05) |
| C-08 | Runtime entry point / status (I, layer 11) | MISSING | none | M | L | L | `python -m hg` | C-06 | CLI self-check runs a real task to CLOSED_VERIFIED and a denied task that never executes | P1 | Build now (minimal) |
| C-09 | Retry limit (MAEP-014) in the loop (B) | PARTIALLY_IMPLEMENTED | `retry_decision` unit-tested | M | L | L | BrainOrchestrator | C-06 | fourth attempt on same approach refused | P1 | Build now |
| C-10 | Trust-root anchoring of grants (RT-06) | BLOCKED_BY_DEPENDENCY | owner chose trust root `OAI-GIANG`; no machine-verifiable anchor chosen | H | M | M | authority provider | owner decision on anchor (protected-branch grants file vs signed grants) | grant not from trust root rejected | P1 | BLOCKED: needs owner choice of anchor |
| C-11 | CI + branch protection (RT-07) | PARTIALLY_IMPLEMENTED at `e1c66ee` | CI workflow in place (PR #3); branch protection not configured | M | L | L | `.github/workflows` + repo settings | owner action for branch protection | CI fails on a failing test | P1 | Add the HG suite to CI; branch protection stays an owner action |
| C-12 | Model provider abstraction, offline fallback (layer 4) | MISSING | none | H | M | M | HG Brain | C-06 contracts | provider swap without orchestrator change; offline mode reports UNAVAILABLE honestly | P2 | Next phase; contract after the loop is stable |
| C-13 | Reasoning/planning engine (A, layer 3) | MISSING | none | H | H | H | HG Brain | C-12 | plans validated against task contract before execution | P2 | Next phase. Plans are currently supplied as structured data; no claim of autonomous planning |
| C-14 | Layered memory with provenance and conflict detection (E, layer 7) | MISSING | only the event ledger | H | M | M | Memory & Knowledge | C-01, C-04 | write/read/update/conflict/restore tests | P2 | Next phase; start with stdlib storage, no vector DB until a benchmark justifies it (MIID §11) |
| C-15 | Context management / summarization (E) | MISSING | none | M | M | M | HG Brain + Memory | C-12, C-14 | decisions and constraints survive summarization | P3 | Later |
| C-16 | Research & synthesis with sources (F, layer 8) | PARTIALLY_IMPLEMENTED | `validate_research_record` only | M | M | M | Creativity & Research | C-14 | claims link to known sources; disagreements recorded | P3 | Later |
| C-17 | Creative option generation / design exploration (G) | MISSING | none | M | M | L | Creativity & Research | C-12, C-13 | options scored by explicit rubric, not self-praise | P3 | Later |
| C-18 | Self-evaluation and learning loop → regression tests (H, MIID §12) | MISSING | none | H | M | M | Security & Verification | C-04..07 | recurring failure class becomes a regression test; improvement measured on fixed suite | P2 | Next phase; ledger events from this change are its input data |
| C-19 | Benchmark harness (MIID §15) | MISSING | none | M | M | L | Security & Verification | C-06 | same suite before/after; no invented numbers | P2 | Next phase |
| C-20 | Code-intelligence tools: repo search, diff, test runner adapters (C) | MISSING | none | M | M | M | Tools & Automation | C-03 | adapters through ActionGateway only | P2 | Next phase; same adapter contract as C-03 |
| C-21 | Observability: health, metrics (layer 12) | MISSING | none | L | L | L | cross-cutting | C-06 | status derived from ledger, no secrets | P3 | Partial now (`status`), rest later |
| C-22 | Copying Claude's interface/persona | — | — | — | — | — | — | — | — | — | NOT_JUSTIFIED (MIID §2: HG must not be a Claude clone or wrapper) |
| C-23 | Mandatory Claude/paid API dependency | — | — | — | — | — | — | — | — | — | NOT_JUSTIFIED (MIID §13, ADR-008) |

## 4. What is absorbed from Claude/Claude Code, and how

Only mechanisms observable in Claude Code's own working method, re-implemented as HG contracts (no copying of proprietary code, prompts or interfaces):

| Observed mechanism | Problem it solves | HG mechanism |
|---|---|---|
| Permission check before each tool call, deny by default | unauthorized side effects | ActionGateway re-evaluates `PolicyEvaluator` immediately before each effect; adapters re-check scope |
| Read-only vs. execute modes | accidental writes during inspection | `enforce_execution_mode` at the gateway |
| Task list with explicit status, nothing marked done without verification | false completion | TaskStore state machine; CLOSED_VERIFIED only via AcceptanceGate over stored evidence |
| Tool result distinguishes error, timeout, success | silent failure, blind retry | outcome taxonomy: SUCCEEDED, SUCCEEDED_UNVERIFIED, FAILED, UNKNOWN, DENIED, BLOCKED, TOOL_UNAVAILABLE, INVALID_INPUT |
| Resume work across sessions from transcript | lost state | append-only ledger replay restores task state and pending actions |
| Stop after repeated failure on the same approach | loops | `retry_decision` (MAEP-014) in the orchestrator |

## 5. Gaps and defects found

- G-1: no component owns task state; guard booleans are caller-asserted (R-01, TH-03). Addressed by C-01.
- G-2: `PolicyEvaluator` has no runtime caller; authority is never re-checked at an action boundary. Addressed by C-02.
- G-3: `ledger.append_event` re-reads the whole file per append (O(n²) over a ledger's life). Acceptable at current scale; recorded as a limitation, not changed.
- G-4: conformance catalogue T-006 (MAEP-006) has no test. Addressed by C-06 tests.
- No defects found in `maep/` that required changes for this phase.

## 6. Order of work in this change

Extend RT-01 store (restore, writer claim, plan) → RT-02 gateway → RT-03 gate → RT-04 orchestrator → RT-05 restart → runtime assembly and CLI, each with negative tests through the real objects (no mocks of MAEP). C-10 stays BLOCKED on the owner's anchor choice; branch protection (C-11) was then done by the owner as ruleset `main-maep` (PR #4). C-12 onward are the next phase and are not claimed.

## 7. Results after Phase C (branch `stt/miid-runtime-rt02-rt05`, base `e1c66ee`)

| ID | New status | Evidence |
|---|---|---|
| C-01 | IMPLEMENTED, INTEGRATION_TESTED, ENFORCED on the runtime path (store from PR #3 + restore, writer claim, plan) | `maep/tests/test_task_store.py` (41), `maep/tests/test_task_store_restore.py` (17) |
| C-02 | IMPLEMENTED, INTEGRATION_TESTED, ENFORCED on the runtime path | `hg/tests/test_gateway.py` DeniedEffectTests |
| C-03 | IMPLEMENTED, INTEGRATION_TESTED (real adapters `fs.write`, `fs.read`) | `test_gateway.py` OutcomeTaxonomyTests, ConstructionTests |
| C-04, C-05 | IMPLEMENTED, INTEGRATION_TESTED | `hg/tests/test_acceptance.py` (11); `test_orchestrator.py` NoFalseClosureTests |
| C-06 | IMPLEMENTED, INTEGRATION_TESTED (catalogue T-006 now has tests) | `hg/tests/test_orchestrator.py` (21) |
| C-07 | IMPLEMENTED, INTEGRATION_TESTED | restore tests; gateway and orchestrator restart tests |
| C-08 | IMPLEMENTED, INTEGRATION_TESTED (fresh process) | `hg/tests/test_cli.py` (3) |
| C-09 | IMPLEMENTED, INTEGRATION_TESTED | `test_orchestrator.py` RetryLimitTests |
| C-10 | unchanged: BLOCKED_BY_DEPENDENCY (owner's choice of trust anchor) | — |
| C-11 | Done: CI also runs the HG suite and self-check; `main` ruleset `main-maep` (PR #4, owner-created) requires those jobs | `.github/workflows/maep-tests.yml`, PR #4 |
| C-12 … C-21 | unchanged: MISSING / PARTIALLY_IMPLEMENTED; next phase | — |

Baseline vs. after, same commands:

| Measure | Baseline (`e1c66ee`) | After |
|---|---|---|
| `python -m unittest discover -s maep/tests -v` | 169 OK, exit 0 | 186 OK, exit 0 (41 existing store tests unchanged except the pinned public-API set, extended with the three new methods) |
| `python -m unittest discover -s hg/tests -t . -v` | n/a (no runtime) | 59 OK, exit 0 |
| `python -m unittest discover -s .claude/hooks -p "test_*.py" -v` | 29 OK | 29 OK (unchanged) |
| MAEP primitives with a runtime caller | 0 | TaskStore (all facts and transitions), `PolicyEvaluator.evaluate`, `enforce_execution_mode`, `evaluate_gate`, `validate_closure`, `retry_decision`, `recovery_decision`, `ledger.append_event`/`read_events` |
| Runtime self-check | n/a | `python -m hg selfcheck` → 3/3 scenarios PASS, exit 0 |
| Guard sabotage caught by tests | n/a | 17/17 mutants killed |

These are test counts and pass rates on a fixed suite, not measures of intelligence or general capability (MIID §15).

Next phase, in priority order: RT-06 trust-root anchoring (needs owner choice), then C-12 model-provider contract with an offline mode, C-14 layered memory with provenance, C-18 learning loop fed by the ledgers, C-19 benchmark harness.
