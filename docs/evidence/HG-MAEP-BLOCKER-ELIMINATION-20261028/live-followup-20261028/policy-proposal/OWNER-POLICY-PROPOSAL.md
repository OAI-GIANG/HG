# HG Runtime Service — Minimal Policy Proposal (NOT ACTIVE)

Task: `HG-MAEP-BLOCKER-ELIMINATION-20261028`
Repository: `OAI-GIANG/HG`
Target: runtime.service factory v2 only; explicitly not the running `hg serve` v1 service.

## Status

`PROPOSED`; not active, not owner-approved, and deliberately contains no ALLOW rules. This deny-all skeleton is safe for schema/digest workflow rehearsal only; it cannot satisfy production readiness.

## Grounded constraints from the current candidate source

- Policy envelope is `{ "policy": {...}, "policy_digest": "sha256:<64 lowercase hex>" }`; digest is SHA-256 of sorted compact UTF-8 JSON for the policy object.
- Policy fields required by `native-authority-v1.schema.json`: `schema_version=hg.policy.v1`, `status=ACTIVE` (only after approval), `version`, `root_generation`, `provenance_verified=true` only after verifier success, `policy_digest`, non-empty unique `approval_evidence_refs`, `grant_ttl_seconds` in 1..300, and `rules`.
- A rule is exact `{action, resource, effect, scope}`. The evaluator matches exact action and resource, requires requested scope subset, explicit `ALLOW`, and gives any matching `DENY` precedence. Missing match fails closed.
- The candidate README describes an optional `applicability_rules` extension for specific Memory data-plane operations; only include if each rule's semantics and need are explicitly understood and verified.
- Current active trust root observed during this inspection is `hg-phone-local-root-20261023`, generation 1, digest `sha256:5c8ee60fc3f09c98f07a240399261efad2dbac5d39ce43487fcaecc999f8ccf4`.
- Current `policy_change_rule_ref` points to a missing file; source does not dereference this field. A-1 selects documentation/label treatment, not root rotation. Therefore this proposal does not change the root or claim that a machine-verified policy-change rule exists.

## Proposed authorization posture

- Default deny; no global wildcards, no implicit action inheritance, no implicit resource inheritance, no non-expiring grants.
- Only approve individual action/resource/scope triples justified by actual runtime routes and the owner's intended use.
- Do not put `PUSH`, `MERGE`, `DEPLOY`, `DELETE`, generic `EXECUTE`, authority mutation, policy activation, or session issuance in an initial runtime API policy unless a separately grounded operational requirement explicitly needs that exact action and scope. Repository collaboration authorization is not automatically a runtime API capability.
- Keep `file_write_roots` physically separate from active production source, release content, authority files, session files, Memory databases, and evidence-ledger directories.
- Use the shortest useful `grant_ttl_seconds`; proposal skeleton uses 30 seconds only as a conservative draft value within source constraints, subject to review against real request latency.
- Bind principal identity and session capabilities to the exact approved resources and scopes; never derive them from a self-claimed client field.
- No active approval record can exist until the final policy content, version, root generation, digest and approval reference have been fixed. Any edit after approval invalidates that approval.

## Remaining inputs before a real policy can be finalized

1. Enumerate production routes/operations that are actually required for runtime.service to serve its intended task lifecycle.
2. Derive exact resource and scope strings from route implementation, acceptance adapters, and existing source contracts; do not guess strings.
3. Confirm the intended principal identity from an existing authoritative identity record or the owner's explicit selection.
4. Decide whether a new Memory SQLite store is empty-of-history by verifying HG backups and the existing `memory.jsonl` migration/export contract. Do not infer that three JSONL events are irrelevant.
5. Only after the exact policy is finalized, compute the canonical digest and use the explicit D2-a owner approval CLI. Never fabricate approval evidence.

## Explicit safety status

This document and its JSON file are proposals, not an authorization decision. They must not be installed as the production active policy, referenced as owner-approved policy, or used to issue production credentials.
