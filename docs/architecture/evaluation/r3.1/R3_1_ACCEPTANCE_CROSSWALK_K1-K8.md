# HG Memory Continuity V2 — R3.1 acceptance crosswalk K1–K8

**Recorded:** 2026-11-02T01:20:02+07:00
**Candidate:** `feature/memory-continuity-v2`
**Baseline:** `main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`
**Disposition:** `REMEDIATION_ACCEPTANCE_PASS / INDEPENDENT_RE_REVIEW_PENDING`

| Gate | Owner requirement | R3.1 implementation/evidence | Result |
|---|---|---|---|
| K1 | Prevent false cross-subject conflicts from episodic/event records. | Inherited R3 restriction in `hg/memory/curation.py`; full 789-test suite includes curation regressions. | **PASS (R3 inherited; regression rerun)** |
| K2 | Five Brain terminal episodes: zero false conflicts while exact matches remain visible. | Inherited `BrainEpisodeCurationTests`; covered by full suite. Brain-like 800/10,000 benchmarks emitted zero conflict/near/cross-subject findings. | **PASS (R3 inherited; regression + stress rerun)** |
| K3 | Process-level ledger serialization from empty state with unlocked negative control. | Inherited subprocess/barrier concurrency and negative-control tests in `hg/tests/test_memory.py`; full suite rerun. | **PASS (R3 inherited; regression rerun)** |
| K4 / D-K4 | A retracted/superseded ASK receipt cannot be reused; a new ASK receipt and fresh confirmation are required. | Notebook binds receipt to immutable subject/content/provenance/principal identity. Exact active retry is idempotent; changed identity is rejected; inactive receipt returns HTTP 409. New principal is server-derived from the configured bearer-token fingerprint; CLI uses Termux UID. Tests prove principal A digest cannot be replayed as B. | **PASS WITH PRINCIPAL SCOPE QUALIFICATION** |
| K5 | MODEL_DERIVED must be an exact excerpt of a real ANSWERED ASK receipt, not caller-authored text. | New writes require exact ASK span/hash proof plus principal-bound v2 confirmation digest. `MemoryStore` verifies it independently. R3 legacy entries remain readable but cannot be newly authored in legacy format. Tests cover forgery, excerpt mismatch and principal drift. | **PASS** |
| K6 | All append-capable paths to the shared memory ledger use one serialization boundary. | Inherited R3 sidecar `fcntl.flock`, reload-before-write, HOME lock and repair lock inventory; full suite rerun. Separate ASK/model/action/evidence journals remain outside this shared-memory-ledger scope. | **PASS WITH SCOPE BOUNDARY** |
| K7 | UI behavior: stale preview, async races, input lock, duplicate submission and text limits. | Shared behavioral controller and app fetch wrapper use a 30-second save timeout. Timeout/network loss/5xx keeps the exact preview as `SAVE_OUTCOME_UNKNOWN`; retry is idempotent. Source-contract test asserts the deadline; 9/9 Node behavior tests and 66 focused Python tests PASS. | **PASS** |
| K8 | Reproducible evidence tied to the exact candidate. | Full suite 789/0/3; focused Python 66/0; Node 9/9; AST/compile 114/114; JS syntax and diff checks PASS; 64-case synthetic VI eval; 800/10,000-record benchmark logs. Package manifest/checksums bind these artifacts to the R3.1 patch. | **PASS** |

## K4 — credential principal scope

The HTTP principal is `owner:service-token-sha256:<hex SHA-256 of the configured bearer token>`, computed by `HGHTTPServer`; the request body cannot assert it. The raw token is not persisted. A token rotation changes the principal and invalidates an earlier preview digest. The CLI uses `owner:termux-uid:<uid>`.

This is a local credential principal, not a separate named human account, federated identity, device-independent identity or multi-user ACL. The system's existing single-owner/same-UID trust boundary remains explicit. No claim beyond that boundary is made.

## K5 — legacy compatibility

Legacy MODEL_DERIVED records without `authorized_principal_id` remain replay-readable under a narrow compatibility path. New MODEL_DERIVED writes require the principal-bound v2 source reference and complete digest verification. Legacy compatibility does not reopen old save identities or permit new legacy-format writes.

## K7 — unknown write outcome

The browser save POST has a 30,000 ms AbortController deadline. A timeout, transport loss or server 5xx after the save POST is treated as ambiguous because the append may have reached durable storage before the response was lost. The client retains the exact receipt/content/digest and makes the outcome clear to the owner. Retrying the same identity returns the existing active record; changed identity is rejected; retracted/superseded receipts return 409. A timeout is never displayed as a confirmed no-write result.

## K8 — evidence index

- `evidence/FULL_SUITE_R3_1.log`
- `evidence/FOCUSED_AND_UI_R3_1.log`
- `evidence/STATIC_CHECKS_R3_1.log`
- `evidence/CURATION_VI_SYNTHETIC_EVAL_R3_1.json`
- `evidence/BENCHMARK_SAME_800_R3_1.json`
- `evidence/BENCHMARK_DISTINCT_800_R3_1.json`
- `evidence/BENCHMARK_BRAIN_800_R3_1.json`
- `evidence/STRESS_BRAIN_10000_R3_1.json`

Three full-suite skips are platform limitations: hardlink creation is unavailable for two tests; root privilege is unavailable for one `chown` test.

## Independent review boundary

No independent reviewer has reviewed this exact R3.1 patch. STT's implementation, internal adversarial examination, tests and reports do not satisfy an independent-review requirement. K1–K8 engineering evidence is recorded, but Integration Review closure remains pending that separate review and owner authorization.
