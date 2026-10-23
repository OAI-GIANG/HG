# MAEP Policy & Authority V1
Authorization must bind a trusted principal, exact action, resource, scope, conditions, task ID and policy version. A caller-supplied ALLOW value is data, not authority. The trusted policy evaluator must establish the decision from current facts.

Read, write, commit, push, merge, deploy, migration and deletion are distinct actions. Permission for one does not imply another. Missing/unknown authority is DENY for side effects; inability to evaluate a required fact is BLOCKED, never ALLOW.

Policy changes require a new version, rationale, impact assessment, test plan and explicit authorization by the owner/designated policy authority. No task may change policy and use that change to approve itself. Exceptions must be scoped, time-bounded, traceable and have compensating controls.

## Amendment MAEP-1.1.0 (2026-10-23)
The owner, who is the trust root, has issued a standing delegation to STT covering every action class listed above, under recovery-first, irreversibility and owner-only-change conditions. Each class is granted explicitly; the distinct-actions rule above still applies. See `MAEP_OWNER_DELEGATION_V1.md`.
