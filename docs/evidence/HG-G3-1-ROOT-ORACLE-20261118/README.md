# G3-1 — root-owned SQLite directory oracle in CI

Date: 2026-11-18
Repository: OAI-GIANG/HG
Base: main at 13a56be75a62a56f2123c755aea97a6d1c9cd79a

## Gap

The MAEP suite contains one test decorated with skipUnless(euid == 0):

maep.tests.test_sqlite_nofollow.SQLiteNoFollowTests.test_rejects_directory_owned_by_another_user

It creates a directory, changes its owner to UID/GID 54321, then verifies connect_nofollow refuses that directory before creating a database. The ordinary MAEP job runs as the hosted runner user, so this root-only oracle is skipped.

## Proposed CI coverage

The MAEP workflow adds a dedicated root-owned-dir-oracle job with Python 3.13 and 3.14 on ubuntu-latest. It first proves that the selected Python interpreter runs as euid 0 through passwordless sudo, then executes only the root-only test method under that same interpreter.

This does not run the full test suite as root (which would invalidate permission-based tests), does not change production runtime UID, and does not weaken the SQLite owner check.

## Qualification rule

The job only qualifies the root-only ownership-rejection oracle if both matrix legs execute and pass the named test. If the runner cannot provide non-interactive sudo, the job must fail visibly; the test must not be silently skipped or converted to success.

This branch is a CI-coverage proposal until GitHub Actions reports success.
