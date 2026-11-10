# HG Memory Continuity R3.1 — Port Integration Verification

**Checkpoint:** V3-CP02 — 2026-11-11 (Asia/Bangkok)
**Repository:** OAI-GIANG/HG only
**Worktree:** `~/HG-MEMORY-CONTINUITY-R3.1-PORT`
**Branch:** `stt/hg-memory-continuity-r3.1-port-20261111`
**Base / pre-integration HEAD:** `272300a7663176b19d01ce792d26fe2cbc5f71d0`
**Production:** unchanged; no STT-initiated lifecycle action, inference, migration, release-pointer change or trust-anchor change; one external/unattributed service start was observed and documented below
**Disposition:** COMPONENT TESTS PASS WITH 3 PLATFORM SKIPS IN EACH PYTHON SUITE; NOT A GO-LIVE CERTIFICATION

## 1. Scope and work performed

This checkpoint continues the already-created Memory Continuity R3.1 port. It does not repeat the original 26-worktree inventory, 70-path forensic scan, production baseline capture, L5 probe or earlier targeted tests.

The port incorporates the preserved R3.1 implementation into an isolated worktree based on the V3 execution checkpoint. The integration retains the current main-branch HTTP origin handling, `/v1/chat/save-preview` and `/v1/chat/save` behavior, safe repair reads, EventLog append/read-only paths, memory provenance and principal-binding checks, and durable save-outcome behavior.

A re-entrant, symlink-resistant memory outcome lock was added because Notebook and MemoryStore intentionally acquire the same lock within one thread. The lock uses a per-path thread `RLock`, thread-local re-entry tracking, one reused descriptor per thread-held lock, kernel `flock`, `O_NOFOLLOW`, and owner/mode/link-count checks. Directory/FIFO repair paths were corrected to avoid creating lock sidecars for non-regular objects.

A MAEP policy test initially treated two dated R3.1 evaluation reports as current governing instructions. The owner decision `OD-IR-20261109` superseded their former review gate. The scanner now exempts only those two exact dated report paths as historical records; it does not relax scanning of current governing files. The focused policy tests and full MAEP suite were rerun after this correction.

## 2. Actual verification

All commands ran on the connected Termux Android ARM64 device from this isolated worktree, unless the command itself is a Node.js test.

| Test | Actual result | Exit | Notes |
|---|---:|---:|---|
| `python3 -B -m unittest discover -s hg/tests -p 'test_*.py'` | 735 tests; 0 failures; 3 skipped | 0 | 267.506 s |
| `python3 -B -m unittest discover -s maep/tests -p 'test_*.py'` | 370 tests; 0 failures; 3 skipped | 0 | 4.259 s; rerun after policy test correction |
| `python3 -B -m unittest -v maep.tests.test_no_mandatory_independent_review` | 8 tests passed | 0 | Focused regression |
| `node hg/tests/test_memory_save_flow.js` | 9/9 passed | 0 | Browser save-flow behavior |
| Python AST parse | 23 changed Python files; 0 syntax errors | 0 | Current staged + unstaged source |
| `node --check hg/ui/app.js` and `node --check hg/ui/memory-save-flow.js` | Both passed | 0 | JavaScript syntax |
| `git diff --cached --check` and `git diff --check` | Both passed | 0 | Whitespace/conflict-marker check |

The three skips in each Python suite remain skips, not passes. They are platform-dependent tests (hard-link and privileged `chown` behavior); they do not qualify unavailable security behavior. Test output also included non-fatal Python `ResourceWarning` messages for unclosed test database/socket/HTTPError objects. This does not change the reported test exit status, but test resource cleanup remains a follow-up.

## 3. Evidence files and SHA-256

Evidence directory:

`docs/evidence/HG-MASTER-GO-LIVE-V3-20261111/r3.1-port/`

The following log files are stored with this report. Their hashes and exit-code sidecar hashes are recorded in `SHA256SUMS`, which was read back and verified with `sha256sum -c SHA256SUMS`.

| Artifact | SHA-256 |
|---|---|
| `HG_SUBTREE_PYTHON314.log` | `1103bc5682434d21f89b21341727ad2153c5068178db981cd09a6e8f9b85f78e` |
| `MAEP_FULL_PYTHON314.log` | `faec85cafdb45d80c33458085ee957251b45ea984910ce00ab3948b98edce90b` |
| `MAEP_POLICY_REGRESSION.log` | `2a1007f2463b4244f65708f6ed5da052ef4ece35a91fbd6a3adc8e560bc67c33` |
| `NODE_MEMORY_SAVE_FLOW.log` | `80080c511ef8ad57850bfa9881495489963f806aea92d9194bbb3e81391c725b` |
| `DIFF_CHECK.log` | `e3b0c44298fc1c149afbf4f8996fb92427ae41e4649b934ca495991b7852b855` |

Exit-code sidecars for all five commands contain `0`; their SHA-256 is `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`. The exact manifest is `SHA256SUMS`.

## 4. Changed-source summary

The port currently contains 46 staged files (6,842 insertions and 120 deletions in the staged diff) plus one unstaged MAEP policy test correction (8 insertions, 1 deletion). The policy correction is part of this checkpoint and must be included in the eventual commit. No source branch or original worktree was overwritten.

The changes cover MemoryStore provenance/locking, curation, ASK receipt and save identity, CLI integration, HTTP save routes, chat orchestration, repair handling, browser save-flow behavior, task-store integration, and tests. The exact inventory is in `git status` and the Git diff.

## 5. Gate impact and limitations

- **G3 — PARTIAL, improved component evidence:** HG subtree and MAEP suite both pass with three skips each; this is not a complete certification of every repository component or the Android security controls.
- **G1 — PARTIAL:** the prior 70 overlapping changed-path inventory remains; 27 divergent source-path decisions are still unresolved. This Memory Continuity port does not close the global reconciliation gate.
- **G2 — BLOCKED:** Android PID namespace and complete cross-process listener-sharing observation remain unavailable/incomplete on this Termux build.
- **G4 — BLOCKED:** no universal all-provider/all-entrypoint model-call gate with request nonce, request/response correlation and post-call integrity proof.
- **G5 — BLOCKED:** historical signed APT provenance is not independently reverified; the runtime trust anchor remains empty.
- **G6 — BLOCKED:** isolated staging recovery, rollback and full data-integrity qualification have not been executed.
- **G7 — BLOCKED:** Android Broker APK/signing/install, actual distinct Android UID, and negative Binder caller proof remain absent.
- **G8 — BLOCKED:** no complete V3-gated inference-to-agent/tool-to-evidence end-to-end transaction has been qualified.

## 6. Safety and disposition

No production files, processes, release pointers, database, secrets or trust anchors were changed. No original worktree, candidate or snapshot was cleaned, reset, deleted or overwritten.

**This component port is test-green within the stated scope, but is not merged and does not authorize GO-LIVE.** The V3 mission remains **NO-GO** until G1–G8 each independently satisfy their actual acceptance criteria with reproducible evidence. The skips and Android-specific blockers remain explicit.



## 7. Read-only production/runtime observation after CP01

At the latest read-only observation on 2026-11-11 around 03:09 Asia/Bangkok:

- Runit reported `hg-runtime` up (PID 21771) and `ollama` up (PID 21775); both had approximately 193 seconds of supervisor uptime at the observation.
- HG runtime log recorded `HG_RUNTIME_READY` for release `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5` at `2026-11-10 20:09:12Z` (2026-11-11 03:09:12 +07).
- Authenticated `/v1/health/live`: HTTP 200, `LIVE`.
- Authenticated `/v1/health/ready`: HTTP 200, `READY`, integrity `VERIFIED`, same release ID.
- Authenticated `/v1/integrity`: HTTP 200, 303 files checked, same release ID.
- Ollama `/api/version`: HTTP 200, version `0.40.14`.

These PIDs differ from the earlier CP01 process observation. This task did not invoke `sv restart`, `sv down/up`, kill, or any Runtime/Ollama lifecycle action. The service log proves a fresh supervisor start at the timestamp above, but the available evidence does not identify who or what initiated it; root cause is **UNDETERMINED**. Treat this as an observed process-lifecycle change, not as evidence of an STT-initiated restart. No inference request was sent.

Evidence checksum-manifest SHA-256: `14c4cea9c6f631a91f2232159ffc9730144d971e113444a3f104817fcb856dbd` (`SHA256SUMS`).
