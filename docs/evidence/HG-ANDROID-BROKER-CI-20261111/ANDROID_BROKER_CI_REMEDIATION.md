# Android Broker CI Remediation — Isolated Workstream

**Recorded:** 2026-11-11 (Asia/Bangkok)
**Repository:** `OAI-GIANG/HG` only
**Worktree:** `~/HG-ANDROID-BROKER-CI`
**Branch:** `stt/hg-android-broker-ci-v1-20261111`
**Base HEAD:** `e465db2ef8143d013d6195abfa077f5010b3fd1c`
**Current state:** SDK provisioning verified in GitHub Actions; first Android compile exposed inherited source errors; remediation in progress; not merged or deployed

## 1. Preservation and source origin

The original source remains in `~/HG-GO-LIVE-CANDIDATE` on branch `stt/hg-go-live-certification-20261111`, HEAD `e465db2ef8143d013d6195abfa077f5010b3fd1c`. That candidate remains dirty and was only read.

The new worktree was created from the exact base commit above. The Broker source, workflow and architecture document were copied without overwriting the source candidate. Comparison against the original candidate's current source tree found 23 imported files: 14 remain byte-identical and nine are intentionally changed in this isolated worktree. The original candidate status was re-read and remains unchanged by this work.

Source manifest: `CANDIDATE_ANDROID_BROKER_SOURCE.sha256`
Manifest SHA-256: `736a201126bdf5448ef357306a48f7b00898314a450303f36ae074aaf9a2a867`

The nine intentional file changes are:

1. `app/build.gradle.kts`: remove unused instrumentation runner and unused AndroidX instrumentation dependencies; retain JVM JUnit tests.
2. `AndroidManifest.xml`: remove the unneeded Termux RUN_COMMAND permission request; the status Binder contract does not use it.
3. `BrokerStore.java`: preserve the precise fail-closed policy decision (e.g. `DENY_UID`) through the exception boundary, without disclosing caller signer or trust-store contents.
4. `settings.gradle.kts`: include a separate negative-caller probe APK module.
5. `hg-go-live-android-broker.yml`: replace the ineffective instrumentation invocation with an actual distinct-UID installed-app Binder negative-call workflow.
6. `HG_ANDROID_LISTENER_ATTESTATION_BROKER_V1.md`: append the remediation design, execution state and explicit Android/GO-LIVE limits.
7. `BrokerOllamaProcessLiveness.java`: replace unavailable Android `Process.getUidForPid()` and direct `Process.pid()` calls with reflection fail-closed PID discovery and kernel procfs owner checks.
8. `BrokerOllamaSupervisor.java`: consume the fail-closed process-handle PID helper and stop if it cannot bind the spawned process.
9. `BrokerRuntimeAnchor.java`: expose package-local SHA-256 hex validation for use by the model anchor without duplicating validation logic.

## 2. Findings corrected

The copied workflow was not sufficient for Binder qualification:

- `src/androidTest` was empty.
- The emulator job installed only the Broker APK.
- The job called `am instrument` directly, without building/installing an instrumentation APK.
- It did not install a real Termux package or verify actual Termux/Broker UID separation.
- It did not demonstrate a Binder call from a different Android application UID.

The new workflow does not misrepresent a JVM unit test as a device Binder test.

## 3. New probe and unit coverage

A separate application module, `probe`, installs as package `org.hg.cim.broker.probe`. Its Activity invokes the exported Broker `ContentProvider.call("status")` through Android Binder from its own package process. It only passes the negative test when the provider returns the precise `DENY_UID` decision. Unexpected success or an unrelated denial is FAIL/INCONCLUSIVE, not PASS.

The emulator job is designed to:

1. Download the pinned F-Droid Termux 0.118.3 package (version code 1002).
2. Verify APK package identity and the F-Droid signer SHA-256 pinned in BrokerStore.
3. Install Termux, Broker and the separate probe app.
4. Read each installed package UID from Android PackageManager output and require all three to be different.
5. Launch the Broker owner-pairing UI and perform the explicit Termux trust confirmation in the emulator.
6. Read back the Broker-private pairing preferences and verify the expected Termux UID was paired.
7. Launch the probe app; require an actual Binder call to be denied specifically as `DENY_UID`.
8. Save the Termux APK digest, UID evidence and probe log as CI artifacts.

The Broker unit suite gains tests for exact peer UID/PID acceptance, wrong UID/PID rejection, invalid peer rejection, request ID/nonce/digest correlation, malformed response digest refusal, request envelope byte binding, and empty/oversized request rejection. The independent probe package is not granted Broker permissions and does not spoof Binder identity.

The CI uses Gradle 9.9.1, JDK 17, Android Gradle Plugin 9.5.0, compile SDK 37 and Build Tools 37.0.0 (Android 17 preview channel). Gradle 9.9.1 is selected instead of 9.9.0 because the 9.9.1 patch release contains security fixes. Android's AGP compatibility table supports API 37 and Gradle 9.6+ with JDK 17.

## 4. What this does and does not prove

**Not yet proven:** the workflow has reached the Android build stage, but the first Java compilation failed (Run #4; see Section 10). There is still no APK build, signer report, emulator install, distinct-UID observation or negative Binder execution result from this branch. Termux does not have local Gradle, Java/JDK, Android SDK, ADB or emulator, so a local Android build cannot be performed here.

Even after the emulator workflow passes, it will establish only emulator negative-caller behavior. It does not prove:

- a positive Binder call from the real installed Termux process;
- the OPPO PKC110 physical device's actual app UID and installed Termux signer;
- physical-device Broker installation, package UID isolation and Binder positive/negative behavior;
- Android L1/L5 full process/listener isolation on the real device;
- production-grade Broker signing/release keys;
- a qualified model/runtime trust anchor or working Broker inference.

The runtime/model anchor assets remain empty. `BrokerModelAnchor.isApproved()` intentionally fails closed, and the inference path is not enabled by the UI. No model inference is claimed or enabled.

## 5. Gate impact

- **G7 — PARTIAL / awaiting CI:** workflow and real cross-UID negative-call probe are implemented in an isolated branch; actual emulator evidence is pending. Physical positive Binder caller and OPPO-device proof remain required before G7 can PASS.
- **G2 — BLOCKED:** this work does not close the real-device L1/L5 process namespace and complete listener-sharing observation.
- **G5 — BLOCKED:** the empty Broker/runtime trust anchors remain empty; no runtime was promoted.
- **G8 — BLOCKED:** no production model inference or end-to-end agent/tool transaction is qualified.
- **GO-LIVE: NO-GO.**

## 6. Safety

No production Runtime/Ollama lifecycle operation, inference, data migration, release-pointer change, trust-anchor edit or production data access occurred. The original candidate, the Memory Continuity port and the V3 execution worktree were not modified by this Broker worktree. No external permission, UID or signer was spoofed.

## 7. External source provenance

- F-Droid lists Termux 0.118.3, version code 1002, and identifies the APK as F-Droid built/signed: https://f-droid.org/packages/com.termux/
- F-Droid's reproducibility page reports Termux 1002 / 0.118.3 as reproducible: https://verification.f-droid.org/packages/com.termux/
- Android Gradle Plugin 9.5 compatibility reference: https://developer.android.com/build/releases/gradle-plugin
- Gradle 9.9.1 release/security notes: https://gradle.org/releases/

External pages establish package/version/build-tool context only; they do not replace the actual CI execution evidence.


## 8. CI execution history and remediation

### Run #1 / initial push

GitHub Actions run `42895305112` (commit `5bb0ce0686a18b4c2cde28089796f34e59b85215`) failed in the `android-actions/setup-android@v3` step before Gradle build. The runner's preinstalled command-line tools were detected, but the action attempted to install the obsolete SDK package `tools`; `sdkmanager` returned `Failed to find package 'tools'`. No Broker or probe APK was built, and no Android security test ran.

### Run #2 / first hosted-SDK direct invocation

GitHub Actions runs `42895661350` (push) and `42895672476` (pull_request), on commit `6378345c288d01534390ad59b30a4210a5e04b93`, failed at the SDK installation step before build. The runner log confirmed the Android SDK root and the preinstalled command-line tools path, but the SDK manager directory was not in PATH; `command -v sdkmanager` was empty and the guarded step exited 1. No APK was built and no Binder call was attempted.

### Current correction

The workflow now resolves the SDK manager by the verified hosted-runner path `$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager`, with a version-sorted fallback search beneath `$ANDROID_HOME/cmdline-tools`. It invokes the resolved executable directly. This change is being pushed in a new commit so CI can test the correction. The prior failures are retained as evidence and are not counted as successful tests.

**Qualification state remains PENDING.** A new successful build/unit job is required before the emulator job can begin; final emulator negative Binder proof remains separate and still does not establish physical OPPO device behavior or positive Termux caller behavior.


## 9. Run #3 — API 37 package identifier correction

GitHub Actions run `42895882025`, job `130108783841`, commit `717b4cbac0d1632fc8d6887aed984d8eda50da13` failed during SDK provisioning. The runner resolved the SDK manager successfully this time, but `sdkmanager` returned `Warning: Failed to find package 'platforms;android-37'`. Gradle, APK build and emulator steps were skipped.

The Android 17 preview package is identified by the SDK package name `platforms;android-37.0` (not `platforms;android-37`). This distinction is confirmed in SDK package documentation and tooling guidance. The workflow is corrected to request preview channel 3 with:
- build job: `platforms;android-37.0` and `build-tools;37.0.0`;
- emulator job: `build-tools;37.0.0`, `platform-tools`, `emulator`, and `system-images;android-35;google_apis;x86_64`.

The build job creates a local SDK path alias `platforms/android-37` pointing to the installed `platforms/android-37.0` directory to accommodate Gradle tooling that checks the compile SDK directory by API number. The emulator job does not download API 37 a second time because it runs an API 35 image and only needs the build/ADB/emulator tools.

**Run #3 is a provisioning failure, not a code or test failure. No APK was built and no Binder call was made. The corrected workflow has not yet been executed at the time of this report.**


## 10. Run #4 — SDK provisioning passed; Java/Android source compile exposed inherited API errors

GitHub Actions Android workflow run `42896286339` (commit `7d6749795b515676028cb9ced418b37286d7d33a`), build job `130110151825`, successfully completed Android SDK provisioning. The build then reached `:app:compileDebugJavaWithJavac` and failed with six compiler errors in three source files:

- `BrokerOllamaProcessLiveness.java`: `java.lang.Process.pid()` is not present in the selected Android compile API, and `android.os.Process.getUidForPid(int)` is not exposed as a public SDK method.
- `BrokerOllamaSupervisor.java`: direct use of `java.lang.Process.pid()` fails for the same reason.
- `BrokerModelAnchor.java`: calls `BrokerRuntimeAnchor.hex64(String)`, but the validator was private.

No APK was produced; APK signer checks and emulator/Binder steps were skipped. This was an actual Java compile failure, not an SDK provisioning failure.

### Remediation

- `BrokerOllamaProcessLiveness.pidOf()` now obtains `java.lang.Process.pid()` reflectively. If the runtime does not expose it, the method returns invalid PID and the supervisor refuses to start/qualify that child. This is intentionally fail-closed.
- UID observation now uses `android.system.Os.stat("/proc/<pid>").st_uid`, which is a public Android API; it samples while the same `ProcessBuilder` handle is alive and rechecks liveness, PID and procfs UID after the observation. Any permission or procfs error refuses qualification.
- `BrokerOllamaSupervisor` uses the new PID helper and stops/refuses when the PID cannot be bound to the returned process handle.
- `BrokerRuntimeAnchor.hex64` is package-visible so `BrokerModelAnchor` can reuse the same digest validator.
- Added JVM tests for null process PID handling, PID discovery from a real host process handle, and digest validation.

The Android SDK's public `android.os.Process` reference does not expose `getUidForPid`; Android's AOSP implementation marks it hidden. The Java `Process.pid()` surface is documented separately and can be absent on older Android runtime levels. The reflection path therefore preserves compilation across the supported SDK and fails closed when the runtime cannot expose a PID.

**Run #4 is FAIL at Java compilation. No Binder call was run.** The source remediation is uncommitted at this note and will be pushed as a new commit for CI re-verification. Even a later compile/emulator pass would not demonstrate physical OPPO behavior or positive Termux Binder use.


## 11. Run #11 — Broker APK build passed; Termux signer pin check stopped before emulator

GitHub Actions PR run `42896994761` (workflow run #11) on the PR merge ref `8200c951eb47c0db5c26136c096155fd31f295a4`, build job `130112604424`, completed **SUCCESS**:

- Android SDK provisioning succeeded.
- Gradle `:app:testDebugUnitTest`, `:app:assembleDebug`, and `:probe:assembleDebug` completed; overall `BUILD SUCCESSFUL in 1m 12s`.
- APK verification succeeded for both APKs using APK Signature Scheme v2.
- Package identities were verified:
  - Broker: `org.hg.cim.broker`, version 1.0.0, compile SDK 37 / Android 17.
  - Negative-caller probe: `org.hg.cim.broker.probe`, version 1.0.0, compile SDK 37 / Android 17.
- Both CI debug APKs were signed by the same temporary debug certificate, SHA-256 `a5115d7a71ea6614c6e5dc2dc777b9f06335a56eddb1b8c5b43715eed2a10785`, public-key SHA-256 `10248189d8971b02ba69fae9a14f5723e188a19227f530fdb638b9cea5c0d532`.
- Uploaded Broker build artifact ZIP SHA-256: `04ef74b1a7879f3244c76935dae489373236f4795c51b696ac9343a9a23e3bc6`.

The dependent emulator job `130113482625` provisioned the emulator SDK and downloaded the pinned Termux F-Droid APK (108.6 MiB), but stopped in the signer-verification step before installing any APK. The workflow captured the signer command output into a shell variable, and only the equality test's exit status was observable; the exact apksigner output and observed fingerprint were not persisted. The job therefore did **not** establish that the pinned certificate was wrong, only that the current check did not pass.

No Termux, Broker or probe package was installed in the emulator. No PackageManager UID observation, Broker owner pairing, Binder call, or negative-caller result exists from Run #11.

### Run #11 remediation

The workflow now:
- captures full `apksigner verify --verbose --print-certs` stdout/stderr in `termux-apksigner-output.txt`;
- checks the apksigner exit code explicitly;
- parses the SHA-256 certificate fingerprint from the captured evidence;
- prints both expected and observed fingerprint values;
- requires a non-empty observed digest and an exact match to the already pinned F-Droid signer;
- stores the apk badging, APK SHA-256, apksigner output, and any later emulator UID/Binder logs as workflow artifacts even on failure.

The trusted signer pin is intentionally unchanged until the observed output is independently inspected. The uploaded debug Broker APK certificate is not the F-Droid Termux certificate and must not be confused with it.

**Disposition:** Broker build/unit job PASS; Termux signer verification not qualified; emulator install/UID/Binder tests SKIPPED. G7 remains PARTIAL/BLOCKED for the unexecuted cross-UID Binder/physical-device requirements. GO-LIVE remains NO-GO.
