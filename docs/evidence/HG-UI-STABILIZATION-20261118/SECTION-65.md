## 65. Addendum 2026-11-18 15:31 +07 — web UI stabilization, complete device suites and L5 fail-closed follow-up

**Candidate branch and scope.**
- Current main base: 13a56be75a62a56f2123c755aea97a6d1c9cd79a.
- New branch: feat/ui-stabilization-main-20261118; separate worktree $HOME/.cache/hg-worktrees/hg-ui-stabilization-rebase-20261118.
- Eleven files add authenticated read-only notes list/search, tool registry and local-model status routes/screens; service wiring retains recover_interrupted=True and uses one assistant home for chat and notes.
- The previous UI worktree and original dirty ~/HG checkout were preserved. No production, Soak5, user memory, TaskStore, Android settings or release pointer was changed.

**Verification on OPPO PKC110 / Android 17 / Termux ARM64 / Python 3.14.8 / Node 26.12.1.**
- HG: 1,044 tests, OK (3 environment-dependent skips), 405.885 s, executed with ResourceWarning promoted to error; zero warnings, failures or errors.
- MAEP: 385 tests, OK (3 environment-dependent skips), 11.590 s.
- Claude hooks: 42 tests, OK, 0.818 s (canonical command from CI workflow).
- Focused chat/UI HTTP tests: 52 tests, OK, 23.569 s.
- Aggregate: 1,471 tests passed, 6 platform-dependent skips.
- node --check hg/ui/app.js PASS; git diff --cached --check PASS.

**Isolated DOM integration evidence.**
- A disposable HGHTTPServer + FakeOllama instance used a temporary HOME/state and the candidate's actual UI files. JSDOM 26.1.0 loaded the page.
- Authenticated GET /v1/health/ready, GET /v1/model, GET /v1/notes, POST /v1/notes/search and GET /v1/tools requests all returned HTTP 200; all six recorded requests carried Authorization and stayed on the same origin.
- Model panel accurately reported NOT_READY / listener UNVERIFIED because the fixture had no supervised Ollama service directory. It did not claim VERIFIED_LISTENER.
- XSS sentinel remained text, no IMG DOM node was created; forgetting the token cleared notes/search/tools views.
- Ollama received one /api/tags status request and zero /api/chat inference calls. No /v1/chat request occurred. Console log was empty. UI DOM report PASS.
- This is JSDOM, not a real Chromium/Playwright run. Playwright and Chromium are unavailable on this Termux device; real-browser/CSP qualification remains open.

**Resource-cleanup ledger reconciliation.**
- The previously described resource-cleanup source changes are already present on current main through PR #202 (6f6cb96). All six source/test file blob IDs match commit 98d9edfaa150f35c18d5f9ad2b2965e0ce1bc751. The old CSV statement that no PR/CI existed is stale; corrected here. No duplicate PR was opened.

**L5 security follow-up, separate branch.**
- Branch fix/pr77-l5-partial-scope-20261118 was created from exact PR #77 HEAD 73a45f059d51d91c6063580e1a4a86268d377611 and pushed as commit d34688a0e0e606477473372668f5cb0607523c9d; PR #77 itself was not modified.
- The new helper blocks PARTIAL/UNKNOWN/missing process-sharing scope as SHARING_SCAN_INCOMPLETE; a visible holder remains LISTENER_SHARED. Focused scope/probe tests passed 30/30.
- Broader integration tests on Android are not a pass: 33 failures, 1 error and 5 skips because procfs cannot read the parent process in the lab (L1 PARENT_UNREADABLE / ENOENT). The real Ollama probe still has /proc hidepid=invisible and PARTIAL sharing visibility. L3 trusted_runtimes remains empty and the live model-call path is not gated by VERIFIED_LISTENER.
- This narrow change is not eligible for merge until supported-runner CI and remaining PR #77 conditions are satisfied.

**Operational status at 15:31 +07.**
- Production process tree observed alive: runsv PID 20288, runtime PID 20309, on the original release 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5. Last authenticated readiness check at 15:09 +07 was HTTP 200, READY, integrity VERIFIED, trust LOADED, idempotency USABLE.
- Soak5 staging remains aee6efe4a9204de6aa12ed25be8e73b04a6107f3bb393cbafc417878fe480519. At 15:31:41 +07, tick rows=23, 22 OK, 1 initial quota SKIP, 0 FAIL; latest tick 23 at 15:11:01 +07. A same-boot Termux process-tree restart was recorded at 14:10:33; staging recovered and ticks 21–23 passed. 24h target is 2026-11-19 01:46:30 +07; soak has not completed.
- JobScheduler recurrence remains QUALIFIED, not VERIFIED; one-shot 4212 executed but recurring job 4211 is not independently attributable due Termux:API 0.53 / Android 17 pending-readback issue. Termux Boot/reboot proof remains open.

**Disposition.**
- The web UI candidate is test-green in device suites and isolated JSDOM integration; ready for independent CI/review, not production.
- PR #77/RT-06 remains HOLD/BLOCKED. Native Flutter source/browser E2E, device reboot/autostart, recurring JobScheduler proof and Soak5 24h result remain open.
- Production stays on the old release. No GO-LIVE decision or production deployment is made. Overall system verdict remains INCOMPLETE.
