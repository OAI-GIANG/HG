# HG Runtime Binding Reconciliation — 2026-10-23

## 1. Decision

**P0 RESULT: BLOCKED — current production runtime is not proven to be bound to the current `OAI-GIANG/HG` candidate or to the new `brain.planning` implementation.**

This was a READ-ONLY inspection through Remote Desktop Commander on the Termux device. No repository files were changed by the investigation before this report was created. No service was restarted, patched, deployed, stopped, or reconfigured. No commit/push/merge/checkout/reset/stash/cleanup was performed. No secret values were intentionally read or emitted.

## 2. Scope and candidate identity

- Repository directory: `/data/data/com.termux/files/home/HG`
- Remote origin, credential-redacted: `https://github.com/OAI-GIANG/HG.git`
- Branch: `stt/maep-v1-20261022`
- HEAD: `f7f00a75c6a1b1363993c2fb9bc023171f080038`
- MAEP: `MAEP-1.2.0`
- Prior checkpoint read: `brain/INTELLIGENCE_UPGRADE_CHECKPOINT_20261023.md`
- Checkpoint conclusion: locally implemented/tested; production integration unverified; Lv5 not certified.

The working tree was already dirty before this reconciliation, with multiple modified and untracked files, including the new Brain/planning files. These pre-existing changes were left untouched. The reconciliation report itself is the only intended new output of this task.

## 3. Runtime evidence collected

### 3.1 Supervisor and service entrypoints

Read-only `sv status` results:

| Service | Observed status |
|---|---|
| `hg2-runtime` | running, PID 15005 |
| `hg2-model` | running, PID 15010 |
| `hg-runtime` | down |
| `hg-backend` | down |

The active `hg2-runtime` supervisor script was inspected without reading its referenced environment file. It:
1. sources `/data/data/com.termux/files/home/.config/hg/hg2-runtime.env`;
2. unsets several edge/vision variables;
3. changes directory to `/data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676`;
4. launches `python3 -u -m hg.server`.

This is a separate release directory, not the candidate checkout at `/data/data/com.termux/files/home/HG`.

The `hg2-model` supervisor script points to a local `llama-server`, model file `qwen2.5-1.5b-instruct-q4_k_m.gguf`, loopback host `127.0.0.1`, port `8788`, and a key-file path. Secret contents were not opened or printed. A running supervisor does not by itself prove that the model endpoint is healthy, that its key is accepted by the planner adapter, or that the runtime invokes the planner.

### 3.2 Active release manifest and source

Release directory:
`/data/data/com.termux/files/home/hg2-releases/fcc561ae919b64572c5a9b549d5664b7fbfd4676`

Read-only observations:
- `manifest.json` reports name `hg`, version `1.0.0`, runtime `python>=3.10`, `origin: clean_room`, and 16 listed modules.
- The module list includes `hg.brain_orchestrator`, but does not list `brain.planning` or the candidate package `brain.planning`.
- The live release's `hg/server.py` imports `hg.brain_orchestrator.BrainOrchestrator` and constructs `BrainOrchestrator()` in the request handling path.
- A read-only recursive search of the release's `hg/` Python files found no `PlanningEngine`, `brain.planning`, or `plan_task` references.
- The release directory is not a Git working tree; `git rev-parse` and `git status` returned “not a git repository”. Therefore its directory name alone is not independent proof of a source commit.

Selected SHA-256 evidence:
- Active release `manifest.json`: `997e540082cc5498b6c79ef9218c27fed7db5ef3deb9a0078daa71e792fe0118`
- Active release `hg/server.py`: `959a8228bceb453d41b6f61d039679709672599c47428828b9abf5943ed84faa`
- Candidate checkpoint: `8ae4d771d95c4021ed5b72436b8b2fdea8db3492bf5fefad7bb65e2cff75a9bd`
- Candidate `runtime/composition.py`: `b58be22d392ec3a7ed97f2a17db8a4c4e648b2a2b24979b13958f8ef90d15458`
- Candidate `runtime/http_server.py`: `ba11bb3f67eb76157ef0f10af57df0f4302924b72b3b7f7b418190f5512baa1f`
- Candidate `brain/orchestrator.py`: `a0402d3d3e775738f7bbac832f10c2e3f0d1eabc16de4f4506436368fe5b03ef`
- Candidate `brain/planning.py`: `b715c80727ee987df852251ba40a3c83dda769950d5660217f3a70bcc0e30a7a`

### 3.3 Read-only health request

A GET request to the local `/api/health` endpoint on port 8787 returned:
- product: `HG`
- runtime: `READY`
- integrity: `ok=true`, reason `chain_ok`, 13 events
- provenance: `ok=true`
- startup and current source manifest digest match: `4fcc892b1f95c37143e5e75590afbdbc349c9128d647e831067b9dd6eacd751c`
- source file count: 37
- edge configured: false

This proves the running service's own integrity/provenance check passes for its current release source set. It does **not** prove that the source set corresponds to current candidate HEAD `f7f00a75c6a1b1363993c2fb9bc023171f080038`, nor that the new planner is loaded. The service's provenance implementation hashes files under its own `hg/` directory and UI file; it is not a Git source identity comparison against the candidate checkout.

## 4. Candidate integration compatibility

Candidate implementation exposes:
- `runtime/composition.py`: optional explicit `reasoning_provider` and `context_resolver`; planner injection is opt-in.
- `brain/orchestrator.py`: `plan_task(task_ref=..., candidate_target=..., context_refs=...)`.
- `brain/planning.py`: bounded plan validation and optional loopback OpenAI-compatible model provider.

The active service instead imports the separate `hg.*` package, constructs its own `hg.brain_orchestrator.BrainOrchestrator()`, and has no observed import/call to the new candidate's `brain.planning` package. The candidate `runtime/http_server.py` is a separate transport adapter and was not observed in the active service's startup command.

**Conclusion:** no verified import, composition, route, dependency, or build-manifest link connects the current runtime to the new planner. Compatibility is therefore **UNVERIFIED**, and production binding is **BLOCKED**. The local model's presence is a potential future provider target only; it is not evidence of integration.

## 5. Findings and root causes

### F-01 — Candidate/runtime source mismatch (P0)
- **Finding:** active process runs from an immutable-looking HG2 release directory, while candidate changes live in `~/HG`.
- **Evidence:** supervisor `run` script, active `hg/server.py` imports, candidate HEAD and separate candidate module paths.
- **Root cause:** separate source roots and package/import contracts; no verified release manifest mapping the active source to the candidate Git commit.
- **Risk:** claiming that candidate functionality is active when the running process does not load it.
- **Status:** BLOCKED.

### F-02 — Planner absent from active release source set (P0)
- **Finding:** active release module inventory and recursive Python search show no planner import/call.
- **Evidence:** manifest module list and source search; active server creates the legacy `hg.brain_orchestrator.BrainOrchestrator()`.
- **Root cause:** the new planner was added to the candidate's `brain/` and `runtime/` architecture, not integrated into the separate `hg.server` release.
- **Risk:** new reasoning/planning capability is unreachable from the production API.
- **Status:** BLOCKED.

### F-03 — Provenance is release-local, not candidate-binding proof (P1)
- **Finding:** health reports a valid 37-file runtime source manifest, but the manifest check covers the active release's own `hg/` files and UI.
- **Evidence:** live health response and active release `hg/provenance.py`.
- **Root cause:** runtime source-manifest validation is not a comparison to the current candidate Git HEAD or its complete build artifact manifest.
- **Risk:** an internally consistent release can still be unrelated to the candidate being audited.
- **Status:** active-release integrity VERIFIED; candidate linkage UNVERIFIED.

### F-04 — Real model and trusted context integration not proven (P1)
- **Finding:** local model supervisor script exists, but no E2E evidence proves planner provider configuration, authentication compatibility, trusted context resolver, or actual model call from the active API.
- **Evidence:** checkpoint explicitly says live inference and trusted production resolver were not run/provisioned; current runtime lacks planner call.
- **Root cause:** optional provider/context injection is not wired into active `hg.server`.
- **Risk:** apparent planning capability remains test-only or unreachable.
- **Status:** BLOCKED.

## 6. Safe integration plan (not executed)

Do not hot-patch the active release and do not repoint its supervisor in place.

1. **Freeze the current state as evidence only:** preserve active release directory, running service, current candidate working tree and all existing changes. Record candidate HEAD, selected file hashes, release source-manifest digest, and current health response.
2. **Create a separate candidate build/staging directory** from an explicitly approved `OAI-GIANG/HG` candidate. Do not build from an unreviewed mixture of dirty working-tree files without an explicit source manifest listing every included path and hash.
3. **Define an explicit adapter boundary:** map the current HTTP request contract to candidate `runtime/composition.py` and `BrainOrchestrator.plan_task`; do not make the legacy orchestrator silently interchangeable with the new class.
4. **Provision dependencies explicitly:** trusted root/policy/candidate provider, verified context resolver, and local model provider. Inject the model credential from the approved runtime secret mechanism without reading it into logs, prompts, command output or the repository. Fail closed if any required provider is absent or stale.
5. **Build and verify in isolation:** source manifest must identify `OAI-GIANG/HG`, exact candidate commit, complete source file hashes, dependency versions and entrypoint. Independently compute the manifest again from the staged artifact. No live service changes.
6. **Run non-destructive E2E against a separate loopback port and isolated state directory:** test successful plan proposal, invalid JSON, scope escape, stale policy, wrong candidate, unavailable model, timeout, malformed context, and model response tampering. Confirm that planning never invokes an adapter, writes Memory, or changes canonical task state.
7. **Run negative security checks:** candidate/policy drift must block before model invocation; credentials must not appear in logs; HTTP redirects/public endpoints must be rejected; plan digest tampering must fail; UNKNOWN must not be treated as success.
8. **Only after acceptance:** prepare a separate release artifact and a rollback procedure. Obtain explicit deployment authorization before any service configuration or process changes. Keep the existing runtime untouched until that authorization and deployment window exist.

## 7. Production acceptance checklist

- [ ] Exact `OAI-GIANG/HG` repository and candidate commit are bound to the staged artifact.
- [ ] Source manifest contains all runtime files and is reproducible from the staged build.
- [ ] Entrypoint and import graph demonstrably load the candidate's `BrainOrchestrator` and `PlanningEngine`.
- [ ] Trusted root, active policy, candidate provider and context resolver pass real integration checks.
- [ ] Local model endpoint is reachable from staging, authentication works, and no secret is exposed.
- [ ] Positive E2E returns `VALIDATED_PLAN_NOT_AUTHORIZED` with correct task/candidate/policy binding.
- [ ] Negative E2E rejects wrong repository/candidate, stale policy, untrusted context, malformed output and out-of-scope resources.
- [ ] Planning performs no action execution, no authorization grant, no task-state mutation and no unintended Memory write.
- [ ] Model outage/timeout, provider error and UNKNOWN fail closed with bounded resource use.
- [ ] Regression suite, compile checks, schema validation and `git diff --check` pass on the exact staged candidate.
- [ ] Health reports the expected source manifest and candidate identity; both remain stable after process start.
- [ ] Rollback artifact and operational steps are documented and validated without affecting the current runtime.
- [ ] Separate deployment authorization is received before touching production.

## 8. Checkpoint and stop condition

**Checkpoint:** current service remains running in its pre-existing state; no service mutation occurred. The candidate working tree remains otherwise unchanged by this read-only reconciliation. This report is the requested output artifact.

**Stop condition:** keep production binding and Lv5 claims BLOCKED until exact candidate provenance, planner import/call path, approved live providers, non-destructive end-to-end evidence and deployment authorization are established.

## Next command

```text
STT — HG — MAEP — P0 STAGING BUILD DESIGN
READ-ONLY / DESIGN ONLY.
Use the findings in HG_RUNTIME_BINDING_RECONCILIATION_20261023.md.
Specify an isolated staging build and adapter contract for OAI-GIANG/HG.
Do not modify the active release, working tree, service configuration, or runtime.
Do not deploy. Output the exact manifest fields, build steps, negative tests,
rollback prerequisites, and acceptance gate.
```
