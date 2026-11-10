# HG Memory Continuity V2 — R3.1 remediation report

**Recorded:** 2026-11-02T01:20:02+07:00
**Candidate:** `feature/memory-continuity-v2`
**Canonical baseline:** `main@2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5`
**Candidate HEAD:** `2f00a62deb2637ee4ce4cb7e77a82592cc87b1c5` (uncommitted working-tree candidate)
**Runtime:** Android / Termux ARM64; Python 3.14.8; Node.js 26.12.1
**Disposition:** `ENGINEERING_REMEDIATION_COMPLETE / READY_FOR_INDEPENDENT_RE_REVIEW`

## 1. Purpose and boundary

R3 was rejected before Integration Review. This R3.1 supplement addresses the remaining provenance-identity and ambiguous-save-outcome gaps found during the follow-up adversarial examination. It supplements, and does not rewrite, the historical R3 implementation record and R3 acceptance crosswalk.

All changes remain in the isolated `~/HG-memory-continuity` checkout on `feature/memory-continuity-v2`. The primary `~/HG` checkout was not modified. No production or private `HG_HOME` ledger was read or written. No commit, push, merge, deployment or live migration occurred.

## 2. R3.1 remediation

### R3.1-F01 — Bind MODEL_DERIVED authorization to an authenticated local credential principal

**Changed paths**
- `hg/http_api.py`: `HGHTTPServer` derives `owner_principal_id` only after the service token is configured; save-preview and save routes pass that server-selected identity to ChatService. The request body cannot provide or override it.
- `hg/assistant/ask_archive.py`: preview and confirmation digest include `authorized_principal_id`; new source references use the compact v2 identity `ask:<receipt_id>:v2:<confirmation_sha256>`.
- `hg/assistant/notes.py`: principal identity participates in the immutable ASK receipt save identity used for exact retry/replay classification.
- `hg/memory/store.py`: new MODEL_DERIVED writes require a valid principal and independently verify the v2 source reference, receipt, exact model-output excerpt and confirmation digest.
- `hg/chat.py`: the principal is returned as provenance metadata; `verified_truth` remains false.

**Principal semantics**
- HTTP principal: `owner:service-token-sha256:<SHA-256 of the configured bearer token>`. The raw bearer token is never written to memory or returned as the principal.
- Local CLI principal: `owner:termux-uid:<OS uid>`, resolved by the trusted local process rather than request text.
- A changed service token yields a different credential principal. A preview made under one credential cannot be confirmed under another; the preview must be recreated.
- This is a credential-bound local principal, **not** a globally authenticated account identity, OpenAI account identity, multi-user identity provider or cross-device identity/ACL system. Same-UID code is within the existing local trust boundary; no stronger claim is made.

**Legacy compatibility**
- Existing R3 MODEL_DERIVED ledger entries without a principal remain readable through the explicit legacy replay path.
- New writes must carry the principal-bound v2 identity. The compatibility path does not authorize creating new legacy-format records.

### R3.1-F02 — Distinguish an unknown save outcome from a confirmed failure

**Changed paths**
- `hg/ui/memory-save-flow.js`: network status `0` and HTTP 5xx after a save submission now return `SAVE_OUTCOME_UNKNOWN`, not `SAVE_FAILED`.
- `hg/ui/app.js` bounds the save request with a **30,000 ms** AbortController timeout. A timeout/network loss or HTTP 5xx after submission is surfaced as an unknown outcome, not a confirmed no-write.
- On an unknown outcome, the exact preview is retained, input controls are unlocked, and the UI tells the owner that the append may already have committed.
- A retry submits the same receipt, subject, content and confirmation digest. Notebook's receipt binding returns the already-created active note on an exact retry, rejects changed identity, and returns HTTP 409 for a retracted/superseded receipt; it does not silently recreate or duplicate the note.
- Definitive 4xx outcomes remain `SAVE_FAILED`; the UI does not misclassify a 409 conflict/inactive receipt as an ambiguous transport result.

### R3.1-F03 — Regression coverage

New/updated tests cover:
- HTTP derives the principal from the configured bearer token, not from client-supplied JSON.
- Principal changes produce a different confirmation digest; a digest from principal A cannot be used as principal B.
- The stored note carries the credential principal but not the raw bearer token.
- A dropped response after durable save is represented as `OUTCOME_UNKNOWN`; the 30-second UI request deadline triggers that path and retry sends the identical receipt/digest, returning the existing note without creating a duplicate.
- HTTP 5xx after save submission is treated conservatively as an unknown result.
- Existing retraction/supersession, source provenance, exact retry, UI race, 4,000-character and 4,001-character guards remain covered.

## 3. Verification evidence

All evidence below was recorded against this candidate working tree and the canonical baseline above.

| Gate | Observed result | Evidence |
|---|---:|---|
| Full repository suite | **789 tests; 0 failures; 3 skipped; exit 0** | `evidence/FULL_SUITE_R3_1.log` |
| Focused Python | **66 tests; 0 failures; exit 0** | `evidence/FOCUSED_AND_UI_R3_1.log` |
| Browser save-flow behavior | **9/9 PASS** | Same focused log |
| Python AST | **114/114 PASS** | `evidence/STATIC_CHECKS_R3_1.log` |
| Python compile | **114/114 PASS** | Same static log |
| JavaScript syntax | `app.js`, `memory-save-flow.js`, UI test — all PASS | Same static log |
| `git diff --check` | PASS | Same static log |
| Vietnamese synthetic curation corpus | **64/64 unique fingerprints; zero errors; precision/recall 1.00 for all five fixture classes** | `evidence/CURATION_VI_SYNTHETIC_EVAL_R3_1.json` |

The three full-suite skips are environment-dependent: two require hard-link creation and one requires root permission to `chown` another user. They are not counted as executed PASS tests.

### 3.1 Android ARM64 synthetic resource profiles

| Profile | Records | Comparisons evaluated | Findings of note | Peak RSS |
|---|---:|---:|---|---:|
| Same subject | 800 | 500 (bounded by finding/comparison behavior) | 500 conflict candidates; report truncated | 18.8 MiB |
| Distinct subjects | 800 | 500 | 500 cross-subject review candidates; report truncated | 19.0 MiB |
| Brain-like episodes | 800 | 20,000 | Zero conflict, near-duplicate or cross-subject findings | 18.2 MiB |
| Brain-like stress | 10,000 | 20,000 | Zero conflict, near-duplicate or cross-subject findings; report truncated | 29.2 MiB; 0.438 s analysis |

Raw JSON is in `evidence/BENCHMARK_*_R3_1.json` and `evidence/STRESS_BRAIN_10000_R3_1.json`. These are bounded synthetic workloads, not production SLAs. The distinct-subject profile intentionally surfaces up to the configured cross-subject review cap; these are review suggestions, not conflict verdicts or automatic merges.

### 3.2 Inherited R3 evidence

The R3 64-case corpus, 800-record profiles and 10,000-record benchmark remain part of the inherited R3 record. R3.1 re-ran the synthetic 64-case evaluation and all four resource profiles after the principal/unknown-outcome changes. No curation algorithm changes were made in R3.1.

## 4. K1–K8 disposition

The updated crosswalk is `R3_1_ACCEPTANCE_CROSSWALK_K1-K8.md`. K1–K3 and K6 retain their R3 implementation and are regression-covered by the 789-test full suite. K4 and K5 have the R3.1 credential-principal strengthening and preserve the legacy read path. K7 now includes the unknown-outcome/retry behavior. K8 has fresh exact-candidate logs, evaluation JSON and benchmark outputs.

## 5. Remaining assurance limits and handoff decision

1. The three platform skips remain open environment limitations; root/hardlink-capable validation was not performed on this Termux device.
2. Credential principal binding is not a federated or account-level identity system. The principal identifies possession of the configured local service credential; CLI saves identify the local Termux UID.
3. Vietnamese curation accuracy results are synthetic fixture metrics. Real/private user memory was not inspected.
4. **Independent re-review has not yet been performed.** STT's own adversarial examination and this implementation's tests are not an independent reviewer. The prior R3 rejection explicitly required an independent challenge before Integration Review closure.

**Handoff:** `ENGINEERING_REMEDIATION_COMPLETE / READY_FOR_INDEPENDENT_RE_REVIEW`. The R3.1 engineering remediation can be handed to an independent reviewer. **Do not label the Integration Review closed, merge, push, or deploy until an independent reviewer evaluates this exact R3.1 patch and the owner authorizes the next gate.**

## 6. Reproduction commands

```bash
cd "$HOME/HG-memory-continuity"
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v   hg.tests.test_ask_archive hg.tests.test_chat_service hg.tests.test_http_ui_chat
node --test hg/tests/test_memory_save_flow.js
node --check hg/ui/app.js
node --check hg/ui/memory-save-flow.js
git diff --check
```
