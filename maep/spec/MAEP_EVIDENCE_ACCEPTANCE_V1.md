# MAEP Evidence & Acceptance V1
Evidence includes ID/type, source reference, exact candidate, collection time, collector, method, result, limitations and optional integrity metadata. A checksum proves equality to a trusted reference, not origin or identity.

Evidence strength labels: E0 assertion only; E1 direct observation; E2 repeatable local check; E3 tests tied to candidate/environment; E4 independent corroboration; E5 end-to-end acceptance. These labels are not automatic approval levels.

Gate states: PASS, FAIL, BLOCKED, NOT_RUN, NOT_APPLICABLE. NOT_APPLICABLE requires documented rationale. Required gates satisfy acceptance only when PASS with linked evidence. CLOSED_VERIFIED requires every mandatory criterion and gate PASS, evidence references resolved, candidate/policy versions matching, no unresolved mandatory blocker, limitations recorded and timestamp present.

Candidate, configuration, policy or material dependency changes trigger impact analysis and invalidate affected results until rechecked. Preserve old results as history.

## MAEP-022 Capability Overlap & Superiority evidence

For every capability-affecting task, the existing task/change plan must link a gate record containing: decision ID; exact candidate and policy version; scope and capability description; inventory evidence and current capability owner(s); overlap classification; comparison evidence references; rationale and limitations; impact/dependency analysis; regression/migration test references; retirement/deprecation plan where applicable; rollback/recovery path; and gate status. Reuse the existing ledger/task record; do not create a separate data store or governance module.

The decision must use one of `EXISTING_REUSE`, `EXTEND_EXISTING`, `CONSOLIDATE_KEEP_SUPERIOR`, `DEPRECATE_OBSOLETE`, `GENUINE_GAP`, `UNKNOWN`. `UNKNOWN` is never an approved state. When overlap exists, evidence must compare correctness, security, reliability, functional completeness, interoperability/compatibility, performance/resource cost, maintainability and operational burden. If no candidate is demonstrably safer and better for the intended scope, preserve existing safe behavior and block pending further evidence. `GENUINE_GAP` is not, by itself, implementation authorization.

The decision's candidate and policy version must match the proposed change. Evidence must be source-backed, current, resolved and specific enough to substantiate the claim; assertion-only superiority does not pass. Required gate statuses other than `PASS` block authorization and acceptance. Any retirement/removal requires explicit scoped authorization, appropriate migration/compatibility checks, passing regression tests and recovery planning; historical evidence and user data must not be deleted to conceal the old implementation.
