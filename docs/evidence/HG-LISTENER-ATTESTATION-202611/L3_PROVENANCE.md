# L3 trust-anchor provenance for Ollama — device evidence 2026-11-19

Device: OPPO PKC110 / Android 17 / Termux, uid 10460. Commands were read-only, except one download into a private temp directory with no install: `~/hg-v1-evidence/l3-provenance-20261119/`.

## Running production binary — integrity only, provenance BLOCKED

- dpkg: `ollama` 0.40.14, aarch64, `install ok installed`.
- `$PREFIX/bin/ollama`: 40,344,880 bytes, mtime 2026-11-03 19:50.
  - sha256 `0d75e9393079e7cb751816393108a8d3e30a494509d788e4f87f570e5f71beff`.
  - md5 `4668cd1d6bf662b1cd4d88b19ae15d0a`, which equals the entry in dpkg `ollama.md5sums`. So the file has not changed since dpkg installed it.
- Limits:
  - md5 is weak, and the md5sums file is writable by the same uid. Same-uid attackers are out of scope (Q3).
  - The signed index (`mirror.albony.in` termux-main, InRelease fetched 2026-11-17 21:17 +07) now lists **0.40.16**, so 0.40.14's `.deb` hash cannot be checked against it.
- **Result: L3 for the running binary = BLOCKED.** No signed-index provenance exists for 0.40.14, and no digest was invented.

## Provenance-backed candidate (0.40.16) — CANDIDATE, not adopted

- `apt-get download ollama` → `ollama_0.40.16_aarch64.deb`, 13,771,144 bytes.
  - sha256 `66b5ec8b7888a58c514512385f3bb96f8c63b9055387ec5d01c8d6a2fc424005`.
  - This equals `SHA256:` in the Packages index, which apt authenticates through the signed InRelease.
- `dpkg-deb -x` → `usr/bin/ollama` sha256 **`5809c69d353790138373fca6cc5f22c847f0333dfb7ffe65189b4cb94fc6159f`**.
- Chain: Termux repository signing key → InRelease → Packages SHA256 → `.deb` → extracted binary.

## Closing L3 (owner decisions required)

1. Upgrade Ollama to the indexed version. This changes the production model runtime, so it needs production approval and a staging rehearsal first: J1, model digest and pinned-model checks.
2. Record the provenance-backed digest in `hg/assistant/trusted_runtimes.json`. This is a trust-registry change: owner-approved and versioned, with its own PR.
3. Re-run the attestation; the running binary's sha256 must equal the recorded digest.

Until then, L3 stays BLOCKED, and so do L5/RT-06 (§64).
