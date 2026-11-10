# Android Broker CI Remediation — Isolated Workstream

**Recorded:** 2026-11-11 (Asia/Bangkok)
**Repository:** `OAI-GIANG/HG` only
**Worktree:** `~/HG-ANDROID-BROKER-CI`
**Branch:** `stt/hg-android-broker-ci-v1-20261111`
**Base HEAD:** `e465db2ef8143d013d6195abfa077f5010b3fd1c`
**Current state:** isolated implementation in progress; not yet built by Android CI; not merged or deployed

## 1. Preservation and source origin

The original source remains in `~/HG-GO-LIVE-CANDIDATE` on branch `stt/hg-go-live-certification-20261111`, HEAD `e465db2ef8143d013d6195abfa077f5010b3fd1c`. That candidate remains dirty and was only read.

The new worktree was created from the exact base commit above. The Broker source, workflow and architecture document were copied without overwriting the source candidate. Comparison against the original candidate's current source tree found 23 imported files: 17 remain byte-identical and six are intentionally changed in this isolated worktree. The original candidate status was re-read and remains unchanged by this work.

Source manifest: `CANDIDATE_ANDROID_BROKER_SOURCE.sha256`
Manifest SHA-256: `736a201126bdf5448ef357306a48f7b00898314a450303f36ae074aaf9a2a867`

The six intentional file changes are:

1. `app/build.gradle.kts`: remove unused instrumentation runner and unused AndroidX instrumentation dependencies; retain JVM JUnit tests.
2. `AndroidManifest.xml`: remove the unneeded Termux RUN_COMMAND permission request; the status Binder contract does not use it.
3. `BrokerStore.java`: preserve the precise fail-closed policy decision (e.g. `DENY_UID`) through the exception boundary, without disclosing caller signer or trust-store contents.
4. `settings.gradle.kts`: include a separate negative-caller probe APK module.
5. `hg-go-live-android-broker.yml`: replace the ineffective instrumentation invocation with an actual distinct-UID installed-app Binder negative-call workflow.
6. `HG_ANDROID_LISTENER_ATTESTATION_BROKER_V1.md`: append the remediation design, execution state and explicit Android/GO-LIVE limits.

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

The CI uses Gradle 9.9.1, JDK 17, Android Gradle Plugin 9.5.0, compile SDK 37 and Build Tools 36.0.0. Gradle 9.9.1 is selected instead of 9.9.0 because the 9.9.1 patch release contains security fixes. Android's AGP compatibility table supports API 37 and Gradle 9.6+ with JDK 17.

## 4. What this does and does not prove

**Not yet proven:** at the time of this report, the new workflow has not run. There is no APK build, signer report, emulator install, distinct-UID observation or negative Binder execution result from this branch. Termux does not have local Gradle, Java/JDK, Android SDK, ADB or emulator, so a local Android build cannot be performed here.

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
