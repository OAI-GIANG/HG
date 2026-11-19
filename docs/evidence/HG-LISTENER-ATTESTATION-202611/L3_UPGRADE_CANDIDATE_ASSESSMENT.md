# L3_UPGRADE_CANDIDATE_ASSESSMENT — Ollama 0.40.16 vs production 0.40.14 (staging, 2026-11-20)

Owner decision VI (2026-11-19 23:53): assess in staging only. No `pkg upgrade`, no `dpkg -i`, no production binary change.
Script: `~/hg-v1-evidence/l3-staging-assess-20261120.sh`. Evidence: `~/hg-staging-l3-ollama-20261120/ev/` (`l3.log` sha256 `d2817ed2…`).

Staging was isolated:
- its own HOME;
- a copy of the model store (1.3 GB, copied in 2 s);
- port 11535;
- `OLLAMA_NOPRUNE=1`.

| Check | 0.40.16 (candidate) | 0.40.14 (production binary, staging run = rollback check) |
|---|---|---|
| Provenance | `.deb` sha256 `66b5ec8b…` = signed Packages index. Binary `5809c69d…` = recorded | dpkg md5 only; not in the current signed index |
| Binary | ELF64 AArch64 (header `7f454c46 0201 01 … b700`), 40,653,008 B; libraries resolved at run time | ELF64 AArch64, 40,344,880 B |
| `/api/version` | `0.40.16`, ready in 1 s | `0.40.14`, ready in 1 s |
| Model tag / digest | `qwen3:1.7b`, 1,359,293,444 B, digest `8f68893c…30e7` (= production pin) | same |
| Inference (temp 0, seed 7, `think:false`) | HTTP 200; cold 4.77 s, warm 0.61 s; "Một tuần có 7 ngày." | HTTP 200; cold 4.80 s, warm 0.58 s; same answer |
| RAM (server tree RSS, model loaded) | ≈ 1.84 GB | ≈ 1.84 GB |
| Model store reused after the other version served it | — | yes (rollback works on the same store) |
| Disk | binary +308 KB vs 0.40.14; model store unchanged | — |
| Shutdown | TERM, stopped in 1 s | TERM, stopped in 1 s |

Production before/after: identical (`prod-diff.txt` empty, sha256 `e3b0c442…`).

**Assessment: QUALIFIED for a production upgrade decision.**
- Nothing differs in function, latency or memory.
- The model digest is unchanged.
- Rollback to 0.40.14 is shown on the same model store.

**What the upgrade would give:** L3 provenance tied to the signed Termux index (`5809c69d…`). L3 alone does not close L5/RT-06, which stays BLOCKED (§64).

**Decision for the owner (separate):**
- Approve or refuse `apt install ollama=0.40.16` on production. This needs a maintenance window, then `sv restart ollama`, then a J1 check.
- Approve or refuse recording `5809c69d…` in `hg/assistant/trusted_runtimes.json`, in its own PR.

The staging copy `~/hg-staging-l3-ollama-20261120/` (1.3 GB) is kept until the owner decides.
