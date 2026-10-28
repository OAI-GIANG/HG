# WP5 — Production readiness and cutover

Final status: **BLOCKED_PRODUCTION_CUTOVER**. No cutover, deployment, restart or rollback was performed. The production service was not touched.

## Gate evaluation

| Gate | Status | Evidence / reason |
|---|---|---|
| G0 Canonical source and candidate provenance | **PASS** (source) | WP2 §5: `3ec6a2a`, tree `498b300a…`, reproducible archive `b1d551a0…6048`, 196/196 files verified |
| G1 Working-tree / user-data preservation | **UNVERIFIED** | Phone offline. Nothing on the phone was touched (trivially preserved), but its state cannot be confirmed |
| G2 Required tests and regression | **PASS (partial)** | 799/799 on Py 3.13 locally; CI 3.13/3.14 green. Termux arm64 NOT_RUN |
| G3 Authority root, policy, policy-change references | **FAIL / BLOCKED** | No approved ACTIVE runtime.service policy (O-1, O-2); `policy_change_rule_ref` dangling (A-1); phone records unreadable |
| G4 Every binding implemented and approved | **PASS (code)**, merge pending | 8/8 registered at the runtime tip; PR #61 (SQLite) not merged |
| G5 Config schema, ownership, permissions | **BLOCKED** | `runtime-factory.json` (v2) not provisioned (O-5); phone offline |
| G6 Security review and authentication | **PARTIAL** | D3 and HTTP auth tests pass; review by the same agent only; no independent review |
| G7 Artifact and manifest hashes verified independently | **PASS** (source artifact) | WP2 §5. A runtime checkout on the phone does not exist yet |
| G8 Rollback target and procedure executable | **UNVERIFIED** | Rollback = keep `hg serve` (`f7cfd766…`) running and stop runtime.service. Live state of `hg serve` and its backups is unverified |
| G9 Health and acceptance criteria defined | **PASS** (defined) | `/health` LIVE; `/health/ready` 200 only with `release: VERIFIED, trust: LOADED`; authenticated task read; `CLOSED_VERIFIED` lifecycle as in the factory E2E |
| G10 Deployment authorization and operational permission | **BLOCKED** | Phone unreachable; merge to the runtime line refused by the session control; runtime.service replacing `hg serve` affects the real user and needs the owner's confirmation (CLAUDE.md, irreversible-impact rule) |

Since G1, G3, G5, G8 and G10 are not PASS, cutover must not start.

## Cutover plan (for when the gates pass)

1. Phone back online; re-verify `hg-runtime` (PID, release, READY) read-only.
2. Owner provisions O-1…O-5; decide A-1.
3. Clean checkout at the merged runtime commit in a new directory (not `~/HG`); verify its `GitCandidateProvider` digest.
4. Run all suites on Termux at that checkout.
5. Start `runtime.service` on a separate port and state while `hg serve` keeps running. Check `/health`, `/health/ready`, one authenticated read and one fs.write lifecycle to `CLOSED_VERIFIED`.
6. Only after the owner confirms: switch the runit service. Keep `hg serve` and its release as the rollback target; verify rollback by switching back once.
