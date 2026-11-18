# PR #205 L5 fail-closed follow-up — verification and CI diagnosis

Date: 2026-11-18 (+07)
Base: exact PR #77 head 73a45f059d51d91c6063580e1a4a86268d377611
Branch: fix/pr77-l5-partial-scope-20261118

## Change in this follow-up

- The L5 BLOCKED / SHARING_SCAN_INCOMPLETE report now carries the complete sharing observation object, including scope, rather than only flattened counters.
- CLI regression tests no longer assume every runner reaches the same failing syscall. A kernel may block before the holder scan (for example pidfd_getfd/Yama); the test accepts a non-PASS fail-closed state, while requiring ALL_PROCESSES_INSPECTED if and only if L5 reports PASS / LISTENER_OWNED.
- SharingScopeGateTests also asserts that the exact partial/unknown/missing scope is preserved in the structured evidence.

## Focused verification on OPPO PKC110, Android 17, Termux ARM64, Python 3.14.8

Command:
python3 -W error::ResourceWarning -B -m unittest -v hg.tests.test_attest.AttestHappyPathTests.test_cli_reports_json_and_exit_code hg.tests.test_attest.SharingScopeGateTests hg.tests.test_attest.SharingScanTests hg.tests.test_l5_probe.ProbeDecisionTests

Result: 31 tests, OK; zero ResourceWarning.

## Previous GitHub Actions failure diagnosis

On workflow run 44269055085:
- MAEP Python 3.13 and 3.14 each failed one test: test_cli_reports_json_and_exit_code raised KeyError sharing. The first revision assumed the CLI must always reach SHARING_SCAN_INCOMPLETE; that assumption was not portable across kernel/procfs capability policies. The structured report and test contract are corrected in this commit. The workflow must rerun on the new SHA before this is called fixed in CI.
- The l5-capability-gate (real kernel; red = BLOCKED) job failed because the hosted runner cannot completely inspect cross-process /proc/pidfd descriptors. The observed self-test was SELF_TEST_OBSERVATION_INCOMPLETE with UNINSPECTABLE_SAME_UID, UNINSPECTABLE_ROOT, UNINSPECTABLE_OTHER_UID, UNREADABLE_DESCRIPTORS and SCOPE_PARTIAL; target inspection was SHARING_SCAN_INCOMPLETE.
- This is a genuine capability block under the workflow explicit HG_REQUIRE_PROC_TESTS=1 policy, not a test to skip or waive. Do not make CI green by weakening the L5 fail-closed requirement.

## Remaining gates

This PR only closes the partial-scope false-PASS. It does not supply a complete process view on the owner's phone, an L3 provenance-backed trust anchor, nor wire VERIFIED_LISTENER into the live /v1/chat model-call path. Original PR #77 remains HOLD; no merge or deployment is requested.
