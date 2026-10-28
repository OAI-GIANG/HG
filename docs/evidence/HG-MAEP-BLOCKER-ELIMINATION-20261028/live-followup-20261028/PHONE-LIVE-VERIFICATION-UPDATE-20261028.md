# HG-MAEP-BLOCKER-ELIMINATION-20261028 — Live Termux Follow-up

**Timestamp:** 2026-10-28, session-local time Asia/Bangkok (+07)
**Scope:** `OAI-GIANG/HG` only
**Status:** `PARTIALLY_COMPLETED`; production cutover remains `BLOCKED_PRODUCTION_CUTOVER`.

## 1. Verified production baseline remains unchanged

- Production checkout: `$HOME/HG`
- Branch: `stt/maep-v1-20261022`
- HEAD: `8dda6d4a5cfb63614ee684e72d03bf9d5eea224b`
- Dirty entries: 46; not edited by this work.
- Running process: PID 8355, `python3 -B -u -m hg serve --config $HOME/.config/hg/runtime-service.json`.
- Production v1 config SHA-256: `d67488209d8d0400bf71022c6c71d3fc0f4abb85bd80291516306ad96bc2b311`.
- Active root file SHA-256: `179ad13b1dd03fa653923f119a24438bea9113d31a188df25d203ce0543fb237`.
- Active trust root: ID `hg-phone-local-root-20261023`, generation 1, record digest `sha256:5c8ee60fc3f09c98f07a240399261efad2dbac5d39ce43487fcaecc999f8ccf4`.
- Authority evidence ledger integrity and head verified PASS. Evidence ledger has one trust-root bootstrap event.
- No production runtime restart, config write, root write, policy write, Memory write or deploy was performed.

## 2. GitHub changes now verified

- PR #61 is **MERGED** into `stt/maep-v1-20261022`; merge commit `ba12ada35800542d2596fa7761926abd6e2586b2`. Its required Python 3.13 and 3.14 checks were PASS.
- PR #63 is **MERGED** into the same runtime branch; merge commit `c7b4051feb533bd8172bc228a7d021b5e7f01da2`. It adds only `runtime/factory_preflight.py` and `runtime/tests/test_factory_preflight.py` (285 lines total). Its required Python 3.13 and 3.14 checks were PASS.
- Remote branch `stt/maep-v1-20261022` was verified at `c7b4051feb533bd8172bc228a7d021b5e7f01da2`.
- Merge is a repository-source change only. The phone production checkout remains at `8dda6d4...`; there was no deploy or local checkout update.

## 3. Termux tests completed during this follow-up

Targeted scripts were run from candidate worktree `$PREFIX/tmp/HG-FACTORY-PREFLIGHT-20261028`, with fixture directories on `PYTHONPATH`. All returned exit code 0:

| Test script | Result |
|---|---:|
| `maep/tests/test_native_authority.py` | 33 passed |
| `maep/tests/test_schema_contracts.py` | 2 passed |
| `runtime/tests/test_local_authority_composition.py` | 3 passed |
| `runtime/tests/test_factory_preflight.py` | 7 passed |
| `runtime/tests/test_owner_approvals.py` | 14 passed |
| `runtime/tests/test_session_auth.py` | 14 passed |
| `runtime/tests/test_memory_rebind.py` | 8 passed |
| **Total of these targeted scripts** | **81 passed** |

`git diff --check` on the candidate was PASS. A first `unittest` module invocation was invalid because these tests import sibling fixture modules by basename; the script-based invocations above are the valid reruns and passed. Previously reported full-suite evidence (799 tests on the candidate) remains prior evidence, not a rerun in this follow-up.

## 4. Minimal v2 config and read-only preflight

An isolated proposal config was created at:

`$PREFIX/tmp/HG-MAEP-POLICY-PROPOSAL-20261028/runtime-factory-proposed.json`

- Mode 0600.
- Host `127.0.0.1`, proposed port 18768; no listener started.
- `authority_dir` correctly points at `$HOME/.config/hg/authority/root` (the directory containing `active-root.json`).
- File-write root, receipts and idempotency paths are isolated under the proposal work directory.
- This is a non-production proposed config, not an active config.

Read-only preflight was run and returned exit code 78, `ready: false`. Results:

- PASS: config, all 8 registered bindings, active trust root generation 1, evidence ledger, file-write root, state directories, verified clean HG candidate.
- NOTICE: dangling `policy_change_rule_ref`; factory code does not dereference it. A-1a was selected to retain root generation 1; this notice is not machine verification of an actual rule.
- BLOCKED: policy approval unavailable, active policy absent, session/revocation source unavailable, Memory SQLite absent.

Preflight JSON: `preflight-candidate.json` in the proposal directory. SHA-256 observed after the corrected authority path: `b96c23803d398c1f00d4c03ee23e0a52cbced854ebfd7cef5a14c0db662d79aa`.

## 5. Policy proposal and A-1

A-1a is recorded as: keep the active trust root generation 1; treat `policy_change_rule_ref` as a governance label under the existing documented D2-a mechanism, not as a machine-verified rule file. Do not fabricate `policy-change-rule.json` or rotate the root.

A deny-all proposal was created under the local proposal directory. Its inner policy object digest is `sha256:a8738c2f1f813b2d115175af20f174a5cdcda20ee2ae6e645ebff485f6e317fc`. The proposal is explicitly `PROPOSED`, has zero ALLOW rules, empty approval references, and `provenance_verified=false`. A focused isolated check verified the digest and proved the production policy provider rejects a non-active/unapproved proposal. It is not an active policy and must never be used as production authority.

A source-derived action matrix was also drafted. Exact production grants cannot be finalized until the required tasks, resource names and scopes are tied to the actual intended runtime operations. Generic wildcard grants are not supported by the evaluator and must not be invented.

## 6. Memory and session findings

- A scoped search of known HG configuration/data/runtime/backup paths did not find an eligible HG runtime.service Memory SQLite source.
- `$HOME/.local/share/hg/runtime-service-state/memory.jsonl` exists, mode 0600, 2,839 bytes, and contains three historical Memory events. Source search found no automatic JSONL-to-SQLite import path. These events are not to be discarded or declared irrelevant without a migration/export decision.
- SQLite backups found in the same broad backup tree are explicitly labelled as the other legacy backend (`HG2_LEGACY_BACKEND_SQLITE_BACKUP_V1` and related revalidation manifests). They are not eligible as HG runtime.service Memory.
- Consequently, no SQLite Memory DB was initialized and no existing history was migrated or overwritten.
- No authoritative production principal/session or revocation file was found. Candidate tests use fixture principals, which are not production identity evidence. No production session/token was issued.

## 7. Closure classification

- B1: `DOCUMENTED_NOT_MACHINE_VERIFIED` per A-1a; actual policy-change rule file remains absent.
- B2 active policy: `BLOCKED_OWNER_ACTION` — exact operations/resources/scopes need final policy, and policy is not active.
- B3 owner approval: `BLOCKED_OWNER_ACTION` — must be issued through D2-a against the finalized policy digest and current root.
- B4 Memory: `BLOCKED_DATA_UNAVAILABLE/OWNER_DECISION` — prior JSONL history exists, but no validated import/restore decision or eligible SQLite source has been established.
- B5 session/revocation: `BLOCKED_OWNER_ACTION` — no authoritative production principal and scope binding found.
- B6 v2 config: `VERIFIED_NON_PRODUCTION_ONLY` — schema/config validation and preflight run; `ready=false`, so not deployable.

The task remains partially completed. No blocker is falsely reported closed, and no production cutover is claimed.
