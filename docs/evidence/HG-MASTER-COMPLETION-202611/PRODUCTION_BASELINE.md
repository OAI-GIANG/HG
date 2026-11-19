# Production baseline — read-only, 2026-11-19 23:24 +07

Collector and evidence location: see `RUNTIME_BASELINE.md`. Production was not started, stopped, switched or written in this session.

## Verdict: UNCHANGED vs ledger §56/§57 (pointer and shim hashes equal)

| Item | Observed |
|---|---|
| Service | `hg-runtime` run, pid 2682, `python3 -B -u -m hg serve --config …/runtime-service-030a88d5….json` |
| Release | `030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5`, port 18766, state `~/.local/share/hg/runtime-service-state` |
| READY line | `2026-11-19_15:45:44Z HG_RUNTIME_READY … release_id=030a88d5…` |
| `assistant-release` sha256 | `6739742c…` (= §56/§57) |
| `$PREFIX/bin/hg` shim sha256 | `d17b5c0c…` (= §56/§57) |
| `hg-runtime/run` | `50a162a7…` |
| `hg-runtime/finish` | `c200ca09…` |
| `ollama/run` | `ecbd836c…` |
| Ollama | pid 2679, package `ollama` 0.40.14 aarch64; binary sha256 `0d75e939…`, md5 equal to dpkg `ollama.md5sums` |

Production RF-1 liveness is not deployed: 030a88d5 predates #198. Downtime therefore comes from svlogd rotation files. Each `.u` file is a supervisor life that was cut uncleanly.

## L3 provenance of the running Ollama (summary)

Details: `docs/evidence/HG-LISTENER-ATTESTATION-202611/L3_PROVENANCE.md`.
- Running binary: 0.40.14. Integrity matches dpkg md5sums. Provenance cannot be tied to the current signed index, which now lists 0.40.16. **L3 for production: BLOCKED.**
- Candidate 0.40.16: digest backed by the signed index. Adopting it requires an Ollama upgrade, which is a production change and needs owner approval.
