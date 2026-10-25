# HG Execution Host — P0 Closure Assessment V1

Date: 2026-10-24
Repository: OAI-GIANG/HG
Candidate branch: stt/execution-host-audit-only-20261024
Reviewed PR head before this assessment: cdb604af3dc731fef9508f3b914b6221049b4861
Scope: controlled implementation and acceptance planning; no production deployment.

## Executive decision

**P0 remains BLOCKED. Do not merge or deploy.**

The Android/Termux host does not currently provide a demonstrated OS-enforced boundary separating the HG audit principal from the RDC/Desktop Commander process and other code running under the same Android application UID. Namespace probes required for a conventional Linux namespace sandbox fail in this session. This is sufficient to reject the current Termux session as the acceptance environment for EH-02/EH-03; it does not prove that every possible Android architecture is impossible.

The proot tool is present but is not accepted as an OS security boundary. Docker/Podman/LXC/QEMU and /dev/kvm were not found in this session. No Linux VM is available through the currently inspected local device, so the alternative Linux/VM boundary cannot be provisioned or accepted from this host alone.

The existing AUDIT_ONLY feature provides application-level defense-in-depth. It does not make the RDC session itself audit-only.

## Preservation and observed host evidence

- Canonical main observed at 37e30b106cb9e0fafb289066befbce2c2b700a4a.
- Original checkout /data/data/com.termux/files/home/HG observed at f7f00a75c6a1b1363993c2fb9bc023171f080038, branch stt/maep-v1-20261022, with 90 pre-existing changed/untracked status entries. This checkout must remain untouched.
- HG server PID 15005 observed as python3 -u -m hg.server.
- RDC configuration version 0.3.0; Android/Termux; allowedDirectories=[]; default shell /data/data/com.termux/files/usr/bin/bash.
- PID 15005 (HG server) and PID 15212 (RDC Node process) both observed with UID/GID 10460, SELinux context u:r:untrusted_app_27:s0:c204,c257,c512,c768, CapEff=0, Seccomp=2, NoNewPrivs=0. This demonstrates they share the same Android app UID/SELinux domain in the observed snapshot; it is not a proof of all possible Android IPC paths.
- /proc/self/ns/user was not visible.
- unshare -Ur true returned Invalid argument; unshare -m true, unshare -n true, and unshare -pf true returned Operation not permitted.
- proot and unshare binaries exist. No docker, podman, nerdctl, lxc, lxd, qemu-system-aarch64, qemu-aarch64, systemd-nspawn, firejail, or bwrap was found; /dev/kvm was absent. Absence checks apply only to this Termux environment.
- These probes create no persistent namespace or production changes. No production file, configuration, permission, principal, PID, service, or main branch was changed by this assessment.

## RDC capability inventory observed in the connected session

The connected RDC tool surface exposes the following actions. This is a complete inventory of the tool names visible to this session, not a claim that every underlying Android/kernel capability has been enumerated.

| Capability class | Observed tools | Security relevance |
|---|---|---|
| Read / inspect | read_file, read_multiple_files, list_directory, get_file_info, start_search, get_more_search_results, list_searches, get_recent_tool_calls, list_remote_tool_calls, who_am_i, get_config, list_devices, list_processes, list_sessions, get_usage_stats, get_tool_result | May disclose repository, host, process, and configuration information within the server's access. |
| File mutation | write_file, write_pdf, create_directory, move_file, edit_block | Can alter or create accessible files. |
| Process / command control | start_process, interact_with_process, kill_process, force_terminate | Can execute commands and alter process state; not compatible with treating this same principal as audit-only. |
| Configuration / service control | set_config_value, shutdown | Can change RDC policy/configuration or interrupt the control service. |
| Search control | stop_search | Stops a running search; operational side effect limited to the search task. |

The observed configuration has an empty allowedDirectories array. This assessment does not infer exact path enforcement semantics from that value alone. The configuration also exposes editable blockedCommands, allowedDirectories, defaultShell, telemetry and read/write limits; these controls are not an OS isolation boundary.

## Required target architecture if Termux cannot meet the gate

Use a **separate owner-controlled Linux VM or Linux host**, not proot as the security boundary and not a container running under the same Termux UID.

1. **Hypervisor/host boundary:** disposable Linux VM, separate from production and from the Android Termux app. No production secrets, mounted production data, or production service credentials.
2. **Separate identities:** dedicated unprivileged OS account hg-audit for read-only inspection; separate hg-executor identity only for explicitly approved test execution; separate evidence-collector identity/service. No shared UID or shared writable home.
3. **No general shell for the audit API:** the RDC/model-facing surface exposes fixed typed operations only. Do not provide arbitrary shell, process-control, policy-edit, Git mutation, or configuration APIs to HG_AUDIT.
4. **OS-enforced filesystem controls:** repository fixture mounted read-only to the audit identity; no access to production paths; no writable policy/trust-root path; no writable evidence-ledger path for the executor. Use OS permissions and a service sandbox in addition to application checks.
5. **Process/network restrictions:** no privilege escalation or ambient capabilities; restrict process creation and network egress to the minimum needed for canonical read-only source retrieval. The audit principal must not receive shell credentials or a general-purpose remote-execution credential.
6. **Evidence separation:** a distinct collector/permission domain accepts append-only evidence records and denies overwrite/delete to the executor. Store the authoritative evidence outside the executor's writable filesystem. A hash alone is not proof of immutability.
7. **Disposable acceptance environment:** use synthetic repository fixtures and fake secrets; never use the active HG server or production data to test escape paths.
8. **Failure handling:** fail closed if the canonical trust root cannot be retrieved or validated. If a process crashes after a side effect may have occurred, record UNKNOWN and reconcile before any retry.

The VM/host must be owner-provisioned and its isolation controls inspected before acceptance. This assessment does not provision a VM, open a cloud resource, install packages, or incur infrastructure cost.

## Proposed minimum HG_AUDIT grant — proposal only

Do not change maep/authority/owner-grants.json on main as part of this task. The current canonical manifest grants broad permissions to STT and has no HG_AUDIT grant.

Proposed new grant, subject to owner review and validation against the canonical schema:

- principal: HG_AUDIT
- actions: [maep.read] only
- scope: [repo:OAI-GIANG/HG, file:docs/architecture/, file:hg/, file:maep/, file:evidence/]
- validity: short-lived (proposed maximum 7 days), explicitly revocable
- prohibited actions: maep.write, maep.commit, maep.push, maep.merge, maep.deploy, maep.migrate, maep.delete, maep.execute
- no authority to edit the grant, canonical branch, policy version, or evidence collector.

This is a proposed least-privilege shape, not an applied grant. Fixture-only tests in maep/tests/test_hg_audit_minimum_grant_proposal.py pass for schema validity, allowed scoped read, out-of-scope denial, write denial, wrong-principal denial, and expiry denial. These tests validate the current policy matcher against the proposed fixture; they do not prove production authorization or apply the grant. Validate scope semantics further before owner-authorized adoption. Until then, production AUDIT_ONLY must fail closed.

## EH-01–EH-07 closure matrix

| Gate | Current disposition | Required evidence to close |
|---|---|---|
| EH-01 inventory tools/APIs/principals/side effects | PARTIAL | Reconcile this observed RDC tool inventory with the actual server implementation and all network/IPC entry points on the selected Linux VM. Record versions and principal map. |
| EH-02 audit principal cannot mutate protected resources | BLOCKED | In the isolated Linux VM, demonstrate OS-denied write/delete/rename/chmod/symlink and policy-path mutations; verify protected fixture hashes remain unchanged. Include direct filesystem attempts outside the HG application API. |
| EH-03 no shell/process/path/API escape | BLOCKED | Demonstrate OS-enforced denial of arbitrary shell, child-process execution, path traversal/symlink escape, procfs/namespace escape, unauthorized sockets/network, and unlisted APIs. Include negative tests for every exposed entry point. |
| EH-04 cannot alter policy/trust root/enforcement | UNVERIFIED | Show OS-denied modification of policy, canonical trust-root cache, executable/configuration, service unit, and collector configuration. Verify missing/expired/invalid grant fails closed. |
| EH-05 denied operations have no side effects | APPLICATION TESTS ONLY | Preserve existing negative unit tests and add host-level denial tests in the VM. Compare file/process/network snapshots before and after each denial. |
| EH-06 reproducible evidence | PARTIAL | Pin candidate commit, VM image/version, OS/kernel, test fixture hashes, exact commands, exit codes and observed outputs. Capture records in the separate append-only evidence domain. Re-run from a clean fixture. |
| EH-07 acceptance environment independent of production | UNVERIFIED | Provision a disposable VM with no production mounts/secrets/processes, verify its identity and mount inventory, and run the acceptance suite there. |

## Implementation and acceptance sequence

- P0-A — Host availability: owner provisions a separate Linux VM/host and gives an approved, narrow connection method. No VM is currently available from the inspected Termux session.
- P0-B — Threat/capability inventory: inspect the exact API server source, enumerate entry points and side effects, bind each to a principal and OS identity.
- P0-C — OS boundary: configure distinct OS users, read-only fixture mounts, process/network restrictions, and separate evidence collector; verify with direct OS-level negative tests.
- P0-D — Trust root: prepare a minimal HG_AUDIT grant as a separate reviewable change. Do not edit or merge the trust root without explicit owner approval.
- P0-E — EH acceptance: run EH-01..EH-07 against the pinned candidate and disposable fixtures; preserve logs, hashes and observed exit codes in the separate evidence domain.
- P0-F — Close review: mark CLOSED_VERIFIED only if every required gate has observed evidence and no P0 finding remains open. Otherwise retain BLOCKED_P0 with the exact blocker.

## Stop conditions

Stop without production changes if the VM/host is unavailable, the evidence collector is not separate, any denied operation mutates a fixture, trust-root provenance cannot be verified, or any result is ambiguous. Do not merge PR #11 or deploy based only on application-level tests.
