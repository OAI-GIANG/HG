# MAEP Policy & Authority V1
Authorization must bind a trusted principal, exact action, resource, scope, conditions, task ID and policy version. A caller-supplied ALLOW value is data, not authority. The trusted policy evaluator must establish the decision from current facts.

Read, write, commit, push, merge, deploy, migration and deletion are distinct actions. Permission for one does not imply another. Missing/unknown authority is DENY for side effects; inability to evaluate a required fact is BLOCKED, never ALLOW.

Policy changes require a new version, rationale, impact assessment, test plan and explicit authorization by the owner/designated policy authority. No task may change policy and use that change to approve itself. Exceptions must be scoped, time-bounded, traceable and have compensating controls.
