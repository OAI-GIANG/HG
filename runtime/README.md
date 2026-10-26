# HG Runtime — Standalone Service Entry Point

## Scope

`runtime.service` is the process entry point for the HG runtime already defined by `runtime.composition` and `runtime.http_server`. It is part of the `OAI-GIANG/HG` repository and has no dependency on another repository.

The entry point does not create credentials, owner identity, trust roots, active policy, evidence, Memory databases, idempotency ledgers, or fake providers. Missing or invalid configuration blocks startup with exit code `78`.

## Required configuration contract

Set `HG_RUNTIME_FACTORY` to an explicitly approved Python `module:callable` inside the trusted HG deployment environment. The callable must:

1. Load/verify the already-provisioned local trust root and active policy; it must not bootstrap either at service startup.
2. Bind an authenticated owner/session verifier and a candidate provider that verifies the exact `OAI-GIANG/HG` checkout identity.
3. Bind the trusted MAEP applicability and gate evidence providers, append-only evidence/receipt sinks, and durable idempotency ledger.
4. Bind the Memory principal/candidate providers, live-state provider, acceptance provider, and any approved adapter registry explicitly.
5. Call `runtime.composition.build_runtime(...)` with all required dependencies.
6. Construct and return `runtime.http_server.HGHTTPServer` using an owner-approved `authenticate_request` callback. The HTTP boundary only permits IPv4 loopback (`127.0.0.1`).
7. Never use mock/test providers, implicit trust defaults, or credentials embedded in source code.

The factory module is executable Python code. Only configure a reviewed, owner-approved module; the entry point intentionally does not search for or select a default factory.

## Launch

`runtime.production_config:create_service` is the single production factory (ADR-012). It reads an owner-controlled JSON file named by `HG_RUNTIME_CONFIG` (absolute path, regular non-symlink file owned by the current user, no group/other access, strict JSON, schema `hg-runtime-factory-config-v2` with exactly the keys `schema`, `host` = `127.0.0.1`, `port` (1024-65535), `checkout`, `authority_dir`, `policy_path`, `evidence_dir`, `memory_db`, `idempotency_db`, `receipts_dir`, `session_record`, `session_revocations`, all paths absolute).

```sh
export HG_RUNTIME_FACTORY='runtime.production_config:create_service'
export HG_RUNTIME_CONFIG="$HOME/.config/hg/runtime-factory.json"
cd "$HOME/HG"
PYTHONPATH=. python3 -u -m runtime.service
```

The factory verifies the configuration and the provisioned trust root, then blocks with `HG_BLOCKED` and exit code `78`, naming every production binding that has no owner-approved implementation yet (`REQUIRED_BINDINGS` in `runtime/production_config.py`). Approved implementations are registered in that module by pull request; configuration cannot select a verifier.

## Current deployment state

- Entry point, production factory and fail-closed tests: implemented.
- **All eight production bindings are registered in this code candidate:** `maep022-record-reader` (`memory.AuthorityEvidenceReader`), D2 `LocalPolicyApprovalVerifier`, D3 `TokenSessionSource` (`authenticated-session-resolver`, `request-authenticator`, `authenticated-context-provider`), D4 `AuthorizedWriteRecordVerifier`, the `RootedFileWriteAdapter` registry, and `ReadbackAcceptanceProvider`. The factory uses reviewed code builders; configuration supplies paths only and cannot select permissive verifiers.
- D2/D4 implementation: `runtime/owner_approvals.py` pins policy approval to the provisioned root and policy digest, and approved Memory/write records to policy version, store and provenance. Store relocation still requires verified restore and explicit owner rebind; restore never carries permissions automatically. Unit tests: `runtime/tests/test_owner_approvals.py` and `runtime/tests/test_memory_rebind.py`.
- MAEP-022 tool/acceptance: `tools_automation/file_write_adapter.py` uses request-digest binding, rooted atomic writes, scope/path/symlink checks and independent read-back. `runtime/acceptance.py` rejects missing/FAILED/mismatched evidence and unreconciled UNKNOWN. `POST /api/reconcile` observes live state but never re-executes an effect. Original implementation gate `MAEP022_GATE_RECORD_FS_WRITE_ACCEPTANCE_20261026.md` applies to the adapter/acceptance implementation at its recorded earlier candidate; the follow-on registration addendum records the explicit owner instruction and production-factory verification for this candidate.
- Production composition: `compose_service(config, bindings)` wires LocalRootStore, LocalPolicyProvider, GitCandidateProvider, LocalPrincipalProvider, Trusted* providers over `AuthorityEvidenceReader`, MemoryLedgerProvenanceVerifier, LocalEvidenceSink, SQLiteIdempotencyLedger, LocalReceiptSink, `build_runtime` and `HGHTTPServer`. `create_service` builds all registered bindings and remains fail-closed unless the owner-controlled config, active trust root, approved active policy, provisioned Memory DB, session and revocation files are valid.
- **Full production-factory HTTP E2E:** `runtime/tests/test_tool_acceptance_e2e.py::test_registered_production_factory_full_lifecycle_without_fixture_bindings` writes an isolated schema-v2 config, calls the real `create_service()` without patching `APPROVED_BINDINGS`, provisions policy approval and session only under a temporary directory, then executes create → authority checks → fs.write → independent read-back → `CLOSED_VERIFIED`. The test asserts the actual file bytes and the final PASS read-back gate. Other E2E tests cover revoked/missing/wrong sessions, scope mismatch, restore/rebind, idempotency, UNKNOWN and reconciliation.
- N1 (fixed, opt-in per approved policy): an owner-approved policy may carry `applicability_rules` that classify Memory data-plane requests as NOT_REQUIRED. Rules only cover `memory:` resources bound to the configured store, only NOT_REQUIRED; malformed, duplicate or overlapping rules block everything; a task record binding the exact request always wins (so REQUIRED still needs the MAEP-022 gate); record lookup errors never fall back to a rule; Brain refuses to dispatch `memory:` resources. Without rules the previous fail-closed behaviour is unchanged.
  Example rule: `{"rule_id": "memory-data-plane", "actions": ["READ", "WRITE"], "resource_prefix": "memory:", "classification": "NOT_REQUIRED"}`.
- N10 (restore/move): resource/scope matching stays exact and every Memory resource stays bound to the database location (`[store:<path>]`, MAEP-004), so a restore to a new path grants nothing. Owner tool `python -m runtime.memory_rebind`: `restore` (new file only; SQLite integrity, schema and full event chain checked on both sides; restored chain head and counts must equal the backup's; refuses an existing target, manifest or leftover journal/WAL; writes a 600 restore manifest), `propose-policy` (rebinds exact rule resources to the restored store in a new `PROPOSED` document with no approval refs; it loads only after the owner approves it through D2 and sets it ACTIVE), `session-scopes` (rebound grants for a new session issued with `python -m runtime.session_auth issue`). Restoring to the original location after loss needs no rebind. Tests: `runtime/tests/test_memory_rebind.py`.
- Production startup (`HG_RUNTIME_FACTORY=runtime.production_config:create_service`), supervision and deployment: **not performed**. The currently running `hg serve` release is the separate `hg-runtime-service-config-v1` path at release `f7cfd766…`; it does not contain `runtime/production_config.py`, `runtime/session_auth.py` or the new factory. No production config, token/session, policy approval, Memory DB or state was created/migrated by this change.
- Before deploying `runtime.service`, the owner must provision a separate `hg-runtime-factory-config-v2` file (mode `0600`, absolute paths, explicit `file_write_roots`, policy approval path, session and revocation files), validate the active trust root/policy and Memory state, issue the owner session, and complete the deployment/rollback preflight. Do not rewrite the existing `hg serve` config or reuse its state as factory state.

The existing `hg serve` deployment is unchanged. Do not bypass the factory startup checks or claim `HG_RUNTIME_READY` until this separate runtime has been provisioned and verified. The runtime must remain stopped until the production factory and its trust inputs are explicitly provisioned and verified.

## Interrupted idempotency recovery

The SQLite ledger records process ownership for new reservations. During composition, proven orphan reservations transition to `UNKNOWN` and a durable outbox retries recovery receipts; no adapter is automatically replayed. Legacy reservations without ownership provenance block startup and require reconciliation.
