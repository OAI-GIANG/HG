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
- Missing production bindings: policy-source verifier (D2), session resolver, request authenticator and runtime-bound authenticated context (D3), approved Memory record verifier and a non-recursive MAEP-022 record read path (D4), tool adapters, live-state provider, acceptance provider.
- Service startup to READY, process supervision, network E2E and production deployment: not performed.

The runtime must remain stopped until the production factory and its trust inputs are explicitly provisioned and verified. Do not bypass the startup guard to make the service appear healthy.
