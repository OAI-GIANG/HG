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

`runtime.production_config:create_service` is the single production factory (ADR-012). It reads an owner-controlled JSON file named by `HG_RUNTIME_CONFIG` (absolute path, regular non-symlink file owned by the current user, no group/other access, strict JSON, schema `hg-runtime-factory-config-v1` with exactly the keys `schema`, `host` = `127.0.0.1`, `port` (1024-65535), `checkout`, `authority_dir`, `policy_path`, `evidence_dir`, `memory_db`, `idempotency_db`, `receipts_dir`, all paths absolute).

```sh
export HG_RUNTIME_FACTORY='runtime.production_config:create_service'
export HG_RUNTIME_CONFIG="$HOME/.config/hg/runtime-factory.json"
cd "$HOME/HG"
PYTHONPATH=. python3 -u -m runtime.service
```

The factory verifies the configuration and the provisioned trust root, then blocks with `HG_BLOCKED` and exit code `78`, naming every production binding that has no owner-approved implementation yet (`REQUIRED_BINDINGS` in `runtime/production_config.py`). Approved implementations are registered in that module by pull request; configuration cannot select a verifier.

## Current deployment state

- Entry point, production factory and fail-closed tests: implemented.
- Registered production binding: `maep022-record-reader` = `memory.AuthorityEvidenceReader` (non-recursive, read-only authority record path; PR #18).
- Candidate (not registered, owner decision D3): `runtime/session_auth.py` `TokenSessionSource` — owner-issued session record (mode 600) with the SHA-256 of a dedicated bearer token, validity window, explicit capabilities/scopes and a revocation file; supplies request-authenticator, authenticated-context-provider and authenticated-session-resolver. Owner tooling: `python -m runtime.session_auth issue|revoke`. Registering it in `APPROVED_BINDINGS` requires the owner's D3 approval.
- Implemented, not registered (owner decisions D2-a, D4-a): `runtime/owner_approvals.py` — `LocalPolicyApprovalVerifier` (owner approval record, mode 600, binding repository, policy digest/version, root generation/digest and an approval ref the policy itself lists; re-read on every load; owner tooling `python -m runtime.owner_approvals approve-policy`) and `AuthorizedWriteRecordVerifier` (a Memory record is approved only if its `evidence.recorded` authorization_id is exactly one ALLOW decision in the authority ledger for WRITE on that evidence id in this store, same task/candidate/policy version/root generation, written inside the grant window; out-of-band records are not approved). E2E with both real verifiers: `runtime/tests/test_owner_approvals.py`. Limitation: after a store move, records whose writes were authorized for the old store path are not approved on the new path.
- Missing production bindings: policy-source verifier (D2), session resolver, request authenticator and runtime-bound authenticated context (D3), approved Memory record verifier (D4), tool adapters, acceptance provider. Live state is no longer a binding: `compose_service` builds `maep.local_runtime_providers.LocalLiveStateProvider` from the composed candidate, policy and root providers.
- Production composition: `compose_service(config, bindings)` wires LocalRootStore, LocalPolicyProvider, GitCandidateProvider, LocalPrincipalProvider, Trusted* providers over `AuthorityEvidenceReader`, MemoryLedgerProvenanceVerifier, LocalEvidenceSink, SQLiteIdempotencyLedger, LocalReceiptSink, `build_runtime` and `HGHTTPServer`. `create_service` calls it only when every binding is registered. The active policy is verified before any file is written; the Memory database must already be provisioned.
- E2E with fixture owner seams (`runtime/tests/test_production_composition_e2e.py`, provisioning in `runtime/tests/e2e_fixture_factory.py`, test-only): real HTTP + D3 candidate token -> authority -> Memory read ALLOW with durable evidence; wrong/missing/revoked token 401 before authority; unapproved record, changed candidate and rejected policy source block; `python -m runtime.service` start/serve/SIGTERM/restart keeps evidence and Memory integrity.
- N1 (fixed, opt-in per approved policy): an owner-approved policy may carry `applicability_rules` that classify Memory data-plane requests as NOT_REQUIRED. Rules only cover `memory:` resources bound to the configured store, only NOT_REQUIRED; malformed, duplicate or overlapping rules block everything; a task record binding the exact request always wins (so REQUIRED still needs the MAEP-022 gate); record lookup errors never fall back to a rule; Brain refuses to dispatch `memory:` resources. Without rules the previous fail-closed behaviour is unchanged.
  Example rule: `{"rule_id": "memory-data-plane", "actions": ["READ", "WRITE"], "resource_prefix": "memory:", "classification": "NOT_REQUIRED"}`.
- N10 (restore/move): resource/scope matching stays exact and every Memory resource stays bound to the database location (`[store:<path>]`, MAEP-004), so a restore to a new path grants nothing. Owner tool `python -m runtime.memory_rebind`: `restore` (new file only; SQLite integrity, schema and full event chain checked on both sides; restored chain head and counts must equal the backup's; refuses an existing target, manifest or leftover journal/WAL; writes a 600 restore manifest), `propose-policy` (rebinds exact rule resources to the restored store in a new `PROPOSED` document with no approval refs; it loads only after the owner approves it through D2 and sets it ACTIVE), `session-scopes` (rebound grants for a new session issued with `python -m runtime.session_auth issue`). Restoring to the original location after loss needs no rebind. Tests: `runtime/tests/test_memory_rebind.py`.
- Production startup (`HG_RUNTIME_FACTORY=runtime.production_config:create_service`), supervision and deployment: not performed; the factory still blocks on the missing bindings above.

The runtime must remain stopped until the production factory and its trust inputs are explicitly provisioned and verified. Do not bypass the startup guard to make the service appear healthy.
