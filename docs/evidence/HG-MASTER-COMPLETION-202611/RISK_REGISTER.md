# Risk register — HG Master Completion V2.0 (updated 2026-11-19 23:35 +07)

| ID | Risk | Evidence | Status |
|---|---|---|---|
| R-01 | Android kills or freezes the Termux tree on the same boot and nothing restarts it. Production availability is ≥ 35 % over 118 h, with a 19.7 h outage on 11-19. | `RUNTIME_BASELINE.md` §3–4 | **OPEN P0**. Strategy B (JobScheduler guard) FAILED. Strategy A needs the owner's device settings. Strategy C is a single recovery entry point used by both the boot and manual paths. |
| R-02 | Termux:Boot autostart after a reboot is unproven. | §58, §59 | OPEN P1. Owner reboot test. |
| R-03 | L5 listener ownership is not provable as uid 10460 on Android 17 (`/proc/net` EACCES, hidepid). | §64; #205 l5 gate red | BLOCKED_WITH_TECHNICAL_EVIDENCE; accepted for v1 (D2). A scope analysis is pending. |
| R-04 | L3: the running Ollama 0.40.14 has integrity only (dpkg md5) and no current signed-index provenance. | `docs/evidence/HG-LISTENER-ATTESTATION-202611/L3_PROVENANCE.md` | BLOCKED. Candidate 0.40.16 has a signed-index digest; adopting it needs owner production approval. |
| R-05 | The UI could show the model as ready without listener ownership. | #204 fail-closed; Chromium check | Mitigated on #204, which is not yet merged. |
| R-06 | Trust root depends on GitHub (RT-06 fails closed). | §59 | Accepted by design |
| R-07 | G7 real-device Binder needs an APK and the signing key. | #197 | BLOCKED (owner) |
| R-08 | A second, unsupervised Desktop Commander remote runs from the shell (pid 4042) next to the runit one (2680). | `RUNTIME_BASELINE.md` F-P3-3 | OPEN P2. Owner's tool; do not kill it without the owner. |
| R-09 | 24 dirty worktrees hold unclassified work. | `WORKTREE_INVENTORY.csv` | PRESERVED; Phase 1 classification |
