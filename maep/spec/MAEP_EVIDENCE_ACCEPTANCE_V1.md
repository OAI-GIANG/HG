# MAEP Evidence & Acceptance V1
Evidence includes ID/type, source reference, exact candidate, collection time, collector, method, result, limitations and optional integrity metadata. A checksum proves equality to a trusted reference, not origin or identity.

Evidence strength labels: E0 assertion only; E1 direct observation; E2 repeatable local check; E3 tests tied to candidate/environment; E4 independent corroboration; E5 end-to-end acceptance. These labels are not automatic approval levels.

Gate states: PASS, FAIL, BLOCKED, NOT_RUN, NOT_APPLICABLE. NOT_APPLICABLE requires documented rationale. Required gates satisfy acceptance only when PASS with linked evidence. CLOSED_VERIFIED requires every mandatory criterion and gate PASS, evidence references resolved, candidate/policy versions matching, no unresolved mandatory blocker, limitations recorded and timestamp present.

Candidate, configuration, policy or material dependency changes trigger impact analysis and invalidate affected results until rechecked. Preserve old results as history.
