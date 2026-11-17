# Probe v3 — Termux evidence (2026-11-06)

This evidence was produced from an isolated candidate copy of PR #77 head 90c106967d24f4ff754fb0325f1a4a28fa8ad42b, before the candidate patch was pushed.

## Environment

- Termux on Android 17 / runtime SDK 37, arm64-v8a.
- Python 3.14.8, sys.platform=android, build-time API level 24.
- Python does not expose os.pidfd_open because Android support in the Python API is gated at build-time API level 31.
- The candidate uses raw syscall 434 (pidfd_open) only on aarch64/x86_64 when the wrapper is absent, and only after the disposable-child capability check. Syscall 438 (pidfd_getfd) remains behind the same disposable-child SIGSYS-safe capability probe.
- Both raw syscalls succeeded in the disposable self-process capability test; the attestor reports PASS/AVAILABLE.

## Verification

- test_l5_probe.py: 12 tests run, 11 PASS, 1 SKIP (Yama-specific case; this device does not expose ptrace_scope=1).
- Focused test_attest.py fallback/capability tests: 5 PASS.
- L5 probe self-test: PASS, 12/12 checks.
- Synthetic child target-mode tests: owned listener, wrong-port rejection, duplicate-descriptor handling all passed.

## Limits

- The raw syscall result is self-process capability evidence, not proof that the actual Ollama service process is accessible.
- Actual Ollama target PID, production service, trust-anchor provenance, benchmark, and end-to-end five-layer attestation were not run.
- trusted_runtimes.json remains empty. L3 and overall VERIFIED remain blocked/unverified.
- JSON evidence is a redacted projection; raw temporary outputs were not committed.
