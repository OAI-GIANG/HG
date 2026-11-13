# HG CIM Android Broker

Experimental Android package providing a distinct-UID Binder ContentProvider boundary.

## Current surface

The provider exposes exactly one method:

    content call --uri content://org.hg.cim.broker.ipc --method status

The call succeeds only after the owner explicitly pairs the installed Termux package in the broker UI. On every Binder call the broker checks:
- Binder caller UID;
- currently installed Termux package UID;
- complete packages-for-UID set (must contain only com.termux);
- current APK signer SHA-256 set;
- owner-pinned UID and signer set in broker-private preferences.

The provider has no query, insert, update, delete, file-descriptor or mutating capability. It does not expose broker-private files.

## Build

The workflow pins:
- Android Gradle Plugin 9.5.0;
- Gradle 9.9.0;
- JDK 17;
- compileSdk 37;
- SDK Build Tools 37.0.0 (installed from SDK channel 3 by the workflow).

Run from this directory with a compatible Android SDK installation:

    gradle --no-daemon testDebugUnitTest assembleDebug

The GitHub Actions workflow builds the debug APK and uploads it as an artifact. It does not install or deploy the APK.

## Device pairing and smoke test

1. Install the debug APK through Android's package installer.
2. Launch HG CIM Broker.
3. Inspect Termux package version, UID and full signer SHA-256.
4. Explicitly select "Trust this installed Termux".
5. Call the provider **from a process running as the Termux app UID**. Plain `content call` typed in Termux does not work: `/system/bin/content` asks the activity manager for `getContentProviderExternal()`, which needs `android.permission.ACCESS_CONTENT_PROVIDERS_EXTERNALLY` (granted to the shell, not to apps). On the owner's phone (Android 17, Termux UID 10460, 2026-11-13) it fails with `SecurityException ... requires android.permission.ACCESS_CONTENT_PROVIDERS_EXTERNALLY`. Run over `adb shell`, the call comes from the shell UID, not from Termux, so it does not test the Termux pairing either. **The repository has no Termux-side client yet, so the positive real-device check (G7) is BLOCKED.**
6. Once such a client exists: confirm the response has authenticated=true, caller UID equal to Termux UID, and broker UID different from Termux UID.
7. Revoke pairing in the app and repeat the call; the provider must deny it.

The negative check (another app UID is denied) uses the `probe` APK. CI runs it on an emulator (`android/cim-broker/ci/emulator_negative_binder.sh`).

The broker must not be paired automatically on first launch.

## Limits

- Debug APK uses a CI debug signing identity; it is not a production release.
- Pairing is owner-confirmed trust-on-first-use for the installed Termux package signer.
- Current broker only establishes a read-only caller identity handshake.
- No MAEP action execution, owner authorization receipt, artifact access or database operation is exposed.
- Do not interpret an authenticated status handshake as authorization to perform a capability.
- The broker is a separate app UID boundary but does not protect against root/kernel compromise.
