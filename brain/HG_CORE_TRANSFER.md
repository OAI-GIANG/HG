# HG Core Transfer — Source of Truth and Capability Boundaries

**Repository:** `OAI-GIANG/HG`

**Scope:** current Termux phone, local development checkout only

**Status:** local modules and tests exist; production binding and full live E2E remain unverified.

## 1. The distilled operating model

HG is one coordinated system, not a collection of independent autonomous branches. `BrainOrchestrator` owns task identity, sequencing, planning, dispatch coordination and result aggregation. MAEP/native authority decides whether an operation is permitted. Memory persists task/knowledge/checkpoint data behind its authorized API. Creativity & Research prepares bounded, source-linked claims. Tools & Automation supplies constrained adapter contracts, not ambient permission. Security & Verification is enforced through authority checks, evidence validation and adversarial/negative tests; package existence alone is not proof of a deployed security service.

The model/reasoner is a proposal engine. It cannot grant authority, mutate policy, write Memory as an unmediated shortcut, mark its own evidence trusted, or execute side effects. A generated plan is `VALIDATED_PLAN_NOT_AUTHORIZED` until the normal execution path separately authorizes the exact action and resource.

## 2. Canonical request-to-effect path

1. Receive a canonical task snapshot and validate schema, policy version, identity and scope.
2. Read the active TrustRoot and validate its record integrity.
3. Resolve an authenticated principal from a trusted session boundary; never infer identity from caller claims alone.
4. Resolve the exact candidate and verify that it is `OAI-GIANG/HG`, has a candidate reference and source-manifest digest, and matches the request.
5. Load an active policy bound to root generation, version, digest and approval-evidence references.
6. Resolve MAEP-022 applicability and its candidate/action/resource-bound evidence through a trusted resolver and provenance validator.
7. When applicability requires it, resolve the gate decision and all mandatory evidence; unknown, stale or missing data blocks.
8. Reserve a durable idempotency key; re-evaluate exact authority immediately before an adapter side effect.
9. Validate adapter scope and result. Treat timeout/ambiguous effect as `UNKNOWN`, not success.
10. Append a durable receipt/evidence record and persist state through Memory's authorized API.
11. Assess acceptance against the task's actual criteria and evidence; only then consider terminal closure.

Every boundary must use injected providers with actual, identified backing sources. A callable stub or a fixture returning `verified: true` is not a production trust boundary.

## 3. Trust-root bootstrap boundary

`maep/local_owner_authority.py` parses and validates a local owner-source file. `maep/local_authority_store.py` provides a single-root local file adapter plus append-only JSONL evidence. `maep/local_bootstrap.py` adds an explicit function that accepts a caller-selected data directory and calls `TrustRootManager.bootstrap`; importing the module does nothing. Bootstrap checks that the owner source is in `SOURCE_CREATED_ROOT_NOT_PROVISIONED`, verifies the exact root payload, records evidence before storing the root, and reads the root back.

The local owner file is only a local owner-controlled source. Ownership and mode `0600` are useful filesystem hygiene, not a separate trust anchor against compromise of the same user account. SHA-256 record/event digests detect inconsistency but do not authenticate an author against an actor able to rewrite both content and digest. The existing source's fixed timestamp must not be misrepresented as a runtime-verified approval time. A root or policy must not be provisioned in production implicitly. The helper is tested only with temporary directories; this handoff did not call it against any production path.

## 4. Persistence principles

- Do not reset, overwrite, or automatically repair an unknown existing store.
- Prefer append-only evidence and explicit readback/integrity verification.
- Reject symlink/non-regular authority files and lax permissions.
- An evidence sink failure must prevent bootstrap; a root must never appear when its required bootstrap evidence failed to persist.
- If an append succeeds but the evidence head update fails, treat state as inconsistent and fail closed; reconcile explicitly rather than silently continuing.
- The local adapters are not tamper-proof against a privileged or same-account attacker.
- Construction/import is inert. Runtime startup and SQLite initialization are separate explicit actions.

## 5. Capability status: what is and is not taught to HG

| Capability | Current local evidence | Not yet proven |
|---|---|---|
| Brain planning | bounded plan contracts and unit tests | model quality, live candidate binding, service E2E |
| Memory & Knowledge | SQLite adapter and isolated tests | current runtime uses it; production migration/recovery |
| Creativity & Research | request/result/source-link contract | live trustworthy source provider and verification |
| Tools & Automation | adapter request/result contracts and Brain-side checks | scoped real adapters, live external effects, reconciliation |
| Native authority | evaluator and root/policy/provider contracts | production owner root, policy, identity and candidate sources |
| Root/evidence storage | local store/sink with restart/readback/tamper tests | resistance to same-user compromise, external/independent trust |
| MAEP applicability/gate | strict providers and test fixtures | production record resolver and provenance source |
| Idempotency/receipt | contracts and test doubles | durable production adapters and crash recovery |
| Unified memory/continuity | explicit SQLite APIs and checkpoint contracts | full runtime adoption and live resume/continuity proof |
| Runtime composition | explicit dependency injection | exact running process is built from this checkout |

## 6. Remaining provider integrations in priority order

1. **Policy source:** immutable/versioned local policy record with owner-controlled update flow, bound to the exact root generation and containing current approval evidence refs. Do not fabricate policy or translate a test fixture to production.
2. **Authenticated principal:** actual authenticated-session provider with identity evidence, revocation and expiry; caller-supplied dictionaries are not identity.
3. **Candidate resolver:** exact local checkout/artifact resolver yielding repository identity, commit/source manifest digest and candidate ref from observed artifacts. Do not treat self-declared names as proof.
4. **Applicability/gate resolver:** resolve authoritative source records and evidence refs from a specific durable ledger/source; the provenance validator must inspect those sources, not return true by default.
5. **Idempotency ledger and receipt sink:** durable local adapters with crash/reopen tests, duplicate-key handling, `UNKNOWN` reconciliation and no overwrites.
6. **Memory runtime providers:** authenticated principal, candidate ref, policy evaluator, live-state and acceptance providers that use canonical task/evidence state.
7. **Context resolver and reasoning provider:** opt-in only; resolver binds context to current candidate/policy with source refs; model endpoint and served artifact must be grounded in current runtime evidence.
8. **Entrypoint/process binding:** produce evidence that CLI/API/service imports these exact modules from this candidate and injects these exact providers. Do not patch/restart the existing service to fake proof.

## 7. Acceptance criteria for “transfer of the essence”

- A new session can read this document and accurately explain canonical ownership and the request-to-effect chain.
- Tests demonstrate exact-payload bootstrap in an isolated directory, readback after adapter recreation, detection of changed root/evidence, failure of evidence append preventing root creation, and no implicit policy/runtime creation.
- Every real provider has explicit provenance, missing-source behavior, expiry/staleness behavior and negative tests.
- Composition can be constructed with local durable adapters but cannot be claimed production-ready merely because fixture injection succeeds.
- End-to-end tests show denial before adapter invocation, candidate/policy drift blocking, duplicate idempotency not repeating effects, and ambiguous outcomes remaining `UNKNOWN`.
- Reports distinguish `IMPLEMENTED`, `TESTED_WITH_FIXTURE`, `INTEGRATED`, and `PRODUCTION_VERIFIED`; never collapse them into one claim.

## 8. Stop/continue rules

Continue building missing source modules and isolated tests when no source exists. Do not stop solely because a provider is missing. But do not create a production trust root/policy, start services, change the running release, or claim an external trust anchor when the evidence does not support it. A missing source is a concrete implementation task; production activation is a different explicit authorization boundary.

## 9. No-claim list

This handoff does not certify AGI/Lv5, autonomous self-improvement, trusted production runtime, authenticated ownership against same-account compromise, deployment, runtime activation, live model quality, repository provenance beyond locally observed git state, or a production release. It records reusable design knowledge and locally testable engineering contracts only.


## 10. Provider-binding implementation update (2026-10-23)

New local source modules added in this work:

- `maep/local_runtime_providers.py`: `GitCandidateProvider`, `LocalPolicyProvider`, `LocalPrincipalProvider`, `SQLiteIdempotencyLedger`, and `LocalReceiptSink`. The receipt ledger uses a locked append and a `prev_digest` chain; it is local integrity, not an external trust anchor.
- `maep/memory_evidence_providers.py`: `MemoryMAEPRecordResolver` reads through the authorized `MemoryStore.get_evidence` API, verifies the matching `evidence.recorded` event and store integrity, and exposes existing Memory records to MAEP-022 resolvers. `MemoryLedgerProvenanceVerifier` requires a separate `verify_approved_memory_record` source verifier and deliberately fails closed when absent.
- `memory/store.py`: `get_evidence(task_id, evidence_id)` is a read-only authorized lookup returning database-owned task/candidate/policy binding. It does not create or migrate the database.
- `brain/tests/test_durable_provider_binding.py`: uses real SQLite idempotency and JSONL receipt adapters with an isolated Brain fixture. It verifies success persistence/reopen, duplicate replay block, conflict block before effect, and timeout remaining `UNKNOWN` after reopen.
- `maep/tests/test_memory_evidence_providers.py`: verifies reading applicability/gate-shaped records from the existing Memory evidence ledger and fail-closed behavior for missing/stale/unapproved sources.

### Binding status

| Path | Status | Boundary |
|---|---|---|
| Candidate observation | `TESTED_WITH_FIXTURE` plus local checkout observation | Local Git state/manifest only; not independent authorship provenance |
| Brain → SQLite idempotency ledger | `INTEGRATED_IN_ISOLATED_TEST` | Not injected into running production runtime |
| Brain → receipt sink | `INTEGRATED_IN_ISOLATED_TEST` | Local append-only hash chain; not protected from same-UID rewrite |
| Memory evidence read API | `IMPLEMENTED_AND_TESTED` | Authorized API and event-chain binding |
| Memory → applicability/gate resolver | `IMPLEMENTED_AND_TESTED_WITH_FIXTURE` | Requires canonical selectors bound to task records |
| Memory record provenance verifier | `IMPLEMENTED_FAIL_CLOSED` | Needs an actual approved-source verifier; fixture is not authority |
| Policy source | `NO_APPROVED_PRODUCTION_SOURCE_FOUND` | No policy record under the inspected `~/.config/hg` path; no policy created |
| Authenticated session/principal | `NO_APPROVED_PRODUCTION_AUTHENTICATOR_FOUND_IN_THIS_CHECKOUT` | HTTP transport requires an injected authenticator and context equality; none is established by this work |
| Runtime entrypoint/process binding | `NOT_VERIFIED` | Existing services/processes were not restarted, patched or reconfigured |

No root or policy was provisioned. Existing production data and service state were not intentionally modified. The new integration tests use temporary directories and test fixtures. A valid Memory event chain establishes local persistence consistency, not who originated an external claim. Production activation requires actual owner-approved policy/session sources and selectors/verifiers connected to current task records; do not replace them with booleans or self-asserted JSON fields.

## 11. Canonical task selectors and remaining trust-source trace (2026-10-23)

`maep.memory_evidence_providers.CanonicalMemoryTaskSelectors` now resolves MAEP-022 applicability and gate references only from the authorized `MemoryStore.get_task()` snapshot. It verifies the task ID, current policy status, database-owned candidate binding, and for gate selection the task's policy version. The task `inputs` list must contain `kind=EVIDENCE` references tagged with exact description tokens `maep022:applicability` or `maep022:gate`; request-provided reference fields are ignored. Ambiguous role references block. Arbitrary evidence-reference-to-task lookup requires an explicit `list_canonical_task_ids()` source and verifies the referenced evidence through `MemoryStore.get_evidence()`; without that index source it fails closed rather than scanning guessed paths or accepting caller task IDs.

A dedicated `MemoryStore.list_tasks(index_scope_task_id, limit, offset)` API has now been implemented. It obtains a distinct `memory:tasks:index:read` authorization, binds the authorization context to an existing canonical task, and enumerates tasks only inside Memory's authorized, read-only API. It verifies schema and global event-chain consistency, task payload/index identity/state/policy binding, unique creation event, and latest lifecycle-event state/version/candidate binding; stale policy, malformed or mismatched event state, invalid pagination, and denied authorization fail closed. `CanonicalMemoryTaskSelectors` now consumes this API through pages when given an index authorization task context, or a separately injected canonical source; it rejects malformed pages, duplicate IDs, stale task entries, missing references and ambiguity. These behaviors are tested with isolated Memory fixtures. The index API is not yet shown to be granted by the production policy or wired into the production runtime.

The runtime trust-source trace remains:

- Policy: `LocalPolicyProvider` enforces root-generation binding, digest, active status, and approval-evidence refs, but requires `verify_policy_source` from an injected approved-source verifier. No active root or policy record was found in the inspected local authority directory; no policy was created.
- Authenticated session: `LocalPrincipalProvider` validates the result of an injected `resolve_authenticated_session` implementation, including principal/session IDs, identity-evidence reference, issue/expiry and revocation fields. `runtime/http_server.py` delegates authentication to a constructor-injected `authenticate_request` and checks context equality with the runtime provider. No concrete owner-approved authenticator/session store was found in this checkout; returned JSON fields or booleans alone do not authenticate a session.
- Approved provenance: `MemoryLedgerProvenanceVerifier` still requires a concrete `verify_approved_memory_record` implementation. Local Memory event-chain integrity proves local consistency only, not who originated the record.
- Runtime composition: `runtime/composition.py::build_runtime` accepts explicit providers and blocks missing dependencies/root/policy. Static source tracing shows the intended injection points, but no evidence establishes that a running entrypoint injects these exact adapters. Read-only process observation found PID 15005 running `python3 -u -m hg.server`, with cwd `/data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676`; its runit service points to that separate release tree, not this `~/HG` checkout. The separate `hg-runtime` run script points to a missing `~/hg/core/runtime/hg_runtime.py`. No live binding to this candidate or its MAEP providers is established. Process was not restarted, patched or reconfigured.

Next implementation dependency is an actual owner-approved policy/session source and an explicit production policy grant for the new Memory task-index API. These can be implemented as new source modules/contracts and isolated tests, but must remain unavailable for production until populated through an explicitly authorized flow. Do not use `memory/MAEP-022-GATE.json` or its historical reconciliation artifact as current authority: its own candidate/policy chronology and scope are historical and do not supply current task-bound evidence.

### 11.1 Explicit trust-source contracts and fail-closed test coverage

Added `maep/trust_source_contracts.py` with explicit interfaces for approved policy provenance, authenticated-session resolution, approved Memory-record provenance, and canonical task-ID indexing. `LocalPolicyProvider`, `LocalPrincipalProvider`, and `MemoryLedgerProvenanceVerifier` now use the common required-source contract. Missing provider implementations are rejected at construction; the contract does not create a fallback, trust root, policy, session, or source verifier. A verifier result is accepted only when it is the literal boolean `True`.

Additional isolated tests cover ambiguous applicability refs and the same evidence ref appearing in multiple canonical tasks; both cases fail closed. Existing Brain tests verify MAEP-022 deny-before-effect (adapter call count zero), conflicting idempotency reservation denial before effect, duplicate replay denial after reopening the durable ledger, and persisted `UNKNOWN` after timeout/reopen. These are fixture-level controls, not production source verification.

The canonical task index API is now implemented and fixture-tested within `MemoryStore`, with a separately authorized index scope and fail-closed binding checks. It is not yet wired into an active production composition or proven to have production policy permission. Policy/session/provenance source interfaces are explicit, but no approved production implementation was found. Runtime entrypoint injection and live source binding remain unverified; production was not touched.


## 12. HTTP task-index integration and regression checkpoint (2026-10-23)

`runtime/http_server.py` now exposes `GET /api/tasks?index_scope_task_id=<task>&limit=<n>&offset=<n>` through the existing protected HTTP boundary and the canonical `MemoryStore.list_tasks()` API. The endpoint rejects absent/blank/duplicate scope, unknown query fields, malformed query syntax, invalid integer pagination, and limits outside 1..500 with HTTP 400; it does not add an alternate task-index implementation or bypass Memory authorization. The authenticated runtime context is checked before the Memory API call. No new authentication or trust default was introduced.

Regression evidence on the current checkout (`HEAD f7f00a75c6a1b1363993c2fb9bc023171f080038`): `runtime/tests/test_http_server.py` passed 29 tests; the combined `maep/tests memory/tests brain/tests runtime/tests creativity_research/tests tools_automation/tests` suite passed **351 tests and 58 subtests**, with one warning. `py_compile` on the touched runtime/provider/store modules passed, and `git diff --check` passed. The HTTP integration test uses an isolated real `MemoryStore`, not production data.

Read-only live health check to `http://127.0.0.1:8787/api/health` returned HTTP 200, `product=HG`, `runtime=READY`, and integrity/provenance self-consistency `ok=true` for separate release commit label `fcc561ae919b64572c5a9b549d5664b7fbfd4676` and manifest `4fcc892b1f95c37143e5e75590afbdbc349c9128d647e831067b9dd6eacd751c`. This is not evidence that the live process imports this checkout: its process/cwd remains the separate `~/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676` release tree. No task-index request was sent to the live service, and no service restart/reconfiguration/deployment was performed.

**Current classification:** task-index endpoint and Memory authorization integration `IMPLEMENTED_AND_TESTED_IN_CHECKOUT`; targeted regression `PASS`; live candidate/runtime binding `NOT_VERIFIED`; overall task remains `PARTIAL_NOT_CLOSED` until the approved production policy/session/provenance sources and actual runtime injection are established through authorized means. This state is not a reason to fabricate a trust source or alter the running release.
