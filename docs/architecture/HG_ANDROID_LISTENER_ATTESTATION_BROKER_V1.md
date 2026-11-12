# HG — Android-specific Listener Attestation and Local Model Broker V1.0

Status: DESIGN BASELINE / NOT IMPLEMENTED / NOT ACCEPTED FOR PRODUCTION

Repository: OAI-GIANG/HG
Platform: Termux on Android ARM64
Governance: MAEP + MTC-1.0
Owner architecture alignment: B_LOCAL_BROKER_SEPARATE_UID

## 1. Decision

Do not weaken L1 or L5 to turn Android BLOCKED into PASS.

The immediate code candidate classifies unavailable /proc/<pid>/ns/pid as BLOCKED/PIDNS_UNAVAILABLE. This is an error-classification correction only. It is not an alternate proof and does not authorize model-call integration or production deployment.

The production direction is a Local Model Broker under a separate Android application UID, with Binder as the only HG-to-broker control plane and a private Unix-domain socket as the broker-to-model-runtime transport. No unauthenticated TCP listener is exposed to other apps.

## 2. Direct Android observations

Observed on the connected device:

- Android 17, ABI arm64-v8a, Termux Python 3.14.8, kernel 6.6.118-android15-8-gc4127a25dcf3-ab15863337-4k.
- /proc/self/ns exposes no pid entry. stat("/proc/self/ns/pid") returns ENOENT for the attester, Ollama PID 8486 and runsv PID 8463.
- /proc/self/ns/net and /proc/8486/ns/net both resolve to net:[4026531840]; stat() is denied with EACCES.
- pidfd_open/pidfd_getfd syscall capability probe succeeds.
- The target probe sees Ollama PID 8486 holding one TCP LISTEN socket on 127.0.0.1:11434, inode 24545846, SO_REUSEPORT=false.
- The target probe still returns BLOCKED/SHARING_SCAN_INCOMPLETE, because proc visibility is invisible and process scope is PARTIAL. The self-test also returns BLOCKED/SELF_TEST_OBSERVATION_INCOMPLETE.
- L1 attestation currently stops at BLOCKED/PIDNS_UNAVAILABLE; L2-L5 are not thereby verified.

These observations mean the service and listener exist, but the current Termux process cannot establish the proof required by the Linux-oriented verifier.

## 3. L1 redesign — Android process identity

### 3.1 Current candidate behavior

PIDNS_UNAVAILABLE is a distinct BLOCKED result. It is never converted to PASS, PIDNS_MISMATCH, PARENT_UNREADABLE, or VERIFIED_LISTENER.

The strict HG_REQUIRE_PROC_TESTS=1 path continues to fail on a device that cannot expose the PID namespace handle. This is intentional and prevents a local test skip from masquerading as a production acceptance.

### 3.2 Broker L1 proof model

The broker becomes the process that owns model execution and the local model endpoint. L1 is anchored to Android's package/UID boundary rather than an unavailable Termux /proc namespace link:

1. Android PackageManager resolves the broker package to its installed UID and signing-certificate digest.
2. Broker startup records its process PID, UID, package version, signing-certificate digest and an owner-approved broker release digest.
3. The model backend is started by the broker under the broker UID. The backend PID is captured at process creation and bound to a pidfd where supported.
4. The broker verifies the backend executable identity and SHA-256 against a broker-owned, release-tracked trust anchor.
5. On every backend connection, SO_PEERCRED must identify the expected backend PID and UID. A mismatch, PID exit, socket replacement or executable change fails closed.
6. The broker returns a nonce-bound attestation envelope to HG over Binder. The envelope contains the broker identity, caller identity, backend identity, release and model digest, request digest, and pre/post verification outcomes.

No PID namespace is claimed to have been inspected. The replacement proof is the OS-authenticated Binder caller identity plus broker package identity and the kernel-authenticated Unix-socket peer credentials. The exact Android API and process lifecycle behavior must be proven by the broker POC before acceptance.

## 4. L5 redesign — no TCP listener in the model path

### 4.1 Transport

- HG calls an exported Android ContentProvider.call() or bound service over Binder.
- The broker checks Binder.getCallingUid(), package ownership for that UID, and the exact approved signing-certificate digest. Unknown callers are denied before request parsing or model execution.
- The broker runs the inference backend under its own app UID.
- The backend listens only on an AF_UNIX/SOCK_STREAM socket located below broker-private app storage (0700 directory, 0600 socket).
- The broker authenticates the backend with SO_PEERCRED, socket type, socket inode, owner UID, parent-directory ownership/mode, and the expected backend process identity.
- The socket path and descriptor are never returned to Termux or another app. There is no 127.0.0.1:11434 listener in the accepted production topology.
- The broker performs a pre-request check and a post-response check. It releases response bytes to Binder only after the post-check succeeds.
- A nonce and request digest bind the broker attestation to the exact model request and prevent response reuse.

### 4.2 Ollama compatibility finding

The preserved Ollama v0.40.14 source checkout shows server.RunServer calling net.Listen("tcp", envconfig.Host().Host). The bounded source audit found no repository-level listener-FD inheritance, LISTEN_FDS, SCM_RIGHTS, net.FileListener, or Unix-socket server entry point in that tag.

Therefore, the existing Termux Ollama package cannot simply be assumed to support this topology. The broker implementation must either:
- carry a small, reviewed and reproducibly built Ollama patch that listens on the private Unix socket; or
- use a backend with an explicitly supported private IPC transport.

Do not claim that changing OLLAMA_HOST to a Unix path works unless the patched binary's actual server implementation and Android tests prove it.

## 5. Binder contract (candidate)

Request:
- protocol version
- request ID and single-use nonce
- caller package identity
- model identifier and pinned model digest
- bounded request payload or ParcelFileDescriptor stream
- SHA-256 of the canonical request bytes

Response:
- matching request ID and nonce
- status (PASS, BLOCKED, REFUSED, FAILED)
- broker package UID/version/signing digest
- backend PID/UID/executable digest
- socket type/inode/owner/mode and SO_PEERCRED evidence
- model digest
- pre-check and post-check results
- response digest and bounded response payload

The broker must reject duplicate JSON keys, unknown fields, oversized payloads, stale nonces, mismatched request digests and unapproved callers. No secret or API key is returned in the attestation envelope.

## 6. Broker threat model and limits

In scope:
- other Android app UIDs attempting to call the broker;
- stale or replaced backend process;
- socket-path symlink/replacement and wrong file type;
- wrong backend executable or digest;
- response replay, request substitution and post-call listener loss;
- malformed Binder payloads and resource-exhaustion limits.

Explicit residuals:
- root/kernel compromise;
- malicious broker signing-key compromise;
- same broker UID compromise;
- malicious Android OS / PackageManager;
- correctness of generated model content.

These residuals must be owner-accepted and recorded. Do not state that Binder makes the system invulnerable.

## 7. Staged implementation plan

- B0: freeze contract, package name, signing identity and caller allowlist.
- B1: build minimal separate-UID broker with Binder caller authentication; prove wrong-UID denial.
- B2: package and run backend under broker UID; prove binary hash and process identity.
- B3: add private Unix socket support to the backend; prove file permissions, peer credentials and no TCP listener.
- B4: add nonce/request-digest binding and pre/post checks.
- B5: implement HG BrokerModelProvider; no direct Ollama TCP fallback.
- B6: adversarial tests, process-crash tests, broker restart, socket replacement, caller spoofing, replay and data-size limits.
- B7: staging recovery/rollback and Android end-to-end tests.
- B8: independent evidence review and GO-LIVE gate.

No production migration may begin before B0-B7 PASS and a verified rollback target exists.

## 8. Immediate safety posture

Until the broker is implemented and independently verified:

- local Ollama calls require VERIFIED_LISTENER;
- L1 PIDNS_UNAVAILABLE is BLOCKED;
- L5 SCOPE_PARTIAL is BLOCKED;
- model responses are not released when post-check fails;
- the running production release and current Ollama service remain untouched.

## 9. Existing CIM Android Broker C0 — reuse boundary

A separate experimental source tree already exists in the preserved worktree
$HOME/HG-IGYM-CIM-V1-MAIN (branch stt/hg-igym-cim-v1-mainline-20261110,
original HEAD 163be5dc5fe5a7b386ee8465a5d6b2f44adfa5be). Its status and files were inspected
read-only; this worktree has uncommitted/untracked CIM content and remains untouched.

Relevant existing source:
- android/cim-broker/app/src/main/java/org/hg/cim/broker/CimBrokerProvider.java
- BrokerStore.java
- CallerTrustEvaluator.java
- MainActivity.java
- app/src/main/AndroidManifest.xml
- docs/cim/HG-CIM-ANDROID-BROKER-IPC-V1.0.md
- docs/cim/HG-CIM-G2-POC-ACCEPTANCE-V1.0.md
- .github/workflows/cim-broker-android.yml

Observed C0 capability:
- A separate Android package (org.hg.cim.broker) with default independent app UID (no shared UID declaration in the manifest).
- One exported ContentProvider Binder method, call("status").
- Binder.getCallingUidOrThrow() is read before processing any caller-provided identity.
- PackageManager resolves installed com.termux; packagesForUid must contain only com.termux; Termux signing certificate digest is checked; owner pairing pins the UID/signer tuple in broker-private preferences.
- Other ContentProvider entry points (query, insert, delete, update, openFile) explicitly throw SecurityException.
- The returned bundle reports broker UID, caller UID/package/signer and mutating_capabilities_enabled=false.

This is a useful source-level C0 identity-handshake starting point and aligns with the separate-UID decision. It is not a model broker:
- It does not launch, supervise or attest an inference backend.
- It does not create a private Unix-domain inference socket or verify SO_PEERCRED.
- It has no model request/response, nonce, request digest or pre/post inference check.
- It provides no MAEP authorization receipt for mutation.
- Its own acceptance record says APK build, install, actual broker UID observation, Binder device handshake and negative cross-UID device tests remain pending.

The existing workflow .github/workflows/cim-broker-android.yml is configured to run
testDebugUnitTest and assembleDebug with JDK 17, Gradle 9.9, Android SDK 37 and Build Tools 36.0.0.
This Termux environment has no local gradle, ANDROID_HOME or ANDROID_SDK_ROOT, so the Android APK
cannot be built locally here. A CI run and an on-device install/pairing/negative test must precede
any claim of broker qualification.

Reuse decision:
- Preserve the C0 source and its owner pairing UI as an independent experimental workstream; do not cherry-pick, copy over, or merge the dirty CIM worktree automatically.
- A later isolated integration branch may add the model backend only after the C0 APK has passed build, install, UID/signer observation and negative caller tests.
- The model broker extension must preserve the existing status-only method as identity discovery and define a separate, versioned, explicitly authorized inference contract. The status handshake itself is never authorization to run a model or a tool.

## 10. Android Broker acceptance delta

Additional gates before treating C0 as reusable production security evidence:

| Gate | Current disposition | Required evidence |
|---|---|---|
| C0-S1 source review | SOURCE INSPECTED | Preserve exact source commit/blob hashes and owner pairing behavior |
| C0-S2 Android build | NOT RUN HERE | CI testDebugUnitTest + assembleDebug PASS with artifact digest |
| C0-S3 install | NOT RUN | APK install on target Android; package and UID evidence |
| C0-S4 caller identity | NOT RUN | Termux Binder caller UID equals PackageManager UID; broker UID is distinct |
| C0-S5 negative caller | NOT RUN | Unpaired / wrong signer / wrong package / wrong UID denied |
| B1 backend identity | NOT IMPLEMENTED | Backend process UID/PID/executable digest and ownership |
| B2 private IPC | NOT IMPLEMENTED | Private AF_UNIX socket, directory/socket modes, SO_PEERCRED and no TCP listener |
| B3 request bracket | NOT IMPLEMENTED | Nonce/request digest + pre/post checks; discard response on post-check failure |
| B4 MAEP receipt | NOT IMPLEMENTED | Broker-verifiable grant/resource/action receipt, no caller-supplied authority |
| B5 recovery | NOT IMPLEMENTED | Broker/backend crash, stale socket removal, no blind replay, restart and restore |


## 11. C0 emulator Binder-negative CI remediation (isolated branch)

**Worktree:** `~/HG-ANDROID-BROKER-CI`
**Branch:** `stt/hg-android-broker-ci-v1-20261111`
**Base:** `e465db2ef8143d013d6195abfa077f5010b3fd1c`

The original Broker candidate is not modified. An isolated worktree was created from the current main baseline and the Broker sources/workflow were copied from `~/HG-GO-LIVE-CANDIDATE`. The source comparison records 23 imported files, with 18 byte-identical and five explicitly modified in the isolated branch. The original candidate remains dirty and preserved.

### 11.1 Workflow defects corrected

The copied workflow had an empty `src/androidTest`, installed only the Broker APK, and invoked `am instrument` without building/installing an instrumentation APK. It did not install Termux or compare real app UIDs. That workflow could not substantiate a real Binder negative-caller claim.

The replacement pipeline:
- builds the Broker app and a separate `org.hg.cim.broker.probe` APK;
- runs JVM tests for caller policy, peer UID/PID and request-envelope correlation;
- pins JDK 17, Gradle 9.9.1, AGP 9.5.0, Android API 37 and Build Tools 36.0.0;
- downloads F-Droid Termux 0.118.3 / version code 1002 and verifies the package plus its pinned signer digest;
- installs Termux, Broker and the probe app on an API 35 emulator;
- obtains all three UIDs from PackageManager and requires that they are pairwise distinct;
- performs the owner-pairing confirmation through the Broker UI in the emulator;
- verifies the stored Termux UID and then calls the exported ContentProvider from the separate probe app UID;
- requires the actual Binder call to be refused with `DENY_UID`; missing Termux, signer mismatch, missing pairing, or unexpected denial cannot pass the test;
- uploads APK digests, package UID observations and Binder-negative logs as workflow artifacts.

The probe calls `ContentResolver.call()` on the exported provider and relies on Binder's kernel-supplied calling UID. It does not pass or forge a UID in its request. `Binder.getCallingUidOrThrow()` is available from Android API 29, matching the Broker's minSdk 29.

### 11.2 Current state and acceptance limits

At the time this revision was prepared, the new workflow had not yet executed. No Android APK build, emulator UID output, signer report, owner-pairing readback or actual Binder negative-call result is claimed.

A successful emulator negative-caller job would qualify only the negative UID boundary on that emulator. It would not establish a positive Termux Binder call, physical OPPO PKC110 installation/UID/signer evidence, physical negative Binder evidence, or the complete L1/L5 process/listener proof.

The Broker runtime and model trust-anchor JSON files remain empty. Model approval intentionally fails closed, and the Broker is not authorized to perform inference. There is no production cutover or model-path qualification from this CI remediation.

**G7 remains PARTIAL pending CI and BLOCKED for final physical/positive Binder qualification. G2, G5 and G8 remain BLOCKED. GO-LIVE remains NO-GO.**
