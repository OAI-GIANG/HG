# WP3 — B-003 authority and provider dependencies

Initial status: `BLOCKED`. Final status: **BLOCKED_AUTHORITY**. Software is complete for the eight bindings. The remaining inputs are owner trust material that must not be fabricated, and the phone is offline.

Code references are at candidate `3ec6a2a` (runtime line).

## 1. Binding inventory (VERIFIED against source)

The checkpoint statement "only `maep022-record-reader` is registered" is true at `c3e9494` and **false at the runtime tip**. `REQUIRED_BINDINGS` now has 8 entries; `live-state-provider` is no longer a binding because `compose_service` builds `LocalLiveStateProvider` from the composed providers.

| Binding | Implementation (`runtime/production_config.py` `APPROVED_BINDINGS`) | Config input | Status |
|---|---|---|---|
| `approved-policy-source-verifier` (D2) | `runtime.owner_approvals.LocalPolicyApprovalVerifier` | `policy_approval_path` | IMPLEMENTED, UNIT_TESTED, registered |
| `authenticated-session-resolver` (D3) | `runtime.session_auth.TokenSessionSource` | `session_record`, `session_revocations` | IMPLEMENTED, INTEGRATION_TESTED, registered |
| `request-authenticator` (D3) | `TokenSessionSource.authenticate_request` | same | as above |
| `authenticated-context-provider` (D3) | `TokenSessionSource.authenticated_context` | same | as above |
| `approved-memory-record-verifier` (D4) | `runtime.owner_approvals.AuthorizedWriteRecordVerifier` | `evidence_dir`, `memory_db` | IMPLEMENTED, UNIT_TESTED, registered |
| `maep022-record-reader` | `memory.AuthorityEvidenceReader` | `memory_db` | registered |
| `tool-adapter-registry` | `tools_automation.file_write_adapter.RootedFileWriteAdapter` per root | `file_write_roots` | registered (MAEP-022 gate record PR #35, #38) |
| `acceptance-provider` | `runtime.acceptance.build_acceptance_provider` (read-back) | — | registered |
| (built in compose) live state | `LocalLiveStateProvider` | — | not an owner seam |

All eight are exercised together by `test_registered_production_factory_full_lifecycle_without_fixture_bindings` through the real `create_service()` (ok in this session).

## 2. The "missing files" from the checkpoint

| File (checkpoint) | Referenced by code? | Contract | Finding |
|---|---|---|---|
| `~/.config/hg/runtime-factory.json` | Yes: `HG_RUNTIME_CONFIG` (runtime/README.md) | `hg-runtime-factory-config-v2`: exactly `schema, host, port, checkout, authority_dir, policy_path, policy_approval_path, evidence_dir, memory_db, idempotency_db, receipts_dir, session_record, session_revocations, file_write_roots`; 0600; owner-owned | **Required, missing (per checkpoint).** Paths only, no secret. `file_write_roots` grants write capability, so the owner chooses them. |
| `~/.config/hg/authority/active-policy.json` | **No.** The filename appears nowhere in code, tests or docs on either line | The policy lives at whatever `policy_path` names. It must be `{"policy": {...}, "policy_digest": "sha256:…"}` with `status: ACTIVE`, `version`, `root_generation` = root generation and a non-empty unique `approval_evidence_refs`, and it must be approved by D2-a | The name is not contractual. The substance is required and missing: **no approved ACTIVE policy exists for runtime.service.** Its content (principals, actions, resources, N1 `applicability_rules`, validity) is an owner decision. |
| `~/.config/hg/authority/phase-gates.json` | **No** reference anywhere | none | NOT_APPLICABLE as a runtime dependency. Gate evidence comes from Memory MAEP-022 records via `TrustedGateEvidenceProvider` |
| `~/.config/hg/authority/policy-change-rule.json` | Only as the string `TrustRootRecord.policy_change_rule_ref` | `native_authority.py` checks only that the field is non-empty. No code dereferences it and no spec defines its schema | **Dangling reference** in the active root (checkpoint). It does not block startup today. It does block G3 as worded ("policy-change references validate"). See decision A-1. |

## 3. "owner-bootstrap.json = SOURCE_CREATED_ROOT_NOT_PROVISIONED" vs "active-root.json = ACTIVE"

This is **not a contradiction in code terms**. `LocalOwnerApprovalSource.validate_owner_approval` and `maep/local_bootstrap.py` approve a bootstrap only while the source says `SOURCE_CREATED_ROOT_NOT_PROVISIONED`. Nothing ever rewrites the source after bootstrap: it is the owner's one-time decision record. The ACTIVE state lives in `active-root.json`, written once with `O_EXCL` (`_write_new_atomic`). The two values are expected to differ after a successful bootstrap. This is an INFERENCE from code; the phone files themselves are UNVERIFIED.

Residual: the source keeps approving a bootstrap of the same payload, but `store_active` refuses to overwrite `active-root.json`, so a replay cannot replace the active root.

## 4. Owner inputs required before runtime.service can start

None of these may be created by an agent: they are trust decisions or credentials.

| # | Input | Tool that exists | Why it cannot be inferred |
|---|---|---|---|
| O-1 | Runtime policy document (ACTIVE, bound to the current root generation) | `python -m runtime.memory_rebind propose-policy` produces `PROPOSED` documents only for rebinding | Principals, scopes, actions, N1 rules and expiry are policy semantics (MAEP-017/028) |
| O-2 | D2-a approval record for that exact policy | `python -m runtime.owner_approvals approve-policy --policy … --authority-dir … --approval-file … --approval-ref …` | An approval written by the agent would be a fabricated approval |
| O-3 | Owner session record and revocation file | `python -m runtime.session_auth issue --session-file … --token-file … --revocation-file … --principal … --days … --capability … --resource-scope … --allowed-scope …` / `revoke --revocation-file … --session-id …` | It is a credential for the principal |
| O-4 | Initialized Memory database at the chosen path | No dedicated owner CLI (E2E uses `MemoryStore(...).initialize`) | Its location fixes every Memory resource (N10); its first principal is an owner choice |
| O-5 | `file_write_roots` and the clean release `checkout` path | — | Write capability grant |
| O-6 | Decision A-1 on `policy_change_rule_ref` | — | Changing the root needs a new root generation by the owner |

## 5. Decision request A-1 — policy-change rule reference

Field: `TrustRootRecord.policy_change_rule_ref` in `active-root.json`. Today it names a file that does not exist, and no code reads it.

| Option | Effect | Security | Cost |
|---|---|---|---|
| **A-1a (recommended)** Record the D2-a mechanism as the policy-change rule in a reviewed document in the repository. Keep the ref as a label and mark G3's "policy-change reference" as documented, not resolved | No root change. Policy changes stay governed by the D2-a approval record pinned to the root digest | Same as today | Docs only |
| A-1b Owner writes `policy-change-rule.json`; add a verifier that resolves the ref and pins its digest | Needs a new root generation, because the current ref carries no digest | Stronger: the rule becomes verifiable | Code, tests, owner re-bootstrap |
| A-1c Leave as is | G3 stays FAIL as worded | — | — |

Continue other work while A-1 is pending.

## 6. Acceptance

| Criterion | Result |
|---|---|
| Authority references resolve to real, verifiable records | **FAIL/UNVERIFIED**: `policy_change_rule_ref` dangles (A-1); phone records not readable |
| No contradictory or dangling active policy references | Bootstrap vs root: not contradictory (section 3). Dangling: A-1 |
| Every required binding has a genuine implementation and verification | **PASS** (8/8, section 1) |
| Gates evaluated from evidence, not hard-coded PASS | **PASS** in code: readiness and gates recompute per request; `TrustedGateEvidenceProvider` reads Memory records |
