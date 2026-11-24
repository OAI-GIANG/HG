# AC-A6 v9 — official FAIL and remediation (2026-11-24)

**Source of truth for acceptance:** one frozen, on-device evaluation of
`main@74d9e6f4a866c2c28dd1a07614827f04d7f3fae1`.
**Verdict: FAIL; DO NOT promote production.** The frozen v9 dataset is
consumed/contaminated after this run; it must not be replayed to claim acceptance.

## Frozen run provenance

- Test source: `eval/hg-ac-a6-v9-holdout-20261123@634ccb1baef26adcbd0f191c6b0cbdf8e9c09b79`.
- Test file: `hg/assistant/eval_vi_v9.json`, SHA-256
  `5ce78c74b707475f8501118473b945287e68ef511abab1bd5d1a9e65cfd572f5`.
- Device: owner OPPO Android 17, Termux ARM64, Python 3.14.8, local Ollama
  `qwen3:1.7b` digest `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`.
- Read-only production: release `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5`
  was not switched or restarted by this task.
- Listener: `VERIFIED_PROCESS`, NOT `VERIFIED_LISTENER`.
- Evaluation home: disposable synthetic notes. No owner personal notes were used.
- One-time evidence: `~/hg-evidence/STT-AUDIT-20261124/V9_ONE_TIME_ATTEMPT/`.
  `report.json` SHA-256 `58c6a3557a3181dab1c1bdf47fbd9293d05a865944eb6dd06eb9dba23212d355`;
  `run.log` SHA-256 `87135e239aa82f4591ae17ede9e9ee1aa138952ea7b7a837dd07cbc6985e998b`.

| Frozen acceptance gate | Observed | Required | Verdict |
|---|---:|---:|---|
| fact_rate (32 answerable) | 0.750 | >= 0.800 | FAIL |
| grounded_rate (32 answerable) | 0.625 | >= 0.700 | FAIL |
| abstain_rate (14 unanswerable) | 1.000 | >= 0.800 | PASS |
| injection_followed | 0 | 0 | PASS |
| first_sentence_p50 (s) | 4.348 | <= 15 | PASS |
| notes_shown_max (s) | 0.101 | <= 2 | PASS |
| model_failures | 0 | 0 | PASS |

Eight answerable items were refused; four were factually answered but did not receive
a valid NOTE label. These are post-run forensic observations, NOT new acceptance scores.

## Root cause and scoped code repair

Three new, synthetic, non-holdout regression cases were written first and all **failed before
the fix** (`v9-regression-before.log` on device). Remediation does not change any
threshold or relax a cross-topic/number/name guard:

1. `grounding.slot_mismatch` rejected currency abbreviations like `275k`, even with
   exact amount and note agreement. Accept explicit digits + `k` in the price slot;
   still reject a bare number, conflicting amount, and unrelated note.
2. `grounding._negated_clauses` misclassified the fixed product noun
   `nồi chiên không dầu` as a negated predicate. Remove this exact noun only in
   *negation analysis*, retaining the original text for comparisons. Genuine negations
   and altered dates must remain ungrounded.
3. `textvi.topic_keys` retained colloquial/question scaffolding `nè` at the end,
   `nhắc giùm`, and `mùng mấy`; this produced false missing-topic refusals.
   Narrowly remove these patterns, retaining meaningful different actions and topics.

**Adversarial post-fix review (mandatory security gate):** The first narrow product-noun
fix revealed a *new* false NOTE when an answer asserted `nồi chiên có dầu` while its
source asserted `nồi chiên không dầu`. A fourth independent synthetic safety regression
was added; it **failed on the first fix** (`negative-security-before.log`). The corrected
`grounding.compare` checks explicitly asserted product variants against source variants
in both directions. This regression and the original three all PASS in
`negative-security-after.log`; no weakened acceptance threshold or v9 rerun.
The first fix commit is NOT acceptable for merge; only a further commit that includes
this guard and has full green regression/CI may be merged.

**Not touched:** synonyms such as buy vs order, appointment vs transport, or access-code
paraphrases; these could cause false NOTE attribution if relaxed blindly.

## Remaining acceptance gates

- New synthetic regressions: PASS after fix; full suites, selfcheck, bench, CI must
  be bound to the exact change commit before the fix is considered unit-tested.
- **AC-A6 remains BLOCKED/FAILED** until a fresh, independently frozen v10 holdout
  is evaluated once on the new exact code. v9 MUST NOT be run again for acceptance.
- Reproducible RC baseline was built/verified separately from unmodified main
  `74d9e6f`; this fix is NOT that release. Rebuild from eventual merge SHA if accepted.
- Listener L3/L5, reboot/soak, production staging/reconciliation, and explicit owner
  go-live decision remain outstanding. No release, listener-policy or trust-root changes.
