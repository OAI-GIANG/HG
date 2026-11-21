# HG UI Stabilization — Test Evidence

Date: 2026-11-18 (Asia/Bangkok)
Repository: OAI-GIANG/HG
Candidate branch: feat/ui-stabilization-main-20261118
Base: main 13a56be75a62a56f2123c755aea97a6d1c9cd79a
Device: OPPO PKC110, Android 17, Termux ARM64, Python 3.14.8, Node 26.12.1

## Full test suites

| Suite | Command | Result |
|---|---|---|
| HG | python3 -W error::ResourceWarning -B -m unittest discover -s hg/tests -t . -v | 1,044 tests, OK, 3 platform skips; 405.885 s |
| MAEP | python3 -B -m unittest discover -s maep/tests -t . -v | 385 tests, OK, 3 platform skips; 11.590 s |
| Claude hooks | python3 -B -m unittest discover -s .claude/hooks -p "test_*.py" -v | 42 tests, OK; 0.818 s |
| Focused UI/chat HTTP | python3 -W error::ResourceWarning -B -m unittest -v hg.tests.test_chat_service hg.tests.test_http_ui_chat | 52 tests, OK; 23.569 s |
| JavaScript syntax | node --check hg/ui/app.js | PASS |
| Patch whitespace | git diff --cached --check | PASS |

Aggregate full-suite result: 1,471 tests passed, 6 platform-dependent skips, 0 failures, 0 errors. HG ran with ResourceWarning promoted to an exception; no ResourceWarning occurred.

The initial hooks discovery command used an invalid package root and did not run tests. The CI workflow's canonical command was then read from .github/workflows/maep-tests.yml and used; the definitive hooks result above is 42/42 PASS.

## Isolated UI DOM integration

A disposable HGHTTPServer instance and a fake local Ollama server were started under a private audit-cache directory. Neither production (port 18766) nor the active Soak5 service (port 18867) was used.

- JSDOM 26.1.0 loaded the actual candidate /ui/ assets from the isolated server.
- Authenticated readiness, model status, notes list, Vietnamese notes search, and tools registry all returned HTTP 200 on the page's own origin.
- Six service requests were recorded; every request carried Authorization.
- The local-model panel correctly displayed CHƯA ĐỦ ĐIỀU KIỆN and listener UNVERIFIED because the fixture had no supervised Ollama service directory. The UI did not upgrade process-level information into listener ownership.
- The XSS sentinel remained plain text; no image element was created.
- Forget Token cleared notes/search/tools data views.
- No /v1/chat request was sent. Fake Ollama received one /api/tags status query and zero chat/inference requests.
- JSDOM console/error report was empty; report result PASS.

This is a JSDOM integration test, not a real Chromium/Playwright browser qualification. The Playwright runner exists at hg/tests/ui_browser_e2e.py, but Python Playwright and Chromium were not installed on this Termux device, so real-browser/CSP execution remains pending.

## Scope and safety

- The UI patch was applied to a new worktree based on current main; the previous dirty UI worktree and the original dirty ~/HG checkout were not modified.
- The hg/service.py rebase conflict was resolved by retaining recover_interrupted=True from current main and adding shared assistant-home wiring for notes.
- All new data endpoints require the service token. The model-status route is read-only and does not run inference.
- No production release pointer, production process, Soak5 process, state ledger, or Android setting was changed.
- This evidence does not establish native Flutter UI source or a native Android/browser test. Flutter source remains absent/unverified.

## Final readiness-contract hardening (follow-up commit)

A final security review found that VERIFIED_PROCESS must never be promoted to service READY. The readiness contract was tightened:

- ChatService.model_status now reports READY only when the model digest is pinned, model check is READY and listener status is VERIFIED_LISTENER.
- The browser UI applies the same exact gate.
- Added a regression test proving VERIFIED_PROCESS alone remains NOT_READY.
- Updated the HTTP status-route fixture/assertion to preserve that distinction.

Verification on the updated candidate:
- Focused chat/UI HTTP suite: 53 tests, OK, ResourceWarning treated as error.
- Isolated JSDOM rerun: PASS; explicit model_not_ready_without_listener_attestation assertion true; one Ollama tags query, zero inference calls.
- Full 1,471-test device suite result above was run on the immediately preceding UI commit; GitHub CI is being rerun for this follow-up commit.
