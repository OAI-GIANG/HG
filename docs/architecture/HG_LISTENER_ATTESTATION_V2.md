# HG Listener Attestation V2 (HG-LA-2)

Status: DESIGN + implementation candidate. Task `HG-MASTER-LISTENER-ATTESTATION-EXECUTION-V1`.
Evidence: `docs/evidence/HG-MASTER-LISTENER-ATTESTATION-EXECUTION-V1/`. Nothing here is PRODUCTION: the
phone was unreachable for the whole task, so every on-device item is NOT_RUN.

| Component | File | Status |
|---|---|---|
| Five-layer attestation + post-check | `hg/assistant/attest.py` | IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED on Linux 6.18 x86_64 (real processes, sockets, pidfd, pidfd_getfd); device NOT_RUN |
| Release-tracked trust anchor | `hg/assistant/trusted_runtimes.json` | IMPLEMENTED, **empty** → L3 is UNVERIFIED everywhere |
| Standalone L5 probe | `deploy/termux/l5_probe.py` | IMPLEMENTED, TESTED in the sandbox (self-test, same-UID, cross-UID); device NOT_RUN |
| Raw-data benchmark | `deploy/termux/ollama_bench.py` | IMPLEMENTED, UNIT_TESTED against a fake NDJSON server; device NOT_RUN |
| Wiring into `ask` / `/v1/chat` (refuse unless VERIFIED_LISTENER, bracket each call) | — | DESIGN only (§11); gated |
| Legacy `config.attest_listener` | `hg/assistant/config.py` | behaviour unchanged; now reports `"listener": "UNVERIFIED"` and no longer claims port ownership (F-1) |

## 1. The five questions

| # | Question | Mechanism | Answer today |
|---|---|---|---|
| Q1 | Is the Ollama process the one the trusted supervisor manages? | L1 | Yes in the sandbox (stand-in supervisor; real `runsv` in CI). Device UNVERIFIED |
| Q2 | Is its executable the approved Ollama binary? | L2 + L3 | Identity: yes in the sandbox. "Approved": UNVERIFIED — no anchor entry yet (F-7) |
| Q3 | Does the running binary match the HG release's trust anchor? | L3 | UNVERIFIED (anchor empty) |
| Q4 | Do its credentials satisfy the policy? | L4 | Yes in the sandbox; device UNVERIFIED |
| Q5 | Is that process the one serving `127.0.0.1:11434`? | L5 + post-check | Yes in the sandbox via pidfd_getfd; on Android 16 UNVERIFIED until `l5_probe.py` runs there |

Overall: **not VERIFIED**. Any layer short of PASS keeps the result fail-closed.

## 2. Findings

- **F-1 (defect, reproduced)** — `main@2f00a62` `config.attest_listener` returned `VERIFIED_PROCESS` with the
  reason "Ollama exits when it cannot bind its port" while a *different* process held the port. Liveness is
  not ownership: when a squatter holds 11434, runit restarts Ollama every second and each attempt is briefly
  alive, so the old check can pass during a restart. Reproduction: `logs/F1-reproduction-main-2f00a62.log`;
  regression test `AttestL5Tests.test_api_answers_but_another_process_owns_the_port_F1`.
- **F-2 (weakness)** — the old check reads `supervise/pid` by path (symlinks followed), trusts the basename of
  `readlink(/proc/PID/exe)`, and has no start-time, parent, supervisor-directory or network-namespace binding.
- **F-3 (fact)** — Ollama `v0.40.13` (commit `04088e7c9d41cba5d33bafbf788d87a465c79d5b`): `RunServer` always calls
  `net.Listen("tcp", envconfig.Host().Host)` (`cmd/cmd.go:2274`) and hands it to `server.Serve(ln)`
  (`server/routes.go:2472`). No `LISTEN_FDS`/`LISTEN_PID`/`os.NewFile` path exists, so an inherited listener
  (option B) needs a source patch. Go sets `SO_REUSEADDR`, never `SO_REUSEPORT`, on that listener.
- **F-4 (fact)** — termux-packages (`packages/ollama/build.sh` at tree `ed2ff96a1160…`) builds Ollama
  **0.40.13** natively for Android (Bionic, aarch64/x86_64; `arm`/`i686` excluded): `go build -trimpath
  -ldflags="-w -s -X …version.Version=0.40.13 -X …server.mode=release"`, installed as `$PREFIX/bin/ollama`
  (mode 0700); llama.cpp backends built with CMake (`GGML_BACKEND_DL=ON`, `GGML_CPU_ALL_VARIANTS=ON`,
  `GGML_OPENMP=OFF`, Vulkan subpackage) into `$PREFIX/lib/ollama/` and loaded at run time; depends on
  `libandroid-spawn`, `libc++`; Go `1.26.10` per `go.mod`. A native runtime with distribution provenance
  therefore exists; no glibc binary is involved.
- **F-5 (inference from platform sources)** — `pidfd_getfd` is plausible for Termux on Android 16:
  bionic `libc/SYSCALLS.TXT:390-391` lists `pidfd_open`/`pidfd_getfd` (the app seccomp policy is generated from
  that list; no blocklist entry), an AOSP-14-derived `private/untrusted_app_all.te` has
  `allow untrusted_app_all self:process ptrace;`, `execve` resets the dumpable flag for Termux's children, and
  Android kernels do not normally enable Yama. Unknowns: kernel ≥ 5.6 on this phone, vendor policy changes.
- **F-6 (conflict in history)** — `docs/V1_SCOPE.md` records a native Termux Ollama 0.40.12 runit service; the
  task brief records Debian 13 PRoot Ollama 0.40.13 (PIDs 31868/31870). Both are historical; current state is
  UNKNOWN. Under PRoot, `/proc/PID/exe` is the PRoot loader, so L2 fails by design (conclusion H).
- **F-8 (fact, found by CI)** — with Yama `kernel.yama.ptrace_scope=1` (Ubuntu's default, GitHub runners)
  `pidfd_getfd` reaches only descendants. HG is never Ollama's ancestor (runsvdir starts Ollama), so on such a
  kernel L5 is `BLOCKED/PIDFD_GETFD_EPERM` — fail-closed, as intended. The probe records `yama_ptrace_scope`;
  Android kernels normally lack Yama (F-5). Tests cover both: a target that sets `PR_SET_PTRACER_ANY` passes, one
  that does not is BLOCKED, never PASS.
- **F-9 (defect, fixed; P2: fail-closed false negative, not a bypass)** — L5 counted listeners per descriptor, so
  one socket with two descriptors (`dup()`) was `FAIL/MULTIPLE_LISTENERS (count 2)`; the probe had the same flaw
  (`NO_UNIQUE_LISTENER`). Root cause: matches keyed by fd instead of socket inode. Fix: group by inode; the result
  lists every fd of the socket and `reverify()` accepts any of them. Failing-first logs:
  `logs/F9-failing-first.log`, `logs/F9-probe-failing-first.log`.
- **F-10 (evidence gap, fixed; P2)** — the sharing scan returned one "hidden" count. It did not say which kind of
  process could not be inspected, silently skipped descriptors whose link could not be read, and ignored `hidepid`
  (with it, other users' processes are not even listed). A PASS could be read as proven exclusivity. Root cause:
  `socket_holders()` modelled only "holder / not holder". Fix: structured observation (holders; uninspectable
  processes by UID class read from the status `Uid` line, because `/proc/PID` of a non-dumpable process — e.g. the
  Termux app — is owned by root; unreadable descriptors; `proc_hidepid`) and `scope` = `ALL_PROCESSES_INSPECTED` or
  `PARTIAL`. Status semantics are unchanged and stated in §4.
- **F-7 (blocker)** — the Termux package repositories are unreachable from the build sandbox (HTTP 000 on three
  mirrors), so the digest of the Termux `ollama` binary could not be obtained with its signature chain. L3 stays
  UNVERIFIED until §9 is done on the phone.

## 3. Threat model and trust chain

In scope: another Android app (different UID) that calls Ollama's unauthenticated loopback API or binds 11434
while Ollama is down; an impostor process named `ollama`; PID reuse; exec or binary replacement during the
check; descriptor reuse races; listener sharing or `SO_REUSEPORT` co-binding; a LAN-exposed bind.
Out of scope (owner decision Q3, unchanged): a same-UID attacker, root, the kernel, eBPF `sk_lookup` or
netfilter redirection (root-only).

Trust chain (each link must hold):
Termux repository signing key → apt-verified `.deb` → anchor entry added by a reviewed PR to
`hg/assistant/trusted_runtimes.json` (part of the release manifest, sealed on install) → L3: SHA-256 of the
**running image** read through its `/proc/PID/exe` descriptor → L2: that image belongs to the PID → L1: the
PID is the direct child of the `runsv` working in this service directory → L4: credentials → L5: the PID
holds the only LISTEN socket on `127.0.0.1:11434` → post-check after the exchange.

## 4. Layers (implementation: `hg/assistant/attest.py`)

Results: `PASS`, `FAIL` (evidence of a mismatch), `BLOCKED` (platform prevents evidence), `UNVERIFIED` (nothing
to compare with). Overall `VERIFIED_LISTENER` only if all five PASS; precedence FAIL > BLOCKED > UNVERIFIED.
L1 or L2 short of PASS ends the run; L3 and L4 are recorded and L5 still runs, so one read-only run yields
evidence for every layer.

**L1 supervision.** `open(service_dir, O_DIRECTORY|O_NOFOLLOW)`, fstat: owner = euid, not group/other
writable. `openat(dfd, "supervise", O_DIRECTORY)` (a symlink into a run directory is allowed; the opened
directory is checked). `openat(sfd, "pid", O_NOFOLLOW|O_NONBLOCK)`; fstat on that descriptor: regular, owner,
mode; content `^[1-9][0-9]{0,6}\n?$`, ≤ pid_max. `/proc/PID/stat` parsed with comm = text between the first `(`
and the **last** `)`; state not Z/X; `pidfd_open`; stat read again — start time and comm unchanged and pidfd
not readable (PID reuse / exit). Same PID namespace. Parent: comm and exe basename `runsv`, owned by euid,
older than the child, and **its working directory is the same inode as the opened service directory**
(runsv chdirs into its service). The pid file is read again at the end (service restarted). pidfd is a
reference used for liveness, not a lock: it does not stop `execve`.
Codes: `SERVICE_DIR_UNUSABLE`, `SERVICE_DIR_OWNER_OR_MODE`, `SUPERVISE_DIR_*`, `PID_FILE_SYMLINK`,
`PID_FILE_NOT_REGULAR`, `PID_FILE_OWNER_OR_MODE`, `PID_FILE_EMPTY`, `PID_FILE_MALFORMED`, `STALE_PID`,
`PROCESS_DEAD`, `PID_REUSED_OR_EXITED`, `PIDNS_MISMATCH`, `PARENT_NOT_RUNSV`, `RUNSV_OF_ANOTHER_SERVICE`,
`RUNSV_OWNER_OR_AGE`, `SERVICE_RESTARTED`, `PIDFD_OPEN_*` (BLOCKED).
A run script without `exec` leaves the shell's PID in `supervise/pid`; L1 passes (the shell is runsv's child)
and L2 fails (`EXE_NAME_MISMATCH`). The service's `run` must end in `exec ollama serve`.

**L2 identity.** `open("/proc/PID/exe")` once; fstat: regular, `st_nlink > 0` (else `EXE_DELETED`, e.g.
upgraded while running), owner euid or root, not group/other writable; basename `ollama`; SHA-256 through
`pread` on that descriptor (never a path from `readlink`); fstat again — `(dev, ino, size, mtime_ns, ctime_ns)`
unchanged (`EXE_CHANGED_DURING_HASH`; ctime cannot be set back by a user); `/proc/PID/exe` stat'ed again —
same `(dev, ino)` (`EXEC_DURING_ATTESTATION`); start time unchanged and pidfd alive. Scope: a snapshot at
two points, **not** continuous execution integrity — an exec away and back to the same file between the two
points is invisible.

**L3 integrity.** The digest must equal an entry for `ollama` in the release-tracked anchor
(`schema: hg-trusted-runtimes-v1`; each entry exactly `name, version, sha256, source, provenance`; file must be
regular, not a symlink). Never read from `HG_HOME` or `config.json`. No entry → `UNVERIFIED/NO_TRUST_ANCHOR`;
entries but no match → `FAIL/DIGEST_NOT_ANCHORED`; defective file → `FAIL/TRUST_ANCHOR_INVALID`. SHA-256
equality is not source provenance: provenance is the chain in §3 and §9.

**L4 credentials** (`CREDENTIAL_POLICY`, `check_credentials`, pure and unit-tested). Real/effective/saved/fs
UID all equal HG's real UID; same for GID; supplementary groups exactly HG's; for CapInh/CapPrm/CapEff/
CapAmb/CapBnd no bit HG's own set lacks; same Seccomp mode; NoNewPrivs ≥ HG's; same SELinux context when HG's
own is readable (target unreadable then → FAIL). Missing fields or unreadable status → FAIL.

**L5 listener.** Same network namespace (`/proc/self/ns/net` vs `/proc/PID/ns/net`). `pidfd_getfd` (syscall
438, unified table) is first probed in a throwaway interpreter because Android's seccomp traps kill with
SIGSYS (`capability()`; result cached per process). Every `socket:[N]` in `/proc/PID/fd` is duplicated; the
duplicate's inode must equal N (else the descriptor was closed and reused — counted as `raced`, skipped). On
the duplicate only `getsockopt`/`getsockname`: AF_INET/AF_INET6, SOCK_STREAM, IPPROTO_TCP, `SO_ACCEPTCONN=1`,
port. A listener is a **socket (inode)**, not a descriptor: descriptors of one socket are grouped (F-9) and the
result lists them (`fds`). Exactly one listening socket on `host:port` (`NO_LISTENER`; `MULTIPLE_LISTENERS` counts
distinct inodes); any other bind on that port in the process → `UNEXPECTED_BIND_ON_PORT` (wildcard/LAN exposure);
`SO_REUSEPORT` off (`REUSEPORT_SET`); no inspected process other than the target holds that inode
(`LISTENER_SHARED`); start time unchanged and pidfd alive. `EPERM`/`EACCES`/`ENOSYS`/SIGSYS → BLOCKED; `ESRCH` →
FAIL. The duplicate is never accepted on, shut down or written; closing it drops only our reference.
`/proc/net/tcp` is never required.

Sharing evidence (F-10), carried in every L5 PASS as `sharing`: `uninspectable` processes by class (`same_uid`,
`root`, `other_uid`, `unknown`), `unreadable_descriptors`, `proc_hidepid`, `scope` and `basis`. What it proves and
what it does not:
- Proved: the attested process holds the only LISTEN socket on `host:port` (kernel bind rules, §5), and **no
  inspected process** holds a descriptor of it.
- Not proved when `scope` is `PARTIAL`: that no uninspected process holds one. Such a process could hold the
  socket only if Ollama, a same-UID process or root passed it the descriptor. An unprivileged other-UID process
  cannot take it, because `pidfd_getfd` and ptrace need ptrace rights over Ollama. Same-UID and root are out of
  scope (Q3), and Ollama passes no descriptors. So `PARTIAL` does not fail L5, but the limit is part of the result
  and is never dropped. Expect `PARTIAL` on Android: hidepid hides other apps, and the Termux app process itself is
  non-dumpable, hence uninspectable even for the same UID (the sandbox already shows `PARTIAL`: root cannot read
  PID 1's descriptors there).
- So `hidden > 0` is not, by itself, grounds for PASS: the PASS rests on the bind rules plus Q3, and it says so.

## 5. Post-check (`Attestation.reverify`)

After the caller's HTTP exchange: same PID in the pid file, pidfd alive, same start time, same exe `(dev,ino)`,
and `pidfd_getfd` of **any** recorded descriptor of the listener yields the **same socket inode**, still LISTEN on
the same address and port. The sharing scan is not repeated: a sharer appearing between the checks requires a
same-UID or root actor (Q3). Argument: sockets stay bound while referenced; a socket inode held by the process at both checks was
alive throughout; Linux refuses any other bind on `127.0.0.1:P` or `0.0.0.0:P` while a LISTEN socket without
`SO_REUSEPORT` holds it, even for a second socket that sets `SO_REUSEADDR` or `SO_REUSEPORT`
(`KernelBindSemanticsTests`, observed on 6.18); so a TCP connection to `127.0.0.1:P` made between the two checks
reached that socket. Residuals: a same-UID process could take a duplicate and `accept` (Q3); root-level
redirection. Codes: `SERVICE_RESTARTED`, `PROCESS_EXITED`, `EXEC_SINCE_ATTESTATION`, `LISTENER_GONE`,
`LISTENER_REPLACED`.

## 6. Android procedure (owner's phone; read-only)

    cd <release root or ~/HG>
    python3 -I -S deploy/termux/l5_probe.py --out ~/hg-v1-evidence/l5-selftest-$(date +%s).json
    python3 -I -S deploy/termux/l5_probe.py --target-pid "$(cat $PREFIX/var/service/ollama/supervise/pid)" \
            --expect 127.0.0.1:11434 --out ~/hg-v1-evidence/l5-ollama-$(date +%s).json
    python3 -B -m hg.assistant.attest --service-dir $PREFIX/var/service/ollama --port 11434

| Probe result | Meaning | Next |
|---|---|---|
| self-test PASS, target `LISTENER_OWNED` | L5 works on this device | §9 anchor, then PR-B wiring |
| `SECCOMP_SIGSYS` / `PIDFD_*_ENOSYS` | syscall unavailable (seccomp or kernel < 5.6) | option B (inherited listener patch) or C (below) |
| `PIDFD_GETFD_EACCES` | SELinux denies | same as above; record the AVC if `logcat` shows it |
| `PIDFD_GETFD_EPERM` | ptrace rules: UID, dumpable, or Yama `ptrace_scope` ≥ 1 (see `environment.yama_ptrace_scope`, F-8) | check Ollama runs as the Termux UID, not under PRoot; under Yama, option B/C |
| target `NO_UNIQUE_LISTENER` | process does not hold the expected listener | F-1 situation or wrong service; investigate before anything else |

Option C (only if A and B fail): Ollama bound to a Unix-domain socket inside the 0700 app directory, so the
filesystem, not the TCP port, carries ownership. Not available in Ollama 0.40.13 without a patch either.

## 7. Runtime decision

- PRoot: fails L2 by design; not used for an attested listener.
- **Termux package `ollama` 0.40.13 (recommended)**: native Bionic, built by Termux's public recipe and
  infrastructure, distributed through the signed repository; reproducing it byte-for-byte is not claimed.
  Service: `$PREFIX/var/service/ollama/run` = `#!/data/data/com.termux/files/usr/bin/sh` +
  `export OLLAMA_HOST=127.0.0.1:11434` + `exec ollama serve 2>&1`. Rollback: `sv down ollama`, restore the
  previous run script (keep a copy), `sv up ollama`; models in `~/.ollama` are untouched.
- Self-built Ollama (needed for option B): pin `v0.40.13`, Go 1.26.10, NDK/termux toolchain, the six Termux
  patches, recorded flags; two builds must match before an anchor entry. BLOCKED here (no Android toolchain,
  no device). Deferred.

## 8. Not proved

Continuous execution integrity between checks; integrity of `$PREFIX/lib/ollama/*.so` and of the `ollama
runner` child that runs inference (a later layer could compare `/proc/PID/maps` entries with anchored
digests); model weights beyond the existing digest pin (`check_model`); anything against same-UID, root or
kernel adversaries; correctness of answers.

## 9. Adding a trust-anchor entry (on the phone; apt checks the repository signature)

    apt-get update && apt-get download ollama            # verified against the signed InRelease/Packages
    dpkg-deb -f ollama_*.deb Package Version Architecture
    sha256sum ollama_*.deb
    dpkg-deb --fsys-tarfile ollama_*.deb | tar -xO ./data/data/com.termux/files/usr/bin/ollama | sha256sum
    sha256sum $PREFIX/bin/ollama                         # must equal the line above

Record in a PR: `{"name": "ollama", "version": "<Version>", "sha256": "<binary digest>", "source":
"termux-main", "provenance": {"deb_sha256": "…", "architecture": "…", "recipe": "termux-packages
packages/ollama/build.sh", "apt_verified": true, "observed_utc": "…"}}` plus the command log in an evidence
directory. An upgrade adds the new entry before the binary changes and removes the old one after; an unknown
digest fails closed (`DIGEST_NOT_ANCHORED`).

## 10. Test matrix (the task's 30 cases)

`hg/tests/test_attest.py` unless noted. "sandbox" = executed in this task on Linux 6.18; CI runs the same with
real `runsv` and `HG_REQUIRE_PROC_TESTS=1`.

| # | Case | Test | Result |
|---|---|---|---|
| 1 | empty pid file | `PidFileTests.test_empty_missing_malformed` | PASS sandbox |
| 2 | pid file not regular (FIFO, dir) | `PidFileTests.test_not_regular_symlink_and_modes` | PASS |
| 3 | symlink pid file | same | PASS |
| 4 | stale PID | `AttestL1Tests.test_stale_pid` | PASS |
| 5 | PID reuse | `AttestL1Tests.test_pid_reuse_between_reads_is_detected` (injected start time) | PASS |
| 6 | wrong runsv parent | `test_parent_is_not_runsv`, `test_runsv_of_another_service` | PASS |
| 7 | shell-wrapper run script | `test_shell_wrapper_run_script` | PASS |
| 8 | wrong executable | `AttestL2L3Tests.test_wrong_executable_name` | PASS |
| 9 | same name, wrong digest | `test_same_name_wrong_digest` | PASS |
| 10 | binary changed during hash | `test_executable_metadata_changed_during_hash` (ctime change) | PASS |
| 11 | execve during attestation | `test_execve_during_attestation` | PASS |
| 12 | pidfd target gone | `test_process_killed_during_attestation` | PASS |
| 13 | wrong UID/GID | `CredentialPolicyTests.test_each_uid_and_gid_position` | PASS (unit) |
| 14 | wrong supplementary groups | `test_supplementary_groups` | PASS (unit) |
| 15 | capability beyond policy | `test_capabilities_beyond_own_sets` | PASS (unit) |
| 16 | `/proc/PID/status` unreadable | `AttestL4Tests.test_unreadable_status_fails_closed` | PASS |
| 17 | `/proc/PID/exe` unreadable | `test_unreadable_executable_fails_closed`; real cross-UID denial: probe run | PASS |
| 18 | `pidfd_getfd` EPERM/EACCES/ENOSYS | `test_pidfd_getfd_errors`; real EPERM: probe cross-UID | PASS |
| 19 | descriptor closed and reused | `test_descriptor_closed_and_reused_between_listing_and_getfd` | PASS |
| 20 | not TCP | `test_not_listening_udp_wrong_port` (UDP) | PASS |
| 21 | not LISTEN | same (bound only) | PASS |
| 22 | wrong bind address | `test_wrong_bind_address` (0.0.0.0, 127.0.0.2) | PASS |
| 23 | wrong port | `test_not_listening_udp_wrong_port` | PASS |
| 24 | listener owned by another process | `test_api_answers_but_another_process_owns_the_port_F1` | PASS |
| 25 | several listeners / SO_REUSEPORT | `test_reuseport_single_and_double` | PASS |
| 26 | API answers, identity fails | case 24 | PASS |
| 27 | model digest mismatch | existing `test_assistant_ask.ConfigTests.test_model_ready_missing_and_digest_pin` | PASS |
| 28 | service restart during attestation | `AttestBracketTests.test_service_restart_after_attestation` | PASS |
| 29 | runtime loses listener | `test_listener_closed_after_attestation`, `test_listener_replaced_after_attestation` | PASS |
| 30 | any layer without evidence fails closed | `test_overall_status_precedence`, `test_shipped_empty_anchor_keeps_overall_unverified_but_collects_l5`, `test_seccomp_or_missing_syscall_blocks_l5` | PASS |

Also: network namespace (root only), listener shared by a forked child, real `runsv` (CI), kernel bind rules,
probe self-test (12 checks), probe target mode, Yama non-ancestor (F-8). F-9/F-10 added:
`AttestL5Tests.test_duplicated_descriptor_is_one_listener_but_independent_sockets_are_two` (dup → one listener
PASS; two SO_REUSEPORT sockets → `MULTIPLE_LISTENERS`, count 2),
`AttestBracketTests.test_first_descriptor_closed_but_duplicate_keeps_the_listener`, `SharingScanTests` (holder
found; uninspectable processes classified and never counted as holders; unreadable descriptor, hidepid and
unknown mount make scope `PARTIAL`; excluded PID; real `/proc` reports its own limits),
`ProbeRunTests.test_target_with_duplicated_descriptor_is_one_listener`. Mutation: 12 mutants of the original
checks (`logs/mutation-attest.log`) and 7 of the F-9/F-10 logic (`logs/mutation-sharing.log`), all killed by
assertion failures, controls passing.

## 11. Acceptance criteria and integration gate

- AC-LA-1 — all five layers PASS against the real Ollama on the phone (`python -m hg.assistant.attest`) — NOT_RUN.
- AC-LA-2 — `l5_probe.py` self-test PASS and target `LISTENER_OWNED` on the phone — NOT_RUN.
- AC-LA-3 — anchor entry for the installed binary added per §9 with evidence — BLOCKED (F-7, device).
- AC-LA-4 — every case in §10 passes in CI on Python 3.13 and 3.14 with real `runsv` and
  `HG_REQUIRE_PROC_TESTS=1` — **PASS (CI, Linux runners only; not the device)** on code commit
  `d79d1ca6327f783d7490a34add012f7e4fa1f073`: workflow runs `41207019585` (MAEP tests, push), `41207023339`
  (MAEP tests, pull_request), `41207023340` (rt06-trust-anchor-tests); `unittest (3.13)` / `(3.14)` jobs
  `124554075160` / `124554074977` (push) and `124554086179` / `124554085902` (pull_request), all `success`.
  Earlier green head `f39a0be` (runs `41204226157`, `41204229861`, `41204229832`) predates F-9/F-10. Commits after
  `d79d1ca` that touch only documentation are checked by CI again; their runs are listed on PR #77.
- AC-LA-5 — benchmark on the phone: raw NDJSON, TTFT, generation TPS from `eval_*` — NOT_RUN. The operator's
  earlier "325 tokens / 21.66 s = 15.00 tok/s" divides by wall time, not `eval_duration`, and is not accepted
  as generation TPS.

PR-B (wiring) may start only when AC-LA-1..3 hold: `ask` and `/v1/chat` then attest before the model call,
refuse unless `VERIFIED_LISTENER`, call `reverify()` after the response and discard it on failure, and record
the attestation report in the receipt. Until then nothing may present the listener as VERIFIED.
Stop conditions: any layer FAIL on the real device; the probe BLOCKED with no option B/C plan approved by the
owner; an anchor entry without the §9 evidence.

## 12. Review record (internal, several angles; not the independent review of MAEP-021)

- Security — holding a duplicate of the listener keeps the port bound if Ollama dies meanwhile: duplicates are
  closed immediately and never kept across the bracket (re-duplicated in `reverify`).
- Correctness — uniqueness rests on bind-conflict rules: verified empirically, kept as a test.
- TOCTOU — a single check proves nothing about the later connection: added the post-check (§5).
- Android — a SIGSYS would kill `hg serve`: first call in a throwaway interpreter.
- Coverage — stopping at L3 while the anchor is empty would hide L5 on the device: L3/L4 no longer stop the run;
  overall status unchanged.
- Honesty — the legacy check's "port is ours" reason was false (F-1): reason corrected, behaviour kept, because
  refusing every call before the device evidence exists would break the owner's v1 assistant.
- Scope — wiring, runtime switch on the phone and option B are separate, gated work.
