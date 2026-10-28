# HG Policy V2 — constrained resource templates

## Status

Implemented in a candidate branch only. This is not an active production policy and does not confer permissions. The active phone root remains generation 1; no policy, approval, session, database, or production configuration is created by this feature.

## Compatibility

- Policy v1 keeps its exact action + resource match semantics. A string containing braces in a v1 resource remains a literal string; it is not interpreted as a template.
- Policy v2 is opt-in with schema_version = hg.policy.v2 and match_mode on every rule (EXACT or TEMPLATE). Unknown schema versions, rule keys, placeholders, or template strings fail closed.
- A v2 source must be validated, digest-checked, and approved by D2-a against the exact policy digest, version, active root digest, and generation. Approval does not automatically make a policy safe; the owner must review its granted rules. An optional applicability_rules field uses the exact Memory-data-plane contract in TrustedApplicabilityProvider: rule_id, unique actions, resource_prefix beginning with memory:, and classification=NOT_REQUIRED only.

## Allowed resource templates

Only these templates are recognized; no generic wildcard, glob, regular expression, prefix grant, or arbitrary format fields are supported:

- memory:task/{task_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:task/{task_id}/candidate [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:evidence/{evidence_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:knowledge/{claim_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:knowledge/verify/{claim_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:knowledge/task/{task_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:checkpoint/{task_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:resume/{task_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- memory:events/{task_id} [store:/absolute/path/to/canonical-memory.sqlite3]
- file:{relative_path}

Every Memory resource template must include the exact, literal canonical absolute store path in its [store:...] suffix; the path is not a template field. The suffix must match the actual resource byte-for-byte. This prevents a grant from one database from authorizing an identically named object in another database. Task IDs, evidence IDs, and claim IDs must match the bounded identifier grammar [A-Za-z0-9][A-Za-z0-9._:-]{0,127}. relative_path must be a canonical relative POSIX path: no absolute path, backslash, NUL, empty segment, . or .. segment, or trailing slash. File writes remain additionally constrained by the configured rooted adapter and the request's file: scope prefix.

## Allowed scope templates

Only memory:task:{task_id}: followed by one of these exact suffixes is supported: read, write, transition, evidence:read, evidence:write, knowledge:read, knowledge:write, knowledge:verify, candidate:change, checkpoint:read, checkpoint:write, resume:record, events:read, backup:read, backup:write, restore:read, restore:create.

The {task_id} value is derived from the verified request task_ref, not from an arbitrary caller-provided scope string. Other scope templates are rejected or ignored and cannot grant access.

## Matching rules

- Policy v2 rules, session resource_scopes, and session allowed_scopes must all independently permit the request.
- Exact resource/scope entries continue to work in v2 under match_mode = EXACT.
- A template rule matches only a listed template and only when its rendered resource equals the requested resource under the validated task reference.
- Requested scopes must be a non-empty subset of the rendered grants.
- Any matching DENY rule overrides matching ALLOW rules.
- Authorization evidence continues to bind the exact requested resource, task reference, candidate, root generation/digest, policy version/digest, request digest, and short-lived TTL.

## Intentionally not templated

Database initialization, backup, restore, trust-root mutation, policy mutation, approval issuance, session issuance/revocation, shell/exec, arbitrary repository mutation and deployment remain exact-only or unavailable. Do not add namespace templates for these privileged operations without a separate threat model, contract, tests, and owner-approved policy.

## Required validation

- V1 exact matching remains behaviorally unchanged.
- V2 unknown templates fail closed.
- Cross-task, malformed identifier, path traversal, scope escalation and mismatched exact rules are denied.
- Owner approval of a v2 policy binds its exact canonical digest and active root.
- Production is not deployed until an actual owner-approved active policy, valid principal/session, and verified canonical Memory database exist.
