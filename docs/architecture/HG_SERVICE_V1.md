# HG Runtime Service V1 — Operations and verification

Status: implementation candidate; not production-certified until merge and on-device gates pass.

## 1. Boundary

The service is added to the existing OAI-GIANG/HG application. The single runtime assembly remains hg/runtime.py; HTTP requests are dispatched through the real BrainOrchestrator, TaskStore, ActionGateway and evidence/acceptance path. Production startup does not use fixture grants or caller-supplied authority.

The listener is IPv4 loopback only (127.0.0.1). A bearer token is required on every route. Request bodies, Authorization headers, prompt content and provider errors must not be logged. The listener enables SO_REUSEADDR for safe immediate restart after a closed socket enters TIME_WAIT; this does not permit a second active listener on the same address.

Security limitation: this is an application-level boundary. A process running under the same Android UID can generally read a mode-0600 token and access files owned by that UID. Loopback and a token do not establish OS isolation.

## 2. Build a release from one Git commit

Run from a canonical repository checkout and supply the exact source commit as COMMIT:

    python -B -m hg.release build --repo . --commit "$COMMIT" --archive "$OUT/hg-release.tar.gz" --manifest "$OUT/hg-release-manifest.json"
    python -B -m hg.release verify --repo . --archive "$OUT/hg-release.tar.gz" --manifest "$OUT/hg-release-manifest.json"

Repeat the build into another destination and byte-compare the archive files. The release manifest binds repository, commit, tree, archive SHA-256, each path, Git blob ID, mode, byte length and SHA-256, plus a deterministic release ID. Verification compares these facts back to Git; a self-consistent manifest alone is not sufficient.

Extract only into a new empty versioned directory:

    python -B -m hg.release extract --archive "$OUT/hg-release.tar.gz" --destination "$RELEASE_ROOT"
    python -B -m hg.release verify-root --root "$RELEASE_ROOT" --manifest "$OUT/hg-release-manifest.json" --release-id "$RELEASE_ID"

Never extract over a live release. Keep old release directories until post-deploy checks and rollback are complete.

## 3. Configuration and credentials

hg/schemas/runtime-service-config-v1.schema.json documents the exact JSON contract. There is no environment-based fallback or implicit configuration. Config and token paths must be absolute. The config must be a regular file owned by the service UID and not accessible to group/other. The token must be a regular owner-owned ASCII file with exactly mode 0600 and at least 32 printable bytes. The state directory must be owner-owned and private (mode 0700 or stricter).

Use a newly generated service token, not a GitHub credential, gate token, plugin token or pre-existing secret. Create it without printing it, use umask 077, and do not place it in command arguments, source control, JSON reports or shell tracing.

Suggested locations, to create only after a deployment checkpoint and backup plan exist:

- Versioned application: $HOME/hg-releases/<release_id>/
- Service configuration: $HOME/.config/hg/runtime-service.json
- Service token: $HOME/.config/hg/runtime-service.token
- Runtime state: $HOME/.local/share/hg/runtime-service-state/
- Release manifest: $HOME/.config/hg/releases/<release_id>.json

Pre-create the configured state directory with mode 0700 (and verify its owner) before preflight. The service itself will not create state when the trust-root check is failing. Do not reuse a state directory unless its identity, ledger contents and backup/restore plan have been audited. A single-writer flock guard prevents two service processes from mutating the same state directory.

## 4. Read-only preflight and service launch

From the exact release directory, create the config and confirm all paths, modes and IDs. The --check command verifies the token contract, release root and current main-pinned trust root without binding the listener or creating the writer lock:

    cd "$RELEASE_ROOT"
    python -B -m hg serve --config "$HOME/.config/hg/runtime-service.json" --check

Proceed only on PREFLIGHT_PASS. A missing, inaccessible, invalid or revoked owner manifest blocks startup. The canonical source cache is bounded to 300 seconds to remain within GitHub's public REST quota; stale reload failures block instead of falling back to old authority. This is a bounded revocation window, not an instantaneous-revocation claim. The trust root remains maep/authority/owner-grants.json on main; this change does not edit it.

Only the dedicated HG runit service is a candidate for activation. Do not enable two service entries against the same state directory: the second should be refused by the writer lock. Before altering a run script or symlink, record the original file, hash, permissions, runit status and exact rollback command. Do not stop or overwrite unrelated processes.

## 5. HTTP contract

All routes require Authorization: Bearer token and a Host header identifying the loopback listener.

| Method | Route | Behavior |
|---|---|---|
| GET | /v1/health/live | Liveness only; not a readiness assertion |
| GET | /v1/health/ready | 200 only if installed release integrity is VERIFIED and current owner authority is LOADED |
| GET | /v1/integrity | Installed release integrity and release_id |
| GET | /v1/tasks/<task_id> | Read-only task snapshot |
| POST | /v1/tasks | Submit one constrained task through the canonical HG runtime |

POST requires a valid Idempotency-Key, Content-Type application/json, one bounded Content-Length, and a JSON object with exactly task and steps. Only fs.write and fs.read adapters are exposed; paths must be normalized under out/ with exact out/ scope. test.run, url.read, shell, arbitrary adapter names and public binds are disabled at this boundary.

For the initial submission API, the task must declare one mandatory AC-READBACK criterion accepting TEST_RESULT evidence and at least one fs.write step. After the tool completes, the verifier reads every planned file back within the runtime root and compares actual content to planned content. Only the real TaskStore and AcceptanceGate can authorize CLOSED_VERIFIED.

Idempotency:
- First key/body: record STARTED durably before runtime execution.
- Same key and body after a durable response: replay the stored response.
- Same key with another body: 409 idempotency_conflict.
- Ambiguous STARTED request after failure: 409 outcome_in_doubt; never automatically execute the effect again.
- A result that was not verified must not be reported as CLOSED_VERIFIED.

## 6. Deployment, smoke and rollback gates

1. Verify the merged commit is on main; build twice; verify identical archive bytes, Git tree and file manifest.
2. Extract to a new release directory, verify installed bytes against the manifest, then run serve --check.
3. Back up the previous run script, symlink target, config metadata, service status and any state authorized for backup. Never echo tokens or copy state into an unprotected location.
4. Activate only the planned hg-runtime service. Poll readiness with a bounded timeout; require /v1/health/ready to return 200, integrity VERIFIED, exact release ID, trust LOADED and current main commit provenance.
5. Submit a uniquely keyed smoke task writing out/deploy-smoke.txt. Require CLOSED_VERIFIED and independently read the file back. Repeat the same key/body and confirm replay without another ACTION_STARTED; changed payload under the same key must conflict.
6. Restart the service and recheck readiness and the existing task/ledger; no token may appear in logs.
7. Exercise rollback using the recorded previous release/configuration. Verify the previous pointer/config is restored and record the final service status. Do not claim rollback passed unless this exact path has been executed.
8. If preflight, integrity, trust, smoke or rollback fails, do not claim closure. Retain failing artifacts and stop; never clean or overwrite failure state.

## 7. Evidence for closure

Required evidence: PR URL, merge commit and main SHA, green CI for Python 3.13/3.14, two-build archive equality, release verification report, installed release verification, config/token modes (not token contents), trust-root provenance, readiness JSON, smoke result and independent read-back, idempotency receipts, restart result, rollback result, and final working-tree/service status.

A unit test or in-process fixture is not a substitute for running the installed release on Termux. Until all are proven, report BLOCKED_WITH_COMPLETE_EVIDENCE, not CLOSED_VERIFIED.
