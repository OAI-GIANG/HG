# Android Broker technical audit — checkpoint V3-CP01

**Candidate source:** `~/HG-GO-LIVE-CANDIDATE/android/cim-broker`
**Disposition:** Prototype source only; not APK-qualified; G2/G7 BLOCKED.

## What exists

The candidate contains a Java Android application module with:
- exported ContentProvider that checks the kernel Binder caller UID;
- package name and pinned signer checks for Termux;
- owner pairing/revoke screen;
- read-only status response;
- a fail-closed inference adapter;
- AF_UNIX client code using Android LocalSocket peer credentials;
- socket path owner/mode/inode checks;
- process handle/PID/UID checks;
- request ID, nonce and request digest envelope;
- runtime/model anchor assets initially empty.

The source inventory is about 1,274 Java lines. No successful Gradle build, APK digest, signer verification, install, actual distinct UID proof, or real Binder negative test has been captured.

## Concrete blockers / design gaps

1. `trusted-runtimes.json` and `trusted-models.json` contain empty arrays.
2. `BrokerModelAnchor.isApproved()` deliberately returns false, including when a matching entry is encountered; local inference cannot proceed.
3. `BrokerRuntimeAnchor` requires signed-APK-protected runtime metadata and a matching binary digest. No qualified Ollama runtime entry exists.
4. `BrokerOllamaSupervisor` sets `OLLAMA_SOCKET_PATH` and starts Ollama. The candidate provides no patched Ollama server implementation that demonstrably consumes this variable and binds the AF_UNIX socket. Do not assume the stock 0.40.14 build does so.
5. `BrokerUnixSocketClient` requires response correlation headers `x-hg-request-id`, `x-hg-request-nonce` and `x-hg-request-sha256`. No corresponding server-side response echo/validation path is present in the candidate module.
6. The response SHA-256 is calculated for audit output; the complete expected-response integrity/correlation contract is not yet independently enforced.
7. `BrokerOllamaProcessLiveness` checks Java Process handle liveness, PID and UID; no actual Android pidfd/PID-reuse race qualification has been captured.
8. `setInferenceEnabled()` has no owner-facing activation path in MainActivity. This keeps inference disabled, but practical operation is absent.
9. The Android manifest requests `com.termux.permission.RUN_COMMAND`, while the candidate source does not use the Termux RUN_COMMAND API. Remove unnecessary permissions before qualification.
10. The workflow's emulator job installs only the debug APK and then invokes `am instrument`; it does not build/install the androidTest APK or run Gradle's connected instrumentation task. No `src/androidTest` source was found in the candidate at this checkpoint.

## Build / device constraints

Termux has no local Gradle, Java, Android SDK, adb or emulator in PATH. GitHub Actions is available, but the candidate workflow is uncommitted and unrun. An x86_64 emulator workflow would provide build/test evidence only; it cannot substitute for the required physical Android 17 ARM64 distinct-UID/Binder and L1/L5 acceptance.

## Security disposition

The empty trust anchors and blocked inference path are appropriate fail-closed behavior. Do not populate them or relax the checks to make the APK appear operational. G7 remains BLOCKED until a signed APK and real positive/negative separate-UID Binder evidence exist; G2 remains BLOCKED until actual Android L1/L5 identity/listener evidence is complete.
