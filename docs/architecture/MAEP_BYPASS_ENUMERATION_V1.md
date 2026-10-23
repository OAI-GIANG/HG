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

## Round 2 — interpreter, shell-indirection and path-alias regressions

After the first commit, additional tests exposed more gaps in the hook parser. The isolated branch now also:

- rejects Python/Node/Deno/Bun/Perl/Ruby/PHP script-file execution by these interpreters unless the supported test module path is used;
- rejects shell script-file execution through bash/sh/zsh/dash unless the command is explicitly parsed as `-c`;
- rejects opaque command substitution, backticks, process substitution, `eval`, `xargs`, `find -exec/-execdir/-ok/-okdir`, `env -S` wrapper indirection and Git command-scoped config that could inject aliases/hooks;
- constrains Python unittest module execution to discovery in allowlisted test roots;
- resolves filesystem paths before checking protected trust files, with fixture tests for symlink aliases and `..` path traversal;
- retains regression coverage for the original inline interpreter and hook self-modification cases.

Observed test results for this round:
- `python3 .claude/hooks/test_maep_guard.py`: 40 passed.
- `python3 -m unittest discover -s maep/tests -p 'test_*.py'`: 261 passed.
- `python3 -m unittest discover -s hg/tests -p 'test_*.py'`: 195 passed.
- `git diff --check`: passed.

These remain evaluator tests, not proof that all possible executables, interpreter flags, aliases, filesystem races, or external tool paths are mediated. Direct execution of arbitrary binaries and the independent RDC/GitHub mutation surfaces remain outside this hook.

## EH-01–EH-07 disposable-host acceptance runbook

Do not run these tests on production or on the Termux host sharing identity with PID 15005. A disposable Linux VM/host must be supplied and confirmed isolated first.

- EH-01 inventory: record VM image/digest, kernel, UID/GID, namespaces, mounts, capabilities, seccomp/LSM profile, all listeners, Unix sockets, process tree, installed agents/connectors and credentials visible to the test principal.
- EH-02 protected mutation denial: using only disposable fixtures, attempt write, append, truncate, unlink, rename, chmod, hardlink/symlink, and directory replacement against protected policy, trust-root, executable/config, evidence collector and fixture files. Require OS-level denial and identical before/after hashes.
- EH-03 execution/escape denial: test shell, child process, interpreter inline/file execution, PATH substitution, symlink traversal, procfs, namespace creation, local sockets, network sockets and unlisted API entry points. Record exact exit status and stderr; no destructive test outside the fixture.
- EH-04 enforcement self-protection: attempt to alter policy, hook, broker, trust-root cache, service configuration and evidence sink; test missing, expired, malformed and revoked grants fail closed.
- EH-05 side-effect absence: snapshot fixture hashes, file metadata, process tree, listening sockets and network counters before/after every denied operation; any unexpected delta fails the gate.
- EH-06 reproducibility: pin candidate commit, VM image, kernel, test fixture manifest and command list; reset to clean fixture; rerun twice; store outputs and hashes in a separate append-only evidence domain.
- EH-07 independence: prove the VM has no production mounts, secrets, shared writable directories, inherited production sockets, shared process namespace or credential access.

Current result remains `BLOCKED_P0`: the required independent Linux host is not available in the inspected session. API/IPC authorization and OS-enforced negative tests remain unverified; do not infer their success from the application suites.
