# S03 Implementation & Test Report

Date: 2026-11-03 (Asia/Bangkok)
Candidate branch: stt/s03-independent-verification-20261103
Base: e99c83e8d53cb9fd0b1ab22514a942b7d168db8b

## 1. Implementation summary

S03 reuses the existing MAEP task-state owner and G1 writer admission. No new database, task coordinator, authorization engine, runtime service, or external dependency was added.

Implemented candidate files:

| File | Change |
|---|---|
| hg/verification/artifacts.py | Content-addressed raw payload store, SHA-256 verification, bounded size, private files, read-only mode, orphan and interrupted-temp inventory |
| hg/verification/worker.py | Standalone allowlisted deterministic worker for Python syntax and closed SQLite snapshot checks |
| hg/verification/independent.py | Bounded separate-process invocation, pinned worker hash, candidate binding, structured outcomes and Orchestrator adapter |
| hg/verification/bounded.py | Source-linked bounded log excerpt with error context, fallback tail, byte caps and raw evidence preservation |
| hg/brain/orchestrator.py | MAEP-linked artifact recording and verification; supports structured PASS/FAIL/BLOCKED/INCONCLUSIVE/STALE results |
| hg/runtime.py | Wires the artifact store into the existing runtime using the G1 writer session |
| hg/verification/evidence.py | Keeps BLOCKED/INCONCLUSIVE/STALE distinct from FAIL and PASS at the acceptance gate |
| maep/core.py | Validates optional evidence integrity metadata as finite scalar values |
| hg/tests/test_independent_verification.py | Tests payload integrity, restore, bounded windows, worker behavior, negative cases and orchestration |

No production state, service configuration, live release, trust-root grant or production database was changed. No dependency was installed.

## 2. Test outcomes

Baseline on the fetched main commit is recorded in BASELINE-AND-PREFLIGHT.md.

Candidate regression after S03 implementation:

| Suite | Outcome |
|---|---|
| MAEP unit/conformance | 304 tests, OK, 3 skipped |
| HG runtime and integration | 497 tests, OK |
| python -B -m hg selfcheck | PASS; all 3 scenarios |
| python -B -m hg bench | PASS; 10/10 cases; pass/completion/denial/recovery/evidence-backed closure rates all 1.0; unauthorized effects 0; false closures 0 |

The final full-suite run was performed after the last hardening of temporary artifact inventory, invalid custom read-limit rejection and scalar evidence metadata checks.

After a final security review added broken-symlink, namespace-symlink, G1 writer-session admission and SQLite inode-binding checks, the final targeted regression command was:

    python -B -m unittest hg.tests.test_independent_verification hg.tests.test_orchestrator maep.tests.test_core -v

Result: 81 tests, OK. The 497-test full-suite run above preceded these last narrow hardening edits; GitHub CI must run the full suite on the pushed head before merge.

The first GitHub Actions run identified an environment-sensitive test fixture: it relied on the runner default umask to create a private directory and file. The fixture now explicitly creates every parent directory with mode 0700 and the interrupted temporary payload with mode 0600. Re-run under umask 022 on Termux passed all 81 targeted tests. The corrected pushed head must still pass the full GitHub Actions matrix.

Static checks at candidate review:
- git diff --check: PASS.
- Python AST parse of all changed Python modules: PASS.
- Evidence JSON Schema parse: PASS.
- Python tests use -B and the environment sets PYTHONDONTWRITEBYTECODE=1; logs are kept outside the repository.

## 3. Adversarial/negative behavior demonstrated

- Payload SHA mismatch or tampering is rejected.
- An absent, symlinked, oversized, malformed or wrong-owner payload is not accepted as evidence.
- Unreferenced published payloads and interrupted temporary files are listed without deleting them.
- Read-only evidence views refuse writes.
- Candidate SHA mismatch from the independent worker prevents Orchestrator closure.
- Python syntax errors, path traversal and symlink targets are rejected.
- SQLite corruption and WAL/SHM/journal sidecars block snapshot verification.
- SQLite is opened read-only and its bytes remain unchanged in the positive test.
- INCONCLUSIVE worker outcomes map to a BLOCKED gate and cannot create closure.
- Existing three-meaningful-failure retry behavior and recovery tests remain green.

## 4. Boundaries and unresolved limitations

1. Separate process does not equal a sandbox: the worker retains the same Android UID and filesystem privileges. It protects against accidental coupling and in-process Executor claims, not hostile same-UID processes.
2. SHA-256 proves byte equality to the metadata reference, not producer identity or trustworthy origin if both blob and metadata can be rewritten by a privileged actor.
3. Filesystem payload publication and MAEP ledger metadata append are not one atomic transaction. Orphan payloads are discoverable and are never silently removed.
4. SQLite verification requires a closed consistent snapshot; live WAL-backed databases are intentionally rejected.
5. The bounded excerpt helper fulfills the resource-control intent but the HG repository did not contain the authoritative GTEW-1.0 specification. No GTEW-1.0 conformance is claimed.
6. The log excerpt helper does not automatically detect every secret. Redaction remains mandatory before sending excerpts to a model or external destination.
7. Syntax validation proves Python parse/compile only, not semantic or runtime correctness.
8. No production service deployment or on-device live smoke test is claimed.

## 5. Acceptance status

The 20 requirements in HG_S03_INDEPENDENT_VERIFICATION_V1.md are covered by source review and/or executable candidate tests. Runtime deployment and OS-level sandboxing are explicitly outside the claims of this candidate. Merge/CI evidence will be appended after GitHub review.
