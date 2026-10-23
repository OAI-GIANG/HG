# MAEP Bypass Enumeration V1

Date: 2026-10-24
Repository: OAI-GIANG/HG
Test worktree: `stt/execution-host-audit-only-20261024`
Base HEAD before this patch: `3efbf7cf0802bd133ef856024e3d64075a52ce4d`
Mode: read-only discovery plus isolated fixture tests; no production deployment.

## Result

Overall: `BLOCKED_P0`. Application-level fixes reduce two bypasses through the Claude PreToolUse hook, but the hook is not a security boundary. Remote Desktop Commander (RDC) and the GitHub connector expose independent mutation paths that do not invoke HG's ActionGateway or the Claude hook. Termux does not provide the OS isolation required to mediate those paths.

## Route inventory and evidence

| Route | Result | Evidence / limitation |
|---|---|---|
| RDC direct filesystem write/edit | `BYPASS_CONFIRMED` | Created a disposable file outside the HG repo using RDC `write_file`, changed it using RDC `edit_block`, then read back `RDC_DIRECT_EDIT_BYPASSED_HG_GATE`. No HG gateway/hook was involved. |
| RDC shell | `ALLOWED_CONFIRMED` | `start_process` ran `python3 -c` successfully. |
| RDC child process | `ALLOWED_CONFIRMED` | RDC starts shell/Python processes and lists their PIDs. The session is not restricted to HG's adapter registry. |
| Claude hook: inline interpreter | `PATCHED_IN_TEST_BRANCH` | Baseline `evaluate()` allowed Python inline code. Added fail-closed detection for inline Python, Node, Deno, Bun, Perl, Ruby and PHP code; added regression cases for wrapper commands. This does not block arbitrary script files or replace OS isolation. |
| Claude hook: guard self-modification | `PATCHED_IN_TEST_BRANCH` | Baseline allowed Edit/Write of `.claude/settings.json` and `.claude/hooks/maep_guard.py`. Added both to the protected path set and tests for file tools, shell redirection, in-place edits and Git checkout. Only effective when the hook itself is invoked. |
| HG ActionGateway / policy | `APPLICATION_TESTED_ONLY` | Gateway permits are in-process and do not mediate RDC or GitHub connector operations. A caller with process/file access can operate outside the gateway. |
| HG HTTP API | `PARTIAL` | Production source inspected read-only. Server binds to loopback by default. `/api/health` is public; memory read/search and `/api/ask` require read auth; memory create/delete and durable sync require write auth. No production mutation requests were sent. Live negative tests and token-isolation checks remain unverified. |
| Local IPC / loopback | `UNVERIFIED` | HG and RDC were observed with the same Android UID and SELinux domain. This is not independent OS isolation. Complete socket/IPC enumeration and controlled denial tests require a disposable Linux host. |
| GitHub API connector | `BYPASS_CAPABILITY_CONFIRMED` | Connected identity is `OAI-GIANG`; repository metadata reports admin/push permissions. Available connector actions include file create/update/delete, commits, ref updates and PR merge. No destructive GitHub action was invoked. These actions do not pass through local MAEP hooks. |
| Agent/other tool surfaces | `PARTIAL` | The current session exposes RDC and GitHub mutation tools. No exhaustive inventory of every future/third-party agent, credential, connector, device or API identity is possible from this session. |
| OS isolation | `BLOCKED` | Prior Android/Termux namespace probes failed (`unshare -Ur`: Invalid argument; mount/network/PID namespace creation: Operation not permitted). No isolated Linux VM/host was available. |

## Patch and regression tests

Changed only in the isolated worktree:
- `.claude/hooks/maep_guard.py`
- `.claude/hooks/test_maep_guard.py`

Observed results:
- Hook regression suite: 35 tests passed.
- MAEP suite: 261 tests passed.
- HG suite: 195 tests passed.
- `git diff --check`: passed.
- MAEP + HG application tests total 456 passed; hook tests are an additional 35 tests. Existing ResourceWarnings appeared during HG tests; no test failed.

The tests exercise the hook evaluator and fixture behavior. They do not establish OS-level enforcement, protect against direct RDC calls, protect GitHub credentials, or prove production API denial behavior.

## Required containment architecture

1. Put HG runtime and its state under a dedicated OS identity/container/VM not shared with agent tools.
2. Do not expose general shell, arbitrary filesystem mutation, process control, configuration mutation or broad GitHub write credentials to the HG audit principal.
3. Route all authorized mutations through a narrow broker that validates principal, action, resource, expiry and policy at the effect boundary.
4. Keep enforcement policy and evidence sink outside the runtime's writable namespace; fail closed if the broker, grant, evidence sink or OS isolation is unavailable.
5. Run EH-01–EH-07 in a disposable Linux VM with before/after hashes, process/socket snapshots, negative tests and reproducible fixture reset.
6. Separately review/restrict GitHub connector permissions and branch rules; local hooks cannot constrain API calls made by another connector.

## Closure decision

`BLOCKED_P0`, not `CLOSED_VERIFIED`.

Open blockers:
- `DIRECT_TOOL_BYPASS`: RDC direct write/edit and shell/process access bypass HG policy.
- `GITHUB_API_BYPASS`: connected GitHub identity has repository admin/push capability outside HG policy.
- `OS_ISOLATION_UNVERIFIED`: no isolated Linux VM/host and no OS-denied path tests.
- `API_IPC_MEDIATION_UNVERIFIED`: production API/IPC denial paths have not been exhaustively tested in a disposable fixture.
- `COMPLETE_MEDIATION_UNVERIFIED`: the complete set of possible agents, connectors, credentials and entry points cannot be claimed from current inventory.

Reopen/continue when an owner-provided disposable Linux VM/host and approved narrow access method are available. Do not merge or deploy until the gates have direct, reproducible evidence.
