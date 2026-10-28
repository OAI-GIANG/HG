# WP4 — Implementation and test

Final status: **IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED (subprocess), CI green — merge BLOCKED (session permission control)**.

## 1. Finding fixed

**F-WP4-1 (P1, correctness/security): crash WAL of a displaced ledger replays into the replacement database on the runtime.service line.**

- Root cause: SQLite pairs `-wal`/`-journal` with a database by file name only. The runtime line opened its ledgers through no path-safe opener at the tip (`2b9a087`). The unmerged first-generation opener (`5e8e652`) bound the path but not the recovery records. After a crash, a restore or an operator swap, committed frames are applied to whatever file is at the path, and `PRAGMA integrity_check` still reports `ok`.
- Reproduction: `maep/tests/test_local_runtime_providers.py::test_crash_wal_of_displaced_ledger_is_not_replayed_into_replacement`. A real subprocess claims a key in `SQLiteIdempotencyLedger`, keeps a second connection open so no checkpoint happens, and exits with `os._exit(0)`. The ledger file is then moved away and replaced with another SQLite file.
  - Opener of `5e8e652`: **FAIL**, `AssertionError: AuthorityError not raised`: the replacement was opened (`logs/failing-first-wal-replay-preport.log`).
  - Opener of `3ec6a2a`: **PASS**: open refused; replacement and WAL byte-identical; replacement holds only its own table (`logs/passing-wal-replay-port.log`).
- Fix: port `maep/sqlite_nofollow.py` from `main` unchanged (blob `c05a6a2119d462f66c10e68146700cbd41cdd51f`, identical to `main@504d1bc`, PR #57), with main's tests (blob `bee8c1f6830a3c3ff1223904bca2a44f56878611`). It adds a per-database `application_id` identity, rewritten on every commit, and admission of WAL/journal records before open only when they name that identity. Unattributable records are refused and left for `adopt_sidecars`.

## 2. Tests adapted (not weakened)

The new opener refuses to open a second database at a path while a live connection in the same process still holds the old inode. Two existing swap tests created their replacement ledger through the opener in exactly that situation:

| Test | Before adaptation | After |
|---|---|---|
| `brain/tests/test_routing_budget.py::…replaced_mid_transaction` | ERROR (`no such table`): the replacement was never created | PASS. Replacement prepared beforehand and swapped in with `os.replace`. Removing both commit-time `_check_binding` calls makes it FAIL (`logs/mutation-routing-budget-commit-binding.log`) |
| `maep/tests/test_local_runtime_providers.py::…replaced_mid_transaction` | PASS, but for the wrong reason (the error came from the refused replacement, not from the commit check) | Same adaptation; asserts unchanged |

No assertion was removed or relaxed.

## 3. Commits and PR

| Item | Value |
|---|---|
| Branch | [`stt/runtime-sqlite-recovery-binding-20261028`](https://github.com/OAI-GIANG/HG/tree/stt/runtime-sqlite-recovery-binding-20261028) from `5e8e652` |
| New commit | [`3ec6a2a`](https://github.com/OAI-GIANG/HG/commit/3ec6a2afb0019e67108f3b2fce61b65dfb4356f0) (4 files: `maep/sqlite_nofollow.py`, `maep/tests/test_sqlite_nofollow.py`, `maep/tests/test_local_runtime_providers.py`, `brain/tests/test_routing_budget.py`) |
| Carried commits | `6754f5b`, `5858047`, `8de974b`, `5e8e652` (CI green earlier) |
| PR | [#61](https://github.com/OAI-GIANG/HG/pull/61) → `stt/maep-v1-20261022` (base `2b9a087`), `mergeable_state=clean` |
| CI | push [40633334387](https://github.com/OAI-GIANG/HG/actions/runs/40633334387) and pull_request [40633365116](https://github.com/OAI-GIANG/HG/actions/runs/40633365116): `unittest (3.13)` success, `unittest (3.14)` success |
| Recovery point | [`recovery/stt-maep-v1-pre-sqlite-port-20261028`](https://github.com/OAI-GIANG/HG/tree/recovery/stt-maep-v1-pre-sqlite-port-20261028) = `2b9a087` |
| Merge | **Not performed.** `PUT …/pulls/61/merge` denied by the session permission classifier ("Merge Without Review"). Not retried through any other tool |

## 4. Test runs (Python 3.13.18, `python3 -B -m unittest …`)

| Suite | `2b9a087` | `3ec6a2a` |
|---|---|---|
| maep (`discover -s maep/tests -t .`) | 284 OK, 1 skip | 318 OK, 1 skip |
| memory | 70 OK | 70 OK |
| brain | 172 OK | 174 OK |
| runtime | 211 OK | 211 OK |
| composition | 1 OK | 1 OK |
| creativity | 12 OK | 12 OK |
| tools | 13 OK | 13 OK |
| **Total / exit** | **763, exit 0** | **799, exit 0** |

The first run on the port branch had 1 error (the brain test above, `logs/test-port-run1-brain-error.log`), fixed as described in section 2. Termux arm64 / Python 3.14.6: NOT_RUN (device offline).

## 5. Hygiene

- `git diff --check`: clean.
- Secret scan of the diff: no matches (the only hits were `import secrets` and `secrets.randbelow` in the opener).
- No unrelated refactor; no change to policy, trust root, grants, `policy_version` or production data.

## 6. Residual risk

- Same-UID processes are not contained (documented in the module). Containing them needs a separate UID owning the database directory.
- `memory/store.py` (Memory DB) does not use this opener. Its integrity relies on its own event chain checks. Whether to extend the binding to the Memory DB is a follow-up design item, not done here.
