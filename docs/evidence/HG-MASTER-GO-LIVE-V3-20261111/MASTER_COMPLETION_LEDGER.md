# HG — Master Autonomous Completion Ledger V3.0

**Checkpoint:** V3-CP01 — forensic baseline, preservation, production read-only verification
**Date:** 2026-11-11 (Asia/Bangkok)
**Repository:** OAI-GIANG/HG only
**Disposition:** IN PROGRESS — NO-GO
**Implementation branch:** `stt/hg-master-go-live-v3-execution-20261111`
**Implementation worktree:** `~/HG-MASTER-GO-LIVE-V3-EXECUTION`
**Base / HEAD at checkpoint:** `e465db2ef8143d013d6195abfa077f5010b3fd1c`

## 1. Executive disposition

The existing production release is alive, ready under its current service contract, and integrity-verified. This does **not** establish the additional security and end-to-end acceptance required by V3. Production has not been modified, restarted, migrated, or cut over.

The historical 26-worktree baseline is preserved. The later GO-LIVE candidate is a 27th registered worktree; the new V3 execution worktree is a 28th. All source/evidence snapshots listed below passed their checksum verification. No original worktree was reset, cleaned, overwritten, deleted, or committed by this campaign.

**Final GO-LIVE is NO-GO** because G1 still has 27 divergent paths without selected implementations; G2/G4/G5/G6/G7/G8 remain blocked or partial; and G3 contains security-test skips on this Android environment.

## 2. Current workstream ledger

| Workstream | Disposition | Verified result | Outstanding acceptance |
|---|---|---|---|
| WP0 Session/environment | PARTIAL | Termux/RDC online; Android 17/API 37, arm64-v8a; runtime and production readiness verified | Long-duration stability and resource soak not run |
| WP1 Forensic reconciliation | PARTIAL | 26 historical worktrees + candidate preserved; 19 HG-only clones and 136 evidence records verified; 70 paths classified | 27 divergent paths still require source-level decisions and integration tests |
| WP2 Architecture/implementation | PARTIAL | Candidate and current architecture reviewed; Broker/model-call gaps recorded | End-to-end integration of model gateway, memory, agent, tools, voice and recovery not complete |
| WP3 Android isolation | BLOCKED | Android Broker source exists in candidate; no APK build/install or actual UID/Binder qualification | Gradle/JDK/SDK/ADB absent locally; CI workflow needs repair; actual-device L1/L5 and separate UID proof absent |
| WP4 Trust/provenance | BLOCKED | Installed Ollama package matches retained package artifact; production MAEP trust is LOADED | Historical signed APT chain for Ollama 0.40.14 is not reverified; model runtime trust anchor remains empty |
| WP5 Model-call gating | BLOCKED | Candidate fails closed when listener proof is unavailable; local provider wrapper has pre/post listener checks | No proven all-provider/all-entrypoint gate, request nonce/correlation, response integrity, or complete audit contract |
| WP6 Practical functionality | PARTIAL | Production /v1/health/live, /v1/health/ready and /v1/integrity return 200; Ollama /api/version returns 200 | No authorized end-to-end inference/agent/tool/memory transaction executed under V3 gates |
| WP7 Staging/recovery | BLOCKED | Preservation archives and readback verified | Isolated staging, destructive fault tests, restore/rollback and cold-start qualification not run |
| WP8 Production go-live | NO-GO | Production baseline captured; no cutover attempted | Requires G1-G7 PASS and G8 independent acceptance |

## 3. Acceptance gate matrix

| Gate | Disposition | Evidence / reason |
|---|---|---|
| G1 Worktree preservation and 70-path reconciliation | PARTIAL | 43 byte-identical; 27 divergent and explicitly UNRESOLVED_OWNER_CHOICE |
| G2 Android L1/L5 identity/listener security | BLOCKED | PID namespace unavailable; cross-process /proc and L5 sharing scan incomplete on actual Termux |
| G3 Regression/software test baseline | PARTIAL | Candidate logs: 763 passed / 40 skipped; MAEP 370 / 3 skipped; hooks 32 passed; targeted 14 / 2 skipped. Mandatory security cases skipped |
| G4 Complete model-call gating | BLOCKED | Candidate verifies listener before/after local calls but lacks complete request/response correlation and all-provider/entrypoint enforcement |
| G5 Runtime trust-anchor/provenance | BLOCKED | Historical signed APT metadata chain unavailable for the retained Ollama package; do not load an unqualified anchor |
| G6 Staging recovery/rollback/data integrity | BLOCKED | No staging recovery/rollback execution evidence |
| G7 Android Broker APK/distinct UID/negative Binder | BLOCKED | No APK, no install evidence, no actual second-UID Binder tests |
| G8 Integrated end-to-end practical operation | BLOCKED | Health/readiness verified; no full gated inference-to-agent-to-tool-to-evidence journey |

G1-G8 are mandatory. No aggregate PASS is permitted.

## 4. Production baseline (read-only)

- Android: 17, API 37, ABI arm64-v8a, device model PKC110, Termux UID 10460.
- Toolchain: Python 3.14.8; Node.js 26.12.1; Git 2.56.0; Ollama 0.40.14.
- Available resources at check time: approximately 327 GB free storage and 4.6 GiB available RAM.
- Local build tools unavailable: pnpm, Gradle, Java, adb, sdkmanager and emulator.
- HG Runtime runit service: PID 8499; Ollama runit service: PID 8486 (observed; neither was restarted).
- Production service config port: 18766.
- Production release ID: `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5`.
- Production release source commit: `4eaac81132ae57028cf2432eec911a01b6ecf1fd`.
- Release tree: `e214489430b319bc17633aa792fb13051aa43d75`.
- Release manifest SHA-256: `646f1604219f2b3852b608914c57a442d04dc7ffcea7c61f0df16a48d34dd941`.
- Read-only `python -B -m hg serve --config <runtime-config> --check`: `PREFLIGHT_PASS`; release `VERIFIED`; MAEP owner trust `LOADED`.
- Authenticated GETs: `/v1/health/live` 200; `/v1/health/ready` 200; `/v1/integrity` 200. Integrity reports 303 files checked, `VERIFIED`.
- Ollama GET `/api/version`: 200. No model inference was invoked on production.

**Important distinction:** MAEP owner-grant trust reported as LOADED is not Ollama package provenance qualification and is not a non-empty Ollama runtime trust anchor.

## 5. Preservation and reconciliation evidence

Snapshot root:

`~/HG-RECOVERY-SNAPSHOTS/HG-MASTER-GO-LIVE-V3-20261111T021511+0700`

Primary snapshot:
- Captured 27 registered worktrees at snapshot time (26 historical worktrees + GO-LIVE candidate).
- 10,433 filesystem entries inventoried.
- `worktrees.tar.gz` SHA-256: `<see MANIFEST.sha256>`.
- `git-common-dir.tar.gz` SHA-256: `<see MANIFEST.sha256>`.
- Per-worktree status and diff records: WT01-WT27.
- Full readback and source-file SHA verification passed.

Supplemental snapshot:
- 19 HG-only snapshot/clone repositories verified present, at their recorded HEADs and clean.
- 136 evidence-manifest records: 136 present, 0 missing, 0 SHA mismatches.
- Two original dirty-worktree preservation archives match SHA-256 `948f410c93996f1901b6a75c6aaa1ce47a6e16ceca4d710652f2303dd52ae7cf`.
- Retained Ollama 0.40.14 Debian package matches SHA-256 `d82733c1606dc21083ed6eaa5060fc099f6306e6f4f4cbb1d9e3fdd9eca0e95c`.
- `go-live-v2-evidence-and-clones.tar.gz` SHA-256: `18cbf115778115a1d569fea2eec8da4594aa1aed9f7b7776ec1fb18645886b4e`.
- Three foreign-repository clones were excluded and left untouched.

V3 execution worktree snapshot:
- Branch `stt/hg-master-go-live-v3-execution-20261111`, HEAD `e465db2ef8143d013d6195abfa077f5010b3fd1c`.
- 305 regular files archived and SHA-verified.
- `execution-worktree.tar.gz` SHA-256: `5d0da2c1b42a73f665e387642ef3b58d72fa30c3304ea38e15186b0749dad9fe`.
- Updated Git common-dir archive SHA-256: `7dbfceef38f5741922a40484cfd03d56091d7fbdd858e801bc4ab343a4571257`.
- Supplemental manifest: `EXECUTION-BASELINE-MANIFEST.sha256`; verified OK.

The primary and supplemental manifests are local Termux evidence and must remain available for restore. See the snapshot root for exact digests.

## 6. Candidate and CI observations

Candidate:
- Worktree: `~/HG-GO-LIVE-CANDIDATE`.
- Branch: `stt/hg-go-live-certification-20261111`.
- HEAD: `e465db2ef8143d013d6195abfa077f5010b3fd1c`.
- Candidate remains dirty: 8 tracked files changed, 86 untracked entries, plus ignored build/runtime artifacts. It has not been altered by this V3 execution branch.

Existing candidate logs are prior evidence, not V3 independent retests:
- Full HG suite: 763 passed, 40 skipped.
- MAEP suite: 370 passed, 3 skipped.
- Agent hooks: 32 passed.
- Targeted regression: 14 passed, 2 skipped.
- Security skips include PID-namespace, cross-process descriptor, listener sharing and root/unshare-dependent tests.

GitHub:
- `origin/main` at checkpoint: `e465db2ef8143d013d6195abfa077f5010b3fd1c`.
- Main MAEP test run #42825117398 succeeded; Python 3.13 and 3.14 checks succeeded for that SHA.
- PR #77 remains open and unmerged; branch `feat/listener-attestation-hg-la-2-20261031`, head `73a45f059d51d91c6063580e1a4a86268d377611`, mergeable state `unstable`.
- The GitHub integration denied branch-protection API access (403); protections must not be inferred or bypassed.
- The V3 candidate branch has not been pushed and its new Android workflow has not run.

## 7. Independent execution-branch baseline test

On the clean V3 execution worktree (base `e465db2ef8143d013d6195abfa077f5010b3fd1c`), Python 3.14.8 ran:

```text
python3 -B -m unittest hg.tests.test_http_api hg.tests.test_service hg.tests.test_chat_service hg.tests.test_assistant_ask
Ran 79 tests in 25.498s
OK
```

- Exit code: 0.
- Skips: none reported by unittest.
- Non-fatal warning: one `ResourceWarning` for an unclosed local test socket during cleanup. Track and fix in the relevant test lifecycle.
- Log: `~/HG-RECOVERY-SNAPSHOTS/HG-MASTER-GO-LIVE-V3-20261111T021511+0700/logs/targeted-baseline-python314-rerun.log`.
- SHA-256 is recorded in the checkpoint evidence manifest.

A prior invocation mistakenly named `hg.tests.test_attest`, which is not present on this main-branch baseline; that invocation returned an import error. It was not counted as a passing run. Candidate attestation tests remain separate evidence and are not conflated with this baseline.

## 7. Immediate dependency order

1. Complete source-level reconciliation of all 27 divergent paths; record selected source SHA, rejected alternatives, tests and recovery references.
2. Resolve listener attestation on the actual Android target: identify supported Android-specific observation methods or remain BLOCKED.
3. Repair Android Broker build/test workflow; build APK; verify signer/package identity; perform actual separate-UID positive and negative Binder tests on emulator and physical Android target.
4. Decide and implement a backend transport that demonstrably provides filesystem AF_UNIX, kernel peer credentials and request/response correlation. Do not assume `OLLAMA_SOCKET_PATH` is supported by Ollama 0.40.14.
5. Establish source-pinned and independently verifiable runtime provenance. Keep trust anchor empty until qualified.
6. Enforce the model-call policy at every production entrypoint and provider; prove bypass refusal and post-call integrity before exposing responses.
7. Build isolated staging and execute full recovery/rollback, concurrency, race, data-integrity, cold-start and resource tests.
8. Only then prepare a production cutover manifest and re-run G1-G8 independently.

## 8. Safety / stop conditions

- Do not alter production service, release pointer, Ollama service, production data, trust anchors or secrets during this checkpoint.
- Do not reset, clean, overwrite, delete or reuse the 26 original worktrees, candidate, evidence archives or snapshots.
- Do not mark unavailable/skipped/mock/emulator-only evidence as a physical Android PASS.
- Do not load a runtime into the trust anchor until the full provenance chain is qualified.
- Stop deployment if any mandatory gate is not PASS; preserve NO-GO and continue independent work.


---

# V3-CP02 — Memory Continuity R3.1 isolated port and verification

**Recorded:** 2026-11-11 (Asia/Bangkok)
**Worktree:** `~/HG-MEMORY-CONTINUITY-R3.1-PORT`
**Branch:** `stt/hg-memory-continuity-r3.1-port-20261111`
**Base / HEAD before port changes:** `272300a7663176b19d01ce792d26fe2cbc5f71d0`
**Disposition:** COMPONENT TESTS PASS WITH PLATFORM SKIPS; UNCOMMITTED AT CHECKPOINT; GLOBAL NO-GO

## Scope delta

This checkpoint does not repeat WP0 discovery, original 26-worktree preservation, the 70-overlap inventory, production baseline verification, or prior Android L5 probing. It advances one isolated Memory Continuity R3.1 integration candidate only.

The port integrates MemoryStore provenance and durable save semantics, ASK receipt identity, memory curation, CLI and chat/API save paths, UI unknown-outcome retry behavior, repair hardening, re-entrant sidecar locking and related tests. The source integration was applied in a new worktree; original source worktrees, the GO-LIVE candidate and production were not overwritten.

A policy-scan regression was fixed narrowly: two exact R3.1 evaluation documents dated 2026-11-02 are preserved as historical evaluation artifacts because owner decision OD-IR-20261109 superseded their former independent-review gate. Current governing documents remain scanned. The focused policy regression is 8/8 PASS.

## CP02 verification result

| Check | Result | Disposition |
|---|---:|---|
| HG subtree on Python 3.14.8 | 735 tests, 0 failures, 3 skipped; exit 0; 267.506 s | PASS within component scope; skips remain open |
| MAEP suite on Python 3.14.8 | 370 tests, 0 failures, 3 skipped; exit 0; 4.259 s | PASS within component scope; skips remain open |
| MAEP no-mandatory-review policy regression | 8/8; exit 0 | PASS |
| Node Memory Save Flow | 9/9; exit 0 | PASS |
| Python AST parse | 23 changed Python files; 0 syntax errors | PASS |
| JavaScript syntax | `hg/ui/app.js` and `hg/ui/memory-save-flow.js` | PASS |
| Staged and unstaged diff check | Both clean | PASS |

Non-fatal ResourceWarning messages for test database/socket/HTTPError cleanup remain visible in the Python full-suite log. They are recorded as cleanup debt, not test failures.

Evidence and checksums:
`docs/evidence/HG-MASTER-GO-LIVE-V3-20261111/r3.1-port/R3_1_PORT_INTEGRATION_TERMUX_20261111.md`
`docs/evidence/HG-MASTER-GO-LIVE-V3-20261111/r3.1-port/SHA256SUMS`

## Updated gate matrix

- G1 PARTIAL — 70 overlapping changed paths remain inventoried; 27 divergent path/source decisions remain unresolved. This port does not close repository-wide source ownership.
- G2 BLOCKED — actual Android PID-namespace and complete process-sharing/listener observation remain incomplete.
- G3 PARTIAL — component suites pass as stated above, but six platform skips across the two Python suites remain skips and Android security qualification is not supplied by these tests.
- G4 BLOCKED — no complete all-provider/all-entrypoint model-call gate with nonce, request/response correlation and post-call integrity.
- G5 BLOCKED — no independently qualified historical signed APT provenance chain; runtime trust anchor remains empty.
- G6 BLOCKED — no isolated staging restore, rollback and data-integrity qualification.
- G7 BLOCKED — no signed Broker APK installed and no actual distinct-UID positive/negative Binder qualification.
- G8 BLOCKED — no complete V3-gated inference → context/memory → model → authorized tool/agent → evidence → frontend transaction.

**V3 remains NO-GO.** Component tests passing do not imply G1-G8 PASS.

## Worktree and publication state

At CP02 verification, the port branch is based on V3 execution checkpoint commit `272300a7663176b19d01ce792d26fe2cbc5f71d0`; it has no configured upstream. It contains the imported integration changes and the narrow policy test correction. The candidate has not been merged into `main` or deployed. Commit/push status is to be recorded in the next checkpoint after final staged-source review.

## Production safety

Production Runtime and Ollama were not restarted, changed or sent an inference request. No production data, release pointer, secrets, or trust anchors were modified. Existing production integrity evidence remains scoped to the pre-existing release contract, not V3 certification.


## CP02 runtime note

The read-only process check during CP02 found new runit children: `hg-runtime` PID 21771 and `ollama` PID 21775, both with approximately 193 seconds uptime. The runtime log recorded `HG_RUNTIME_READY` at 2026-11-10 20:09:12Z for the same production release ID. Authenticated health/live, health/ready and integrity endpoints returned HTTP 200; integrity reported 303 checked files; Ollama /api/version returned 0.40.14. These PIDs differ from CP01. No runtime lifecycle command was issued by this task; the initiator/root cause of the fresh supervisor start is undetermined. No inference was invoked. WP0 remains PARTIAL until the process-lifecycle event is attributed and stability is demonstrated.
