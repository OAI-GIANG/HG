# Status Reconciliation 2026-10-28

Task: HG-MAEP-AUTONOMOUS-COMPLETION-20261028 · Work package WP1 (contract) and WP11 (documentation).
Baseline reconciled: `main` at `72a428d25f75341a280fe5580c2e5df30617e28c`, after PR #57.

## Why this file exists

MAEP-024 requires labels to match evidence, and the same state must not have two definitions. A
read-only audit found documents asserting a status that the code and the executed tests had already
left behind. Each row below is a contradiction that existed, the fact that contradicts it, and the
resolution applied. Nothing here changes a rule, a guard or a policy version; the normative content
of MAEP-001..028 is untouched (MAEP-028). Where a claim could not be established, it is left
BLOCKED rather than upgraded.

| # | Contradiction (file:line) | What the code and tests show | Resolution |
|---|---|---|---|
| R-1 | `maep/spec/ACCEPTANCE_CHECKLIST_V1.md` AC-12 "BrainOrchestrator runtime integration — DEFERRED-OUT-OF-SCOPE" | `hg/brain/orchestrator.py` and `hg/runtime.py` exist and are exercised by 59 tests in `hg/tests/test_orchestrator.py`; `python -m hg selfcheck` runs in CI | AC-12 restated as PASS-INTEGRATION (in-process) with the tests named |
| R-2 | Same file AC-16 "guards are still caller-supplied until a task-state owner exists" | `maep/task_store.py` is that owner (AC-19) and derives guards from stored facts | AC-16 restated; spec/code parity now pinned by `StateTableParityTests` |
| R-3 | Same file AC-17 "BLOCKED_FOR_TRUST_INTEGRATION … no trust root exists" | RT-06 is implemented (`maep/authority/canonical_source.py`, `anchored.py`) and AC-24 records PASS-LIVE | AC-17 restated; the *identity* half (principal is an unauthenticated string, T-1) still recorded as residual |
| R-4 | Same file AC-18 "machine-verifiable trust anchor (RT-06) remains BLOCKED" — while AC-24 on the following lines said PASS-LIVE | The anchor is implemented and read on the runtime path | AC-18 restated; internal inconsistency removed |
| R-5 | `maep/README.md` "runtime integration remains deferred" and "not yet demonstrated by end-to-end tests" | RT-02..RT-07 and MIID Phase D are INTEGRATION_TESTED in-process | Status and limits rewritten to the current state, with the residual in-process containment limit stated |
| R-6 | `maep/spec/MAEP_OWNER_DELEGATION_V1.md` "Enforcement: DESIGN — nothing in this file is ENFORCED until a runtime exists" and Q-5 "anchoring remains BLOCKED" | RT-06 reads the grant on every runtime decision; the gateway mints permits | §7 rewritten as PARTIAL, naming what is enforced and what is still only guidance |
| R-7 | Same file condition 6 "takes effect immediately" | `canonical_source.py` caches `main` for at most 300 s by default | Condition 6 restated: a bounded revocation window, not instantaneous |
| R-8 | `docs/architecture/RUNTIME_ENFORCEMENT_PLAN_V1.md` status line "RT-06 BLOCKED" while §6 of the same file said ENFORCED | RT-06 is implemented and tested | Status line corrected; §1/§2 kept as dated history with an amendment note (MAEP-015: corrections append, they do not erase) |
| R-9 | Same file §3.4 "If audit capture is mandatory and the append fails, the action is held (fail closed)" | Pre-effect append failure does abort the effect; a post-effect append failure cannot un-write the effect and leaves the action pending with `UNKNOWN` | §3.4 restated to the ordering the code actually guarantees |
| R-10 | `maep/spec/MAEP_CONFORMANCE_TEST_CATALOGUE_V1.md` "NOT RUN … trust-root-anchored grants (RT-06)" | T-046..T-050 run in CI | Bullet corrected; rows T-056..T-059 added for the tests introduced on 2026-10-28 |
| R-11 | `CLAUDE.md` "Proposed: a test asserting every rule MAEP-001..028 is mapped in the catalogue" | `maep/tests/test_conformance_catalogue.py` now enforces rule coverage and anchor resolution | Moved from Proposed to Done in `CLAUDE.md` |

## Not reconciled here (left honest, not upgraded)

| Item | Status | Why |
|---|---|---|
| `maep/spec/ACCEPTANCE_CHECKLIST_V1.md` AC-14 independent review | NOT_PERFORMED-BY-DIRECTIVE | A different party must perform it; an agent cannot supply it (MAEP-021) |
| Principal identity (T-1) | OPEN | Any holder of the service token acts as the manifest principal `STT`. Closing it needs an authenticated identity source, which is an owner decision about the trust root |
| `maep/core.py` primitives that still take a caller boolean (`validate_policy_change`, `validate_review_label`, `validate_closure` for non-CLOSED_VERIFIED, `transition` guards) | OPEN, documented | They are primitives whose authority comes from the caller; the runtime path does not accept booleans (TaskStore derives them). Making the primitives self-authorizing is a contract change that needs a policy version and owner approval (MAEP-017, 028) |
| Production deployment | BLOCKED | No reachable deployment target from this environment; see the task report |
| Android/Termux runtime of the SQLite opener introduced by PR #57 | NOT_RUN | Only Linux CI runners were available; documented in the PR |

## How to re-check this file

Each row names a file and a symbol. `python -m unittest discover -s maep/tests -v` and
`python -m unittest discover -s hg/tests -t . -v` reproduce the test evidence;
`StateTableParityTests` fails if the state table and `maep/core.py` drift apart again, and
`ConformanceCatalogueTests` fails if a catalogue row names a test that no longer exists.
