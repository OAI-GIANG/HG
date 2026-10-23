# HG Execution Host — Audit-Only Runtime V1

Status: IMPLEMENTED IN ISOLATED FEATURE BRANCH; APPLICATION-LEVEL TESTS PASS (448 TESTS, 2026-10-24); OS-LEVEL GATES OPEN
Scope: OAI-GIANG/HG. This document does not authorize merge or production deployment.

## Decision record

- D-01: Audit principal has no side-effect capabilities.
- D-02: Termux-first; assess Linux/VM if OS isolation cannot be evidenced.
- D-03: Evidence sink must be in a separate permission domain; physical location remains open.
- D-04: Side-effect execution requires a separate task/scope authorization.
- D-05: EH-01..EH-07 require evidence; no execution privileges while a P0 finding remains open.

These are design choices for this candidate. They are not evidence that OS-level controls exist and do not authorize production deployment.

## Enforcement implemented in this candidate

1. AUDIT_ONLY is an explicit execution mode; unknown modes fail closed.
2. The mode requires the fixed HG_AUDIT principal.
3. The runtime requires an anchored authority provider and rejects fixture grants in this mode.
4. The runtime does not instantiate fs.write or test.run in AUDIT_ONLY.
5. ActionGateway requires an exact allowlist of built-in local read adapter types; a custom adapter cannot gain audit access merely by declaring action=READ.
6. Network URL reads are excluded from AUDIT_ONLY to reduce network/SSRF and remote-side-effect exposure.
7. The common execution-mode guard denies every non-read action in AUDIT_ONLY.
8. Existing READ_ONLY mode is retained for compatibility.

## Trust-root dependency

The current canonical owner-grants manifest on main grants broad capabilities to STT and does not declare HG_AUDIT as a distinct read-only principal. This candidate intentionally does not edit the trust-root manifest. Therefore a production AUDIT_ONLY runtime cannot be considered authorized until an owner-controlled trust-root change grants only minimum read actions/scopes to HG_AUDIT and evidence confirms the resulting canonical state. A missing grant must remain DENY.

## Security boundary limitation

This is an in-process application control. It does not constrain Desktop Commander/RDC, arbitrary shell commands, other Termux processes, Android permissions, or direct filesystem access. Consequently:

- OS_ISOLATION_UNVERIFIED remains open.
- COMPLETE_MEDIATION_UNVERIFIED remains open.
- EH-02 and EH-03 cannot be marked PASS based on these changes alone.
- The feature must not be used to claim that the current RDC session itself has become audit-only.

## Required gates

- EH-01: inventory every tool/API/principal/side effect, including RDC itself.
- EH-02: prove audit principal cannot mutate protected resources from outside and inside HG.
- EH-03: prove shell/process/path/API escape paths are blocked by an OS-enforced boundary.
- EH-04: prove audit principal cannot alter policy, trust root, or enforcement.
- EH-05: run negative tests proving denied operations have no side effects.
- EH-06: preserve versioned fixtures, expected results, observed results, and evidence manifest for reproducibility.
- EH-07: run acceptance in an environment isolated from production.

## Stop / rollback

Do not change main, trust-root grants, RDC configuration, running services, or production as part of this candidate. If a test indicates an unexpected effect or the evidence sink fails, stop and mark the outcome UNKNOWN where an effect may have occurred. Do not retry non-idempotent operations without reconciliation.
## Test evidence

- Targeted regression suite: 55 tests passed, exit code 0.
- Full repository suite: 450 tests passed, exit code 0 using Python 3.14.6 on Android/Termux ARM64.
- Static whitespace check: git diff --check passed.
- Test worktree was isolated at HG-execution-host-audit-only-20261024, based on canonical main commit 37e30b106cb9e0fafb289066befbce2c2b700a4a.
- Tests used temporary test directories and did not target the active HG server or production data.
- Machine-readable evidence and SHA-256 file inventory: evidence/EXECUTION_HOST_AUDIT_ONLY_EVIDENCE_V1.json.

The test results prove the candidate's application-level behavior only. They do not prove operating-system isolation, complete mediation, tamper-resistant evidence storage, or production acceptance.
