# HG-MASTER-LISTENER-ATTESTATION-EXECUTION-V1 — execution and acceptance record

Date: 2026-10-31 (Asia/Ho_Chi_Minh). Executor: STT (Claude, cloud sandbox). Design: `docs/architecture/HG_LISTENER_ATTESTATION_V2.md`.
Final status: **PARTIALLY_COMPLETE / BLOCKED_EXTERNAL (device)** — never CLOSED_VERIFIED, because L5 and the trust anchor
have no on-device evidence.

## A. Objective and scope

Five-layer listener attestation for the local Ollama service and its evidence, in `OAI-GIANG/HG` only. In scope here:
repository work, sandbox tests, standalone probe and benchmark tools, design. Out of reach: the owner's phone.

## B. Initial state (verified, not inherited)

| Item | Observation | Evidence |
|---|---|---|
| Repository | `https://github.com/OAI-GIANG/hg`, branch `main`, HEAD `2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5` (PR #76, 2026-10-29), clean tree, `origin/main` identical | session commands |
| Baseline tests, root | maep 304 OK; hooks 32 OK; hg 417 with **1 failure** `test_release.SealedReleaseTests.test_sealed_import_without_dont_write_bytecode_leaves_tree_unchanged` | `logs/baseline-*.log` |
| Root cause of that failure | environment: root ignores the 0o555 seal; the sibling test already skips for euid 0. Re-run as uid 999: release tests 16 OK, full hg 417 OK | `logs/baseline-hg-release-nonroot.log`, `logs/baseline-hg-nonroot.log` |
| Device (Termux, Android 16) | both Desktop Commander devices **offline** (last seen 3 h and 45 h before) → Termux, runit, Ollama, PRoot, model, listener state all UNKNOWN | session |
| Owner's uncommitted changes on the phone (`~/HG`) | not reachable; untouched | — |
| Secrets/config | none read; none in this package | — |
| Sandbox | Linux 6.18.44 x86_64, Python 3.13.18, root and uid 999; no runit package reachable; Termux repositories unreachable | `logs/final-summary.txt`, `source-facts.txt` |

## C. Findings — see design §2 (F-1 … F-8). F-1 is a reproduced defect in `main`. F-8 (Yama `ptrace_scope=1`
restricts `pidfd_getfd` to ancestors) was found when the first CI run failed: the sandbox has no Yama, GitHub's
Ubuntu runners do. The tests were corrected to assert BLOCKED/EPERM for a non-ancestor attester under Yama.

## D. Root cause (F-1)

`config.attest_listener` inferred port ownership from process liveness ("Ollama exits when it cannot bind its port").
With a squatter on the port, runit restarts Ollama continuously and each attempt is briefly alive; liveness and
ownership are different facts. Reproduction on `main@2f00a62` code (`logs/F1-reproduction-main-2f00a62.log`): old
check `VERIFIED_PROCESS`, new check `FAIL / NO_LISTENER`.

Round 2 (task `HG-LA-2 — PR #77 FINAL EVIDENCE RECONCILIATION`, same day):
- **F-9** — listeners were counted per descriptor, so `dup()` made one socket look like two
  (`FAIL/MULTIPLE_LISTENERS, count 2`; probe `NO_UNIQUE_LISTENER`). Root cause: matches keyed by fd instead of
  socket inode. Severity P2: fail-closed false negative, not a bypass. Failing-first: `logs/F9-failing-first.log`,
  `logs/F9-probe-failing-first.log`.
- **F-10** — the sharing scan reported one "hidden" count. It did not classify uninspectable processes, it skipped
  unreadable descriptors silently, and it ignored `hidepid`. Root cause: `socket_holders()` modelled only "holder /
  not holder". Severity P2: evidence clarity; the claim was already worded "visible", but the limit did not travel
  with the PASS. Answer to "does `hidden > 0` qualify for PASS?": not by itself. L5 PASS rests on kernel bind rules
  plus Q3, and the result now states `scope` (`PARTIAL` here and expected on Android) and that basis. Design §4.

## E. Implementation (all on branch `feat/listener-attestation-hg-la-2-20261031`)

New: `hg/assistant/attest.py`, `hg/assistant/trusted_runtimes.json` (empty), `deploy/termux/l5_probe.py`,
`deploy/termux/ollama_bench.py`, `hg/tests/test_attest.py`, `hg/tests/test_l5_probe.py`, `hg/tests/test_ollama_bench.py`,
`hg/tests/fixtures/attest/{target,runsv_double}.py`, the design document, this package.
Changed: `hg/assistant/config.py` (reason text, `"listener": "UNVERIFIED"`, docstring — refusal behaviour unchanged),
`hg/tests/test_assistant_ask.py` (asserts the new fields), `.github/workflows/maep-tests.yml` (installs runit, sets
`HG_REQUIRE_PROC_TESTS=1` so capability gaps fail instead of skipping), `CLAUDE.md`, `docs/V1_SCOPE.md` (F-1 note).
Deleted: nothing. Not done on purpose: wiring into `ask`/`/v1/chat` (design §11 gate).
Round 2 (commit `d79d1ca`): `attest.py` groups listeners by inode, adds `fds`, structured `socket_holders()`,
`proc_hidepid()`, the `sharing` block with `SHARING_BASIS`, and `reverify()` over any recorded descriptor;
`l5_probe.py` has the same grouping and sharing observation; new tests are listed in design §10.
`trusted_runtimes.json` is unchanged (still empty).

## F. Tests

| Run (uid 999 unless noted) | Command | Exit | Result |
|---|---|---|---|
| MAEP | `python3 -m unittest discover -s maep/tests` | 0 | 304 OK, 1 skip (needs root to chown) |
| HG | `python3 -m unittest discover -s hg/tests -t .` | 0 | **473 OK**, 2 skips (netns needs root; real runit absent) |
| Hooks | `python3 -m unittest discover -s .claude/hooks -p "test_*.py"` | 0 | 32 OK |
| Self-check / bench | `python3 -m hg selfcheck` / `python3 -m hg bench` | 0 / 0 | PASS / PASS |
| Attest + probe as root | `python3 -m unittest hg.tests.test_attest hg.tests.test_l5_probe -v` | 0 | 53 OK, 1 skip (real runit) — netns case ran |
| Mutation | 12 mutants of critical checks + 1 control | — | control PASS; **12/12 killed by assertion failures**, 0 invalid |

Round 2, on the code committed as `d79d1ca` (`logs/round2/`):

| Run (uid 999 unless noted) | Exit | Result |
|---|---|---|
| MAEP | 0 | 304 OK, 1 skip (needs root to chown) |
| HG | 0 | **483 OK**, 4 skips (netns needs root; real runit absent; 2 Yama tests, since there is no Yama here) |
| Hooks | 0 | 32 OK |
| Self-check / bench | 0 / 0 | PASS / PASS |
| Attest + probe as root | 0 | 63 OK, 3 skips (real runit; 2 Yama) |
| Mutation of F-9/F-10 logic | — | control PASS; **7/7 killed by assertion failures**, 0 invalid (`logs/mutation-sharing.log`) |

Positive: verified listener + post-check, CLI JSON, probe self-test (12 checks) and same-UID target. Negative and race
cases: the 30-case matrix in design §10 plus sharing, netns and kernel bind rules. Regression: full suites above.
Integration level: real kernel, real processes and sockets in the sandbox — **not** the Android device.

## G. Evidence (this directory; hashes in `artifact-manifest.sha256`)

`logs/` baseline and final runs, F-1 reproduction, mutation log. `probe/` raw probe JSON (probe artifact
SHA-256 `2d57a6b1e2faa9bfa538f5d2274ce490a52b01521e57b13df1c686fcd3cdf96d`): self-test PASS (root, uid 999), same-UID
target `LISTENER_OWNED`, wrong port `NO_UNIQUE_LISTENER` (exit 1), cross-UID `BLOCKED/FD_TABLE_EACCES` with direct
`pidfd_getfd` → `EPERM` (exit 2). `probe/` is from the first probe version and is kept as a record; it is
superseded by `probe-v2/` (probe artifact SHA-256 `9d774eba08817a42964a8346b5c11cbdedbc90d440f6a4c7a5836a568c07284d`,
commit `d79d1ca`): the same five cases plus `target-dup.json` (one socket, `fds [3, 4]`, `LISTENER_OWNED`). Every
run reports `sharing.scope = PARTIAL`: as uid 999 the root processes are uninspectable, and even root cannot read
PID 1's descriptors in this sandbox. `source-facts.txt`: Ollama v0.40.13, termux-packages recipe, bionic and SELinux
references. Benchmark JSON / TTFT from a real model: **none** (NOT_RUN).

## H. Security and risk

Residual: L5 unproven on Android 16 (F-5 is inference); L3 has no anchor (F-7); libraries and the runner child are
not attested (design §8); same-UID/root out of scope (Q3). The legacy check still lets `ask` proceed on process evidence
alone, now labelled honestly. CI change adds an `apt-get install runit` step: a network failure there fails CI
(visible, not silent).

## I. Git and CI

PR #77 (`feat/listener-attestation-hg-la-2-20261031` → `main`, base `2f00a62`), open, not merged. The agent's merge
attempt was refused by the session's safety control (no human review), so the merge is the owner's decision.
CI on code commit `d79d1ca6327f783d7490a34add012f7e4fa1f073`: runs `41207019585` (MAEP tests, push), `41207023339`
(MAEP tests, pull_request) and `41207023340` (rt06), all `success`; `unittest (3.13)`/`(3.14)` jobs `124554075160`/
`124554074977` (push) and `124554086179`/`124554085902` (pull_request). Earlier: first CI run red on `16f04cf`
(F-8, Yama), green on `65d324c` and `f39a0be`. Later documentation-only commits: see PR #77 checks.

## J. Runtime / deployment

Nothing deployed; no service, port, file or process on the phone touched. Release integrity unaffected (new files are
ordinary tracked files covered by the release manifest).

## K. Cleanup audit (sandbox)

All test supervisors, targets, listeners and probe children terminated (checked with `ps` after each run); temporary
directories removed; read-only source clones kept only in the session scratchpad (outside the repository).

## L. Acceptance matrix

| Criterion | Status |
|---|---|
| Canonical repo, controlled changes | VERIFIED |
| L1 supervision | INTEGRATION_TESTED (sandbox stand-in; real runsv in CI) — device UNVERIFIED |
| L2 identity | INTEGRATION_TESTED — device UNVERIFIED |
| L3 trust anchor / provenance | BLOCKED (F-7) |
| L4 credentials policy | UNIT_TESTED + INTEGRATION_TESTED — device UNVERIFIED |
| L5 listener ownership | INTEGRATION_TESTED (sandbox + CI); exclusivity shown among inspected processes only (`scope PARTIAL`, basis Q3) — device UNVERIFIED |
| Native runtime choice | DESIGN (Termux package 0.40.13 recommended; F-4) |
| Model digest pin | existing check, UNIT_TESTED; device digest UNVERIFIED |
| Positive/negative/regression tests | TESTED (sandbox + CI green on `d79d1ca`, Linux only) |
| Benchmark with raw data | tool UNIT_TESTED; device NOT_RUN |
| Service preflight / runtime verification | NOT_RUN |
| Evidence package, rollback point | present (branch; `main` untouched) |
| Overall | **not CLOSED_VERIFIED** |

## M. Blockers and unknowns

1. Device offline → run design §6 commands (probe, attest CLI) and the benchmark on the phone.
2. Trust anchor → design §9 on the phone, then a PR adding the entry.
3. Current runtime on the phone (PRoot vs Termux package, F-6) → UNKNOWN until 1.

## N. Next action — the NEXT ACTION COMMAND in the task's final report.
