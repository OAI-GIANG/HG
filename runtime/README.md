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

After a production factory has been implemented, reviewed and configured explicitly:

```sh
export HG_RUNTIME_FACTORY='runtime.production_config:create_service'
cd "$HOME/HG"
PYTHONPATH=. python3 -u -m runtime.service
```

`runtime.production_config:create_service` above is an example contract name, **not a currently available module**. Do not set this value until that module exists and its trust/provider bindings have been verified. Without a configured factory, the expected result is `HG_BLOCKED` and exit code `78`.

## Current deployment state

- Entry point and fail-closed tests: implemented locally.
- Production factory module: not present/verified.
- `HG_RUNTIME_FACTORY`: absent at the time of implementation.
- Owner/session verification, policy provenance verification, and all live provider bindings: not demonstrated as a complete production composition.
- Service startup, process supervision, network E2E, and production deployment: not performed.

The runtime must remain stopped until the production factory and its trust inputs are explicitly provisioned and verified. Do not bypass the startup guard to make the service appear healthy.
