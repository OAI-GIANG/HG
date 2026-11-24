# AC-A6 v11 one-time evaluation

The evaluator returned **PASS** in its only run. **AC-A6 remains FAIL and production remains NO-GO.**

- Candidate `40254e60802bc59e40cd739d6ae4081241af4acd` was evaluated from its isolated checkout on Android ARM64 / Termux Python 3.14.8 with pinned Ollama `qwen3:1.7b` (digest `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`).
- The independent synthetic dataset was frozen remotely at `9421fdbd7b67c7689176bd8c105dc427ebab0f82` before the run. Input SHA-256 `e57d4354b996f6bcb35ca1fc60088c9176f006401bdf937b8b32e958faf9b2f8`.
- The single attempt started at `2026-11-24T12:20:45Z` and ended at `2026-11-24T12:22:55Z` with exit code `0`. The complete per-question scores, answers and labels are in [results.json](results.json).
- Raw report SHA-256 `04db24e7bb38b3eb4835c166f38fa98de39b21450af9515f8218f12e240cdec9`. Run log SHA-256 `9b2492ef5b87afbb7287f50634a6e63d5db80eb95a607b43a915fe39d04cb81f`. Raw files and checksums are held on the owner device. The published report omits device-local model metadata and paths.
- The listener status observed for the model was `VERIFIED_PROCESS`.

| Measure | Observed | Original requirement | Result |
| --- | --- | --- | --- |
| Fact | 32/34 (0.941) | ≥ 0.80 | PASS |
| Grounded | 29/34 (0.853) | ≥ 0.70 | PASS |
| Abstain | 14/14 (1.000) | ≥ 0.80 | PASS |
| Injection followed | 0 | 0 | PASS |
| Notes shown max | 0.042 s | ≤ 2 s | PASS |
| First sentence p50 | 3.642 s | ≤ 15 s | PASS |
| Model failures | 0 | 0 | PASS |

## Qualification and recovery

- Exact-head CI passed all 10 checks, including Python 3.13/3.14. The check identifiers are in [exact-head-ci.json](exact-head-ci.json).
- On Android, all six command groups exited 0. The targeted suite passed all 12 tests, HG ran 1,132 tests with 3 skips, MAEP ran 385 tests with 3 skips, and hooks passed all 42 tests. Selfcheck and bench passed. Platform skips cover hard-link support and the root-only ownership case covered by GitHub CI. The Android checksum manifest SHA-256 is `33b9a2d3a266e09e1aebf6508862c49a5855205fc1c9dd86b1c2539d7c3d4808`.
- PR #217 remains open and draft. Its v10 raw checksums passed on the device, but the prior RDC command still lacks a confirmed terminal status. Evidence PR #217 and candidate PR #219 remain separate. Recovery `recovery/stt-pre-pr217-20261124` points to `4e02d62cb8e48bb4cc958be322727b91efae6e88`.
