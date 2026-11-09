# HG Runtime Service V1 — Operations and verification

Status: implementation candidate; not production-certified until merge and on-device gates pass.

## 1. Boundary

The service is added to the existing OAI-GIANG/HG application. The single runtime assembly remains hg/runtime.py; HTTP requests are dispatched through the real BrainOrchestrator, TaskStore, ActionGateway and evidence/acceptance path. Production startup does not use fixture grants or caller-supplied authority.

The listener is IPv4 loopback only (127.0.0.1). A bearer token is required on every route except the four static web UI files (§5). Request bodies, Authorization headers, prompt content and provider errors must not be logged. The listener enables SO_REUSEADDR for safe immediate restart after a closed socket enters TIME_WAIT; this does not permit a second active listener on the same address.

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

### 4.1 Writer admission and read-only views (G1)

- The service holds the `.writer.lock` flock for its whole life and registers a `RuntimeWriterSession` (`maep/admission.py`). Below a directory that contains `.writer.lock`, a writable `TaskStore`, `EventLog`, `MemoryStore` or `IdempotencyStore` is constructed only with that active session; otherwise construction raises. The marker file stays after the service exits, so this also covers an offline state directory.
- This is an application-level capability inside one trusted interpreter. It is not a sandbox: code in the same interpreter, or any process of the same UID writing files directly, is outside it.
- Two consequences of that limit, reproduced in the PR #87 independent review (2026-11-09) and accepted under the v1 same-UID threat model (owner decision Q3), not fixed: (F-02) `RuntimeWriterSession` trusts the descriptor it is given — it does not check that the descriptor names `.writer.lock` or owns its flock, so a same-UID process can open the marker without the flock, build a session and append through the official API while the service runs; (F-03) admission resolves the target path before looking for `.writer.lock`, so a symlinked directory below a marked root lets an append land outside it (the switch precheck rejects symlinks in a state copy; the runtime path guard alone does not). HG therefore claims no global single-writer isolation and no path containment against untrusted path input. Closing either needs session issuance bound to a verified lock descriptor/inode, or descriptor-relative path resolution that rejects symlinked ancestors, with tests — a separate change.
- The switch script (`deploy/termux/switch_service.sh`) takes the same flock on its own descriptor (fd 9 live, fd 8 incoming copy) for the whole stop → backup → precheck → state/run-script swap section and proves ownership through that descriptor before each change (`deploy/termux/state_lock.py verify`, which reads the kernel's per-descriptor lock list in `/proc/self/fdinfo` and never re-takes a lost lock); losing the lock stops the switch before the next change (PR #87 review F-01, A-05). A switch-wide lock (fd 7 on `~/hg-v1-evidence/.switch.lock`) lets only one switch run at a time (A-01).
- Operator reads (`hg status`, `hg health`) and the switch precheck open read-only views (`read_only=True`). They need no session and every write path on them raises.
- Every JSONL append runs under a lock on the ledger inode (thread lock + `flock`) around read → validate → append, so sequence numbers, task event IDs and Memory conflict decisions have one winner across processes. A failed append whose bytes reached the file is "outcome unknown" to the caller; the next append still numbers from the file, never from memory. A ledger another user could write is refused.
- Assistant HOME: config load/save and HOME ledgers take the common HOME lock; a shared hold is never upgraded to exclusive in place (refused at once, no deadlock).
- Not provided: atomicity across stores (JSONL ledgers, the idempotency SQLite store and the filesystem commit separately) and exactly-once effects; an effect interrupted mid-way is `IN_DOUBT` (§5).

### 4.2 State copy precheck

`deploy/termux/switch_service.sh` backs up the stopped state under its writer lock and writes `.hg-state-copy.json` (inventory of every regular file: path, bytes, SHA-256; `assurance: OPERATIONAL_INTEGRITY_UNAUTHENTICATED`). `state_precheck.py` refuses a copy without that attestation, with a missing/extra/modified file or a symlink, or one that overlaps the live state named by `HG_RUNTIME_STATE_DIR`, the service config `state_dir` (`HG_SERVICE_CONFIG`, default `~/.config/hg/runtime-service.json`) or the documented default path; it then loads the copy with read-only views and opens SQLite with `mode=ro` + `quick_check`. The attestation detects accidental change between copy and load; it is not a signature and does not prove where the copy came from. A restored copy's attestation is removed before it becomes live state.

## 5. HTTP contract

Contract revision 2026-10-29 (owner instruction of 2026-10-29: the web UI's Chat must reach this service with valid authentication and get an answer from HG Brain end to end). The revision is additive: every route that existed keeps its behavior. It adds the web UI files and `POST /v1/chat`. It changes no policy, grant or trust root (MAEP-1.1.0, Q4).

Every route requires Authorization: Bearer token and a Host header identifying the loopback listener, with one exception: the four exact request targets of the web UI below, which carry no data and cause no effect, are served without the token so that a browser can open the page. They still require the loopback Host and a loopback client. Any other path, including any other `/ui/...` target or one with a query string, still answers 401 before routing when the token is missing.

| Method | Route | Token | Behavior |
|---|---|---|---|
| GET | /ui/, /ui/index.html, /ui/app.js, /ui/styles.css | not required | The web UI shipped in the release (`hg/ui/`), read once at startup from the verified release root. Headers: `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, same-origin COOP/CORP |
| GET | /v1/health/live | required | Liveness only; not a readiness assertion |
| GET | /v1/health/ready | required | 200 only if installed release integrity is VERIFIED, current owner authority is LOADED and the idempotency store is not UNUSABLE; the body's `idempotency` is USABLE, UNUSABLE or NOT_CONFIGURED |
| GET | /v1/integrity | required | Installed release integrity and release_id |
| GET | /v1/tasks/<task_id> | required | Read-only task snapshot |
| POST | /v1/tasks | required | Submit one constrained task through the canonical HG runtime |
| POST | /v1/chat | required | One message from the owner -> HG Brain model layer -> HG-labelled answer (below) |

The UI calls only its own origin with relative `/v1/...` paths (same address space, so no CORS preflight and no browser local-network permission is involved), keeps the token the owner pastes in the tab's sessionStorage and sends it only in the Authorization header. There is no CORS support: a page from any other origin cannot read responses.

### POST /v1/chat

- Request: Content-Type application/json, one bounded Content-Length, body exactly `{"message": <string>, "general": <boolean>}`. The message is NFC-normalized and trimmed; 1..2000 characters. Anything else: 400 `invalid_request` / `invalid_message`, 415 `content_type`, 413 `body_too_large`, 400 `invalid_json`.
- Precondition: installed release integrity VERIFIED, else 503 `service_not_ready`. Canonical owner authority is not required: a chat answer is not a MAEP action and causes no effect.
- Processing (`hg/chat.py`): the owner's assistant home (`$HG_HOME`, default `~/.local/share/hg/assistant`, never created by the service) is checked; the supervised local model process and the pinned model digest are attested as for `hg ask`; then `hg.assistant.ask.ask()` runs with `hg.brain.providers.ModelRouter` holding exactly one provider, the local Ollama model (Q5: no paid provider is reachable from this route). `general=false` behaves like `hg ask`; `general=true` like `hg ask --general` (a question about the owner's own life is still answered only from notes).
- Response 200: `outcome` (ANSWERED, MEMORY_ONLY or NO_DATA, as `hg ask`), `answer`, `sentences` (each with HG's label NOTE / MODEL / CONFLICT / BADCITE / ABSTAIN), `counts`, `notes` used (content re-read and matched to the receipt's SHA-256), `quarantined`, `note_conflicts`, `provider`, `model`, `model_check`, `listener`, `seconds`, `release`, `display` (what the terminal would show) and `brain`: `router`, `provider_policy`, `model_calls` (event ids of the MODEL_CALL events) and `receipt_event_id` (the ASK receipt). Both kinds of event are appended to `$HG_HOME/asks-YYYY-MM.jsonl`; MODEL_CALL never contains the prompt.
- Errors: 503 `chat_busy` (one chat at a time: the phone runs one model), `assistant_unavailable`, `assistant_busy`, `model_untrusted`, `notes_ledger_damaged`, `chat_unavailable` (no chat service configured); 500 `internal_error` without detail.
- Boundary statement: this route does not run through BrainOrchestrator, TaskStore or ActionGateway and is not ENFORCED by the HG runtime path; model output never triggers an action. Same-UID attackers are out of scope (Q3). The v2 line's `/api/dispatch` (branch `stt/maep-v1-20261022`, frozen by Q2) is not part of this contract.

POST requires a valid Idempotency-Key, Content-Type application/json, one bounded Content-Length, and a JSON object with exactly task and steps.

Transport limits: each socket read times out after 5 s; reading the whole request (request line, headers, body) must finish within 15 s on the monotonic clock, otherwise an incomplete request line/headers is closed without a response and an incomplete body gets 408 (`request_timeout` for silence, `request_deadline_exceeded` for the total). At most 32 connections are served concurrently; beyond that the server answers 503 `server_busy`. These are implementation defaults, not contract values. Only fs.write and fs.read adapters are exposed; paths must be normalized under out/ with exact out/ scope. test.run, url.read, shell, arbitrary adapter names and public binds are disabled at this boundary.

For the initial submission API, the task must declare one mandatory AC-READBACK criterion accepting TEST_RESULT evidence and at least one fs.write step. After the tool completes, the verifier reads every planned file back within the runtime root and compares actual content to planned content. Only the real TaskStore and AcceptanceGate can authorize CLOSED_VERIFIED.

Idempotency (revision 2026-11-02, H1.3.1: additive, except that a POST whose STARTED receipt cannot be recorded now answers 503 `idempotency_unavailable` instead of 500 `internal_error`):
- Receipts live in `http-idempotency.sqlite3` in the state directory, states STARTED, COMPLETE, IN_DOUBT.
- First key/body: record STARTED durably (WAL, `synchronous=FULL`) before runtime execution. If STARTED cannot be recorded with certainty (database locked, store UNUSABLE or closed): 503 `idempotency_unavailable`; nothing is executed.
- Same key and body while the original request is active in this service process: 409 `request_in_progress`; the caller may retry later with the same key and body. No second execution is started.
- Same key and body after a durable response: replay the stored response.
- Same key with another body: 409 `idempotency_conflict`, whatever the receipt state (STARTED active or orphaned, COMPLETE, IN_DOUBT). A different body is never treated as a new request.
- IN_DOUBT, answered 409 `outcome_in_doubt`: a STARTED receipt not owned by an active request in the current service process (after a crash or restart), or a request whose execution or receipt recording failed after STARTED -- any exception, including BaseException such as SystemExit. Such a key is never executed again automatically: the effect may already have happened (the process can die after the side effect and before the COMPLETE receipt is committed) and the store cannot tell. Deciding what happened (task snapshot, action ledger, the file itself) and whether to submit new work under a new key is the owner's reconciliation, not an automatic retry.
- The active-request marker is process-local and is not a lease or a persisted authority claim. On restart, the in-memory marker is absent, so an orphaned durable STARTED receipt fails closed as IN_DOUBT. It is not shared between processes: correctness assumes one service process per state directory (the writer flock) and one store per database in that process.
- Guarantee: the HTTP layer never starts a second execution for a key that already has a receipt. This is not exactly-once delivery: effects (files under out/) are outside the SQLite transaction, so a crash can leave an effect with no COMPLETE receipt; that is exactly the IN_DOUBT case. Nothing here is distributed-safe.
- A request that ends with BaseException records IN_DOUBT (best effort), releases its ownership and lets the exception end the handler thread: no HTTP response is written and the connection is closed. A failure while recording IN_DOUBT never replaces the original exception.
- Store failures: every receipt write is one BEGIN IMMEDIATE transaction, rolled back on any failure. The store becomes UNUSABLE -- no new request (503 `idempotency_unavailable`), readiness 503 with `idempotency: UNUSABLE` -- when the outcome is unknown: rollback failed, a transaction is still or already open, or the failure is not a SQLite OperationalError (database file replaced or unbound, corruption, closed connection, an owned receipt that is no longer STARTED). A transient OperationalError that rolled back cleanly (e.g. `database is locked`) leaves it usable. Receipts are never deleted or rewritten by recovery; durable STARTED receipts answer IN_DOUBT after the restart. Operator action: find the cause (storage, permissions, a replaced file), then restart the service.
- Shutdown: SIGTERM/SIGINT stops accepting connections; `server_close()` then closes the listener, waits for every handler thread and only then closes the store, so a request running at shutdown still records its receipt. Shutdown adds no timeout to a running execution: it is bounded by the request-read deadline plus that execution's own duration (non-daemon handler threads would keep the process alive anyway).
- Durability scope: tests kill the process (`os._exit`) after the side effect; power loss depends on the device honoring fsync and is UNVERIFIED on the phone.
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
