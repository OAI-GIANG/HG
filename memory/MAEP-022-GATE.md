# MAEP-022 Capability Overlap & Superiority Gate — Memory candidate

- Gate ID: MAEP-022-HG-MEMORY-CANDIDATE-20261022
- Current policy: MAEP-1.2.0
- Candidate fingerprint: sha256:c623ae9d5a976ae857671691420aa0bb37c6481862b2a607008be7e7c6591132
- Machine-readable gate: MAEP-022-GATE.json
- Resolved evidence: MAEP-022-GATE-EVIDENCE.json
- Validator: maep.core.validate_capability_evolution_decision
- Current gate validation: PASS for this exact uncommitted local candidate.
- Chronology disposition: RETROSPECTIVE_CANDIDATE_REVIEW_NOT_PREAUTHORIZATION.

## Capability inventory

The inspected source contained:
- maep.core with task, authorization, transition, evidence, acceptance, closure, recovery, claims and capability-evolution validators.
- maep.ledger with a JSONL append/read primitive, duplicate-ID checks and corruption rejection.
- Six existing MAEP JSON Schemas for task, authorization, state transition, evidence, acceptance gate and closure.
- Architecture/design contracts that name Memory & Knowledge and BrainOrchestrator, but mark those runtime domains as design-only/not implemented.

The inspected source inventory did not contain an executable Memory/Knowledge runtime, durable knowledge-record versioning/retrieval API, continuity/checkpoint schema or mandatory runtime resume guard.

## Overlap decision

Decision: EXTEND_EXISTING.

There is real overlap with MAEP task/evidence policy and event history. The new package does not replace the MAEP policy engine and does not mirror the same Memory event stream into the separate JSONL ledger. It imports and calls the existing MAEP primitives. SQLite binds Memory's task projection, event stream, evidence, knowledge versions and checkpoints transactionally; this function is not supplied by the existing ledger primitive alone.

The selected extension remains a local adapter only. BrainOrchestrator runtime ownership and trusted providers are documented in INTEGRATION_CONTRACT.md but are not implemented by the inspected repository. Therefore the gate does not claim production integration or whole-HG capability completion.

## Internal critique and trade-offs

- Correctness: reuses MAEP validators; task transitions and acceptance/closure remain guarded; negative tests cover invalid authorization and candidate/evidence mismatch.
- Security: missing or failing trusted policy providers block operations; operation grants are rechecked before persistence; local file permissions are restricted; secret-field screening is deliberately described as incomplete.
- Reliability: state changes and events share SQLite transactions; ordered SHA-256-linked events and checkpoint digests detect tested inconsistencies; online backup and isolated restore are tested.
- Functional coverage: task/evidence/knowledge/checkpoint APIs exist locally, unlike the inspected runtime inventory.
- Compatibility: Python standard library only; exercised on the current Termux target.
- Performance/resource cost: one local database avoids dual-write between separate task/event files, but SQLite serializes writers and the implementation validates the complete event chain during store readiness checks (O(n) per readiness check). No throughput advantage is claimed or benchmarked.
- Maintainability: one API and one store per adapter; no second orchestrator or policy engine. Provider wiring and end-to-end runtime integration remain blockers.

These are internal findings, not independent review. No signature functionality/workflow or independent-review workflow is added.

## MAEP-031 evidence-driven improvement record

This candidate records its basis in:
- ADR-001-SQLITE.md: reuse analysis and storage choice.
- INTEGRATION_CONTRACT.md: authority boundary and required real runtime providers.
- ACCEPTANCE_MATRIX.md: criterion-to-test traceability and explicit limits.
- Candidate-bound evidence records MK-INV-001, MK-CMP-001, MK-IMPACT-001, MK-MEM-TESTS-001 and MK-MAEP-TESTS-001.

## Required chronology qualification

The MAEP-022 gate was identified after the initial local Memory implementation draft had already been written. The current candidate fingerprint and evidence were then bound and validated using the current MAEP-1.2.0 validator. That later evaluation does not prove the gate preceded the first code changes, and it does not retroactively erase this process-ordering deviation.

To preserve governance:
- no commit, push, merge, deployment, production database initialization, migration or runtime rollout was performed;
- this PASS is scoped to the technical capability comparison of the current local candidate;
- full MAEP process closure remains BLOCKED on chronology nonconformance and the absent BrainOrchestrator/runtime binding;
- any change to implementation, schema, tests, product documentation or root README changes the candidate fingerprint and requires gate revalidation.

## Current worktree status — STALE / NOT ACCEPTANCE EVIDENCE

The PASS record and evidence files are preserved as historical artifacts for their original candidate fingerprint. The current HG working tree fingerprint differs, so this historical PASS MUST NOT authorize or certify the current candidate. Re-run the scoped inventory, comparison, impact analysis and regression tests against the current candidate before any new PASS is issued. Do not edit the historical evidence to make its candidate reference match.
