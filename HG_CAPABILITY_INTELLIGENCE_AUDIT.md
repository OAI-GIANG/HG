# HG Capability & Intelligence Audit — 2026-10-23 (continued)

## 1. Final status

**PARTIAL — candidate test suites pass, but audit closure is blocked by unverified runtime source binding and missing valid staging checkout. Do not claim PASS or production certification.**

Scope: repository `OAI-GIANG/HG` and explicitly authorized Termux checkout only. No HG2 repository access was used. No production service was restarted, stopped, patched, reconfigured, or deployed. No source implementation file was changed by this audit. This report is the requested audit artifact and is newly created in the repository root.

## 2. Repository and state evidence

- Origin: `https://github.com/OAI-GIANG/HG.git`
- Checkout: `/data/data/com.termux/files/home/HG`
- Branch: `stt/maep-v1-20261022`
- HEAD: `f7f00a75c6a1b1363993c2fb9bc023171f080038`
- HEAD remained unchanged after tests.
- Working tree was already dirty at audit start: 18 tracked modified files plus multiple untracked source, test, checkpoint and report paths. The audit did not reset, stash, checkout, clean, delete, or overwrite these changes.
- `git diff --check`: exit 0.
- `HG_CAPABILITY_INTELLIGENCE_AUDIT.md` did not exist before this report was created.

## 3. Runtime source binding — P0 BLOCKER

Read-only process metadata shows:

- PID `15005` is alive.
- Command: `python3 -u -m hg.server`.
- Process working directory: `/data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676`.
- The working directory is outside the authorized `OAI-GIANG/HG` checkout and is not one of the authorized candidate source paths. No files in that directory were read during this continuation.

The existing in-repository checkpoint `HG_RUNTIME_BINDING_RECONCILIATION_20261023.md` records that the active service uses a separate release source root and that the candidate planner's import/call path was not demonstrated. Current evidence is consistent with that finding. A running process and a healthy self-reported health endpoint do not prove it is running the audited Git HEAD.

**Result:** runtime-to-candidate binding = **UNVERIFIED / BLOCKED**. The audit cannot inspect or attest to the live release's source files while maintaining the stated scope. Required evidence must be produced from an explicitly authorized, in-scope staging environment or the scope must be explicitly expanded to that exact release path.

## 4. Staging discovery — P0/P1 BLOCKER

The following exact paths were checked:

- `/data/data/com.termux/files/home/HG-staging-enforcement-20261023` — exists, but `git -C <path> rev-parse --show-toplevel` returned “not a git repository”.
- `/data/data/com.termux/files/home/hg-staging-20261023` — exists, but is not a Git repository at that path.
- `/data/data/com.termux/files/home/HG-staging` — not found.

A name match is not sufficient to establish a staging checkout. No staging build or live E2E test was run.

**Required action:** identify an already-existing, explicitly authorized staging checkout of `OAI-GIANG/HG` with a valid Git root, recorded branch/HEAD, and clean/known worktree state. Do not create or repoint a staging directory without further authorization.

## 5. Safe reproducible tests executed

Commands were run from the candidate checkout with bytecode writes disabled and pytest cache disabled.

### 5.1 Brain test suite

Command:

```sh
cd /data/data/com.termux/files/home/HG
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider brain/tests
```

Result: **73 passed in 0.25s**.

### 5.2 Combined candidate suites

Command:

```sh
cd /data/data/com.termux/files/home/HG
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider brain/tests memory/tests runtime/tests tools_automation/tests maep/tests
```

Result: **345 passed, 46 subtests passed, 1 warning, in 6.84s; process exit code 0.**

Warning: `maep/tests/test_trusted_providers.py:77` — pytest could not collect helper class `TestOnlyProvenanceVerifier` because it defines `__init__`. This is a collection warning, not a test failure, but it should be classified and resolved or explicitly accepted in the test catalogue.

A pytest invocation without `PYTHONPATH=.` initially failed collection with `ModuleNotFoundError` for `maep` and `brain`. The correctly rooted invocation above then passed. This establishes a test invocation/environment requirement; it does not establish production runtime binding.

### 5.3 Diff hygiene and post-test state

- `git diff --check`: PASS (exit 0).
- Branch and HEAD remained `stt/maep-v1-20261022` / `f7f00a75c6a1b1363993c2fb9bc023171f080038`.
- PID 15005 remained alive; no service lifecycle action was performed.
- Existing dirty source tree remains. Test results apply to this local candidate checkout, including its pre-existing uncommitted changes, not to canonical `main` or the running process.

## 6. Evidence interpretation

| Claim | State | Evidence and limitation |
|---|---|---|
| Candidate identity | VERIFIED | Origin, branch and HEAD read from Git in `~/HG`. |
| Working-tree preservation | PARTIAL | HEAD unchanged; existing dirty state retained. The audit report itself is an intentional new untracked artifact. |
| Brain/planner unit and integration logic | TESTED | 73 candidate tests pass; test providers/mocks and in-memory test fixtures do not prove live model quality. |
| Memory, runtime composition, HTTP handler, automation contracts and MAEP tests | TESTED | Combined suite: 345 passed plus 46 subtests; local test harness only. |
| Diff whitespace hygiene | VERIFIED | `git diff --check` exit 0. |
| Runtime is the audited candidate HEAD | UNVERIFIED | PID 15005 cwd is a separate out-of-scope release path; no in-scope source-to-process binding evidence. |
| Staging source identity | BLOCKED | Two candidate staging paths are not Git roots; third path absent. |
| Live model-provider inference from the running HG API | UNVERIFIED | No live end-to-end request from a verified staging build was executed. |
| End-to-end MAEP enforcement on all production entrypoints | UNVERIFIED | Unit/integration tests pass, but no verified runtime binding or adversarial E2E on staging. |
| Adversarial coverage | PARTIAL | Tests include wrong candidate/repository, stale policy, scope mismatch, replay, timeout, malformed result, public endpoint and redirect cases; no complete staging/runtime adversarial campaign. |
| Canonical release readiness / autonomous intelligence level | BLOCKED | Cannot infer production capability or high autonomy from candidate-only test results. |

## 7. Updated capability levels and progress estimates

Percentages below are **audit rubric estimates**, not measured IQ, a probability of security, or objective product-completion metrics. “Implementation” means code/design present in the inspected candidate; “verification” means evidence obtained in this audit.

| Axis | Provisional level | Implementation progress | Candidate test verification | Runtime verification | Confidence |
|---|---:|---:|---:|---:|---|
| Structure and modularity | 3/5 | ~80% | ~50% | ~25% | Medium for candidate source; low for runtime |
| Integrated intelligence | 2–3/5 | ~65% | ~50% | ~20% | Medium-low |
| Controlled autonomy | 2–3/5 | ~60% | ~55% | ~20% | Low-medium |
| MAEP enforcement | 3/5 within application boundary only | ~70% | ~65% | ~25% | Medium for test evidence; low for live enforcement |
| Overall runtime certification readiness | Not certified | ~60% | ~55% | ~25% | Low |

The passing combined suite increases confidence in candidate-level logic and regression coverage. It does **not** increase runtime-binding confidence because the live process remains bound to a separate path and staging has not been established.

## 8. Blockers and exact next actions

- **B-01 / P0 — Runtime source binding:** PID 15005 runs from an out-of-scope release directory. Do not inspect its contents under current scope. Obtain explicit authorization for the exact path or provide an in-scope staging runtime.
- **B-02 / P0 — No valid staging Git root:** both named staging directories are not repositories at those paths. Identify the exact existing authorized checkout and verify origin/HEAD/worktree.
- **B-03 / P1 — Live provider E2E absent:** after a valid staging checkout and runtime are identified, run tests against an isolated loopback port and isolated temporary state; do not touch production.
- **B-04 / P1 — MAEP universal enforcement unproven:** trace every exposed entrypoint to the same policy/gateway and run negative tests on the exact staged runtime.
- **B-05 / P2 — Pytest collection warning:** classify or fix the helper-class naming/collection issue in a separately authorized source-change task; no source fix was made here.
- **B-06 / P1 — Test provenance:** results are from the dirty local candidate, not a clean reproducible artifact tied to canonical Git commit. A source manifest and staged build identity are still required.

## 9. Stop condition and closure criteria

Do not declare audit PASS until all of the following are evidenced:

1. An in-scope staging Git root identifies `OAI-GIANG/HG`, exact candidate HEAD, and known worktree state.
2. A reproducible staged artifact manifest binds source paths/hashes, candidate commit and actual runtime entrypoint.
3. Runtime import/call tracing proves the intended Brain, model provider, Memory, tools and MAEP enforcement paths are loaded.
4. Positive and negative end-to-end tests run against that staged runtime with isolated state and no production mutation.
5. Adversarial cases fail closed, with receipts/evidence and no unauthorized effects.
6. Post-test checks confirm production PID/config/data and candidate source state were preserved.

**Final state: PARTIAL.** Candidate test suites pass; runtime source binding and staging are blocked. No production change or deployment occurred.

## Next command

```text
STT — HG — MAEP — RESOLVE STAGING IDENTITY ONLY

1. Chỉ làm việc trong OAI-GIANG/HG và staging đã được chủ nhân cho phép.
2. Không đọc nội dung, không sửa, không restart và không truy cập sâu vào
   /data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676
   vì đường dẫn này hiện nằm ngoài phạm vi được cấp.
3. Xác định chính xác staging checkout hiện có; xác minh origin, branch,
   HEAD, status và runtime entrypoint từ bên trong phạm vi được phép.
4. Không tạo staging mới, không sửa source, không deploy.
5. Nếu không tìm được staging hợp lệ, dừng với BLOCKED và yêu cầu đúng
   đường dẫn hoặc quyền truy cập cần thiết.
6. Sau khi staging được xác minh, mới lập kế hoạch E2E cô lập; chưa chạy
   test lên production.
```
