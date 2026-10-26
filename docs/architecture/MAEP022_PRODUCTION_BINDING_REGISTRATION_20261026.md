# MAEP-022 Follow-on Gate — Production Binding Registration

**Decision ID:** `MAEP022-PRODUCTION-BINDING-REGISTRATION-20261026`
**Evidence candidate:** `git:a10d8d2a7c23c64a7a088eeebbc0a88b5e0ec616`
**Policy:** MAEP-1.2.0
**Gate:** PASS for the bounded code-registration change; **not a production deployment approval**.

## Authorization and relation to the earlier gate

The earlier `maep022/fs-write-acceptance-gate-20261026.json` assessed the adapter/read-back implementation at candidate `4fe69e1…` and explicitly excluded its production registration. It remains unchanged as historical evidence for that earlier candidate.

The owner’s 2026-10-26 `NEXT ACTION COMMAND — HG ONLY` explicitly required finishing the D2/D3/D4, Tool Adapter/acceptance and policy-version/restore blockers, and instructed that a production-like E2E use isolated state and that deployment occur only if all gates and rollback are ready. This follow-on records the requested production-factory registration and its evidence. It does not authorize modifying the running `hg serve` release or production data.

## Registered code path

The candidate’s `runtime/production_config.py` registers all entries in `REQUIRED_BINDINGS` using code-owned builders:

- D2: `LocalPolicyApprovalVerifier`
- D3: `TokenSessionSource` for authenticated session, request authentication and runtime context
- D4: `AuthorizedWriteRecordVerifier`
- non-recursive authority record reader: `AuthorityEvidenceReader`
- tool adapter: `RootedFileWriteAdapter` registry, bounded to owner-configured absolute roots
- acceptance: `ReadbackAcceptanceProvider`

Configuration supplies file paths and explicit file-write roots; it cannot inject verifier implementations. Startup still fails closed unless the schema-v2 configuration, trust root, active approved policy, existing Memory database, session record and revocation list are valid. No trust-root, policy-version or ledger migration was performed.

## Verification evidence

The following results were observed on Termux / Python 3.14.6 and are also referenced in `production-binding-registration-gate-20261026.json`:

| Verification | Result |
|---|---|
| Real production factory + HTTP lifecycle, without patched `APPROVED_BINDINGS` | 1 test passed in 13.433 s; file bytes matched; independent read-back PASS; task reached `CLOSED_VERIFIED` |
| Full `runtime/tests` | 160 tests passed in 181.576 s; exit code 0 |
| MAEP | 280 passed; 1 existing skip; exit code 0 |
| Memory / Brain | 70 / 171 passed; exit code 0 |
| Production config / Creativity & Research / Tools & Automation / composition | 12 / 12 / 13 / 1 passed; exit code 0 |
| Existing `main` `hg/tests` comparison at `0ef9d8d…` | 248 tests passed in 36.422 s; exit code 0 |
| CI | PR #38’s Python 3.13 and 3.14 checks are the integration check for the final gate-document/test commit; see GitHub PR status before merging |

## Impact and deployment boundary

The running phone service remains `hg serve`, using `hg-runtime-service-config-v1`, release `f7cfd766…` / source commit `f3dac347…`. The deployed release does not contain `runtime/production_config.py`, `runtime/session_auth.py` or `runtime/acceptance.py`. This change did **not** create or migrate a production factory config, issue a production token/session, modify production Memory, alter the active service or deploy a new runtime.

Before a future `runtime.service` deployment, provision and validate a separate owner-controlled `hg-runtime-factory-config-v2` (mode `0600`; absolute paths; `policy_approval_path`; `file_write_roots`; `session_record`; `session_revocations`), verify the existing trust/policy/Memory inputs, issue the owner-authorized session, prepare a rollback point, and run the deployment preflight. Do not reuse or overwrite the existing `hg serve` config/state. Production rollout remains `NOT_RUN` until those separate prerequisites and post-deploy checks are satisfied.
