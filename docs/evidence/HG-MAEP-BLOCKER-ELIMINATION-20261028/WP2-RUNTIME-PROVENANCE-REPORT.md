# WP2 — B-002 runtime candidate and provenance

Initial status: `PARTIALLY_VERIFIED`. Final status: **VERIFIED_WITH_LIMITATIONS** for source provenance of the new candidate. Production eligibility is **BLOCKED** by WP3 inputs and the WP4 merge.

## 1. Candidates compared

| Role | Ref | Commit | Bindings registered | Tests (this session, Py 3.13.18) | Verdict |
|---|---|---|---|---|---|
| Active production (`hg serve`) | release `f7cfd766…` | built from `main@f3dac34` (Project record) | n/a (separate `hg-runtime-service-config-v1` path) | not run here | Live identity UNVERIFIED (device offline). Behind `main` by #36, #57, #58 |
| Phone canonical checkout | `~/HG` | `8dda6d4` + 46 dirty (checkpoint) | — | — | UNVERIFIED. Must not be the deployment checkout: `readiness_provider` requires `working_tree_dirty is False` |
| Checkpoint candidate | `stt/production-composition-20261026` | [`c3e9494`](https://github.com/OAI-GIANG/HG/commit/c3e9494f08d00b582b0ba0ccf9469a8a140e2864) | 1 of 8 (`maep022-record-reader`) | 600 OK (1 skip) | **Not eligible**: `create_service()` blocks by design; 57 commits / 26 PRs of fixes missing |
| Runtime line tip | `stt/maep-v1-20261022` | [`2b9a087`](https://github.com/OAI-GIANG/HG/commit/2b9a0872684b6ccec879d30864ebacce662235e2) | 8 of 8 | 763 OK (1 skip) | Superseded: SQLite opener lacks recovery-record binding |
| **New candidate** | [PR #61](https://github.com/OAI-GIANG/HG/pull/61) head | [`3ec6a2a`](https://github.com/OAI-GIANG/HG/commit/3ec6a2afb0019e67108f3b2fce61b65dfb4356f0), tree `498b300a1ebe7c460efde61cd6627475e7eb301e` | 8 of 8 | 799 OK (1 skip); CI 3.13/3.14 green | Source VERIFIED. Not merged (WP4). Not deployable until WP3 inputs exist |

`3ec6a2a` descends directly from `2b9a087`, so a merge of #61 yields exactly tree `498b300a…`.

## 2. Ancestry and change audit (`c3e9494` → `2b9a087`)

All 26 first-parent merges are PRs into the runtime line (#25–#54 except main-only PRs). They include `#26` live-state provider, `#31` N1 applicability rules, `#32` N10 verified restore/rebind, `#33` D2-a/D4-a verifiers, `#35` fs.write adapter and read-back acceptance (MAEP-022 gate record), `#37` D3 registration, `#38` binding-registration gate record, `#39`/`#40` idempotency crash recovery and WP0 API contract, `#44` effect intent persisted before the adapter, `#45` authentication before GET routing, and `#41`–`#54` HTTP contract and error-path tests. Diff: 41 files, +4716/−102.

`2b9a087` → `3ec6a2a`: 5 commits (WP4): `6754f5b`, `5858047`, `8de974b`, `5e8e652` (first-generation SQLite opener, unmerged until now) and `3ec6a2a` (main's opener with recovery-record binding).

## 3. Runtime contract checks (by reading code at `3ec6a2a`, plus tests that ran)

| Area | What the code does | Test evidence in the runs |
|---|---|---|
| Startup | `HG_RUNTIME_FACTORY` must be set explicitly; `HG_RUNTIME_CONFIG` must be an absolute path to a regular, non-symlink, owner-owned, mode ≤0600 file with strict JSON, schema `hg-runtime-factory-config-v2` and exact keys; host must be `127.0.0.1`; port 1024–65535. Any failure exits 78 (`HG_BLOCKED`) | runtime suite (factory fail-closed tests) |
| Trust root | `LocalRootStore.load_active()` from `authority_dir/active-root.json`: regular, non-symlink, 0600, exact fields, integrity digest | maep/runtime suites |
| Policy | `LocalPolicyProvider` + D2-a `LocalPolicyApprovalVerifier`: digest, version, root generation and root digest pinned; `approval_ref` listed in the policy | `runtime/tests/test_owner_approvals.py` |
| Authentication | D3 `TokenSessionSource`: digest compare, revocation, expiry, 0600, no token logging; authentication before routing and before JSON parsing | runtime suite (#45, WP0 tests) |
| Readiness | `/health/ready` is `VERIFIED/LOADED` only if root integrity holds, policy is ACTIVE with verified provenance for the current generation, and the checkout is a clean `OAI-GIANG/HG` git checkout | runtime suite |
| Idempotency | `SQLiteIdempotencyLedger`: reservation ownership, crash recovery to `UNKNOWN`, no automatic replay; now opened via recovery-record-bound SQLite | maep + runtime suites; new WAL test (WP4) |
| Shutdown | SIGINT/SIGTERM → graceful stop; restart keeps state | `test_start_serve_stop_restart_keeps_state_intact` ok |
| Full lifecycle | Real `create_service()` without patched bindings: create → authority → fs.write → read-back → `CLOSED_VERIFIED` | `test_registered_production_factory_full_lifecycle_without_fixture_bindings` ok |

Limit: this is a reading of the code plus the existing tests, done by the same agent. It is not an independent security review. No new P0/P1 defect was found beyond the SQLite item fixed in WP4.

## 4. Deployment constraints found (they affect G5/G8)

1. `GitCandidateProvider` needs a real git checkout whose remote contains `github.com/OAI-GIANG/HG` (case-sensitive) and a clean working tree. A tarball or the dirty `~/HG` cannot be the runtime checkout. Use a separate clean checkout (for example `git worktree add` or `git clone` at the release commit) and point `checkout` at it.
2. Every Memory resource is bound to the database path (N10). The Memory DB location is therefore part of the release decision.
3. The `hg serve` deployment and its state must stay separate. Do not reuse its config or state (runtime/README.md).

## 5. Release artifact (source provenance)

| Item | Value |
|---|---|
| Commit / tree | `3ec6a2afb0019e67108f3b2fce61b65dfb4356f0` / `498b300a1ebe7c460efde61cd6627475e7eb301e` |
| Artifact | `git archive --format=tar --prefix=hg-<commit>/ <commit>` → 1,945,600 bytes |
| SHA-256 | `b1d551a0e75dbf7c2579eb2e8ee9fbdcab1b35d5d45dd72c6c96ae160bae6048`, identical on two independent builds |
| Per-file manifest | `source-manifest-3ec6a2a.tsv` (196 files: mode, git blob, SHA-256, bytes, path) |
| Independent check | Archive listing has no absolute or `..` paths. After extraction, all 196 files match the manifest (0 mismatches), and the file set is equal |
| Provider digest | `GitCandidateProvider.source_manifest_digest` of a clean checkout = `sha256:4e393b38fd80c91a76af4d232cc3a59f1afec64bb7a2d79dbd12568ffcaf0392` (computed with the remote check stubbed to the canonical URL, because the sandbox remote is lowercase) |

Reproduce: `git archive --format=tar --prefix=hg-3ec6a2afb0019e67108f3b2fce61b65dfb4356f0/ 3ec6a2afb0019e67108f3b2fce61b65dfb4356f0 | sha256sum`.

## 6. Acceptance

| Criterion | Result |
|---|---|
| Candidate identity and source provenance established | PASS for `3ec6a2a` |
| Runtime contracts and deployment configuration compatible | Contracts PASS. Deployment config: BLOCKED (owner inputs, WP3) |
| Required tests pass with recorded results | PASS on 3.13 locally and 3.13/3.14 in CI. Termux arm64 NOT_RUN |
| No unresolved P0/P1 defect | No open P0/P1 found. Residual same-UID limit documented (P2, accepted design limit) |
| Release and rollback artifacts independently verifiable | Source artifact PASS. Rollback artifact on the phone UNVERIFIED |
