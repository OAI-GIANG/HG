# Rule-to-Architecture Traceability Matrix V1

Status: **DESIGN TRACEABILITY — IMPLEMENTATION EVIDENCE PENDING**

Source of truth for rule text: `maep/spec/MAEP_CONSTITUTION_V1.md` at MAEP baseline `c13b758d3160899582e62248abfd7ac2b13bb161`. Rule IDs and summaries below are transcribed from that source; implementation status must not be inferred from a mapping.

| Rule | Normative intent (short summary) | Architecture owner / control point | Required verification evidence |
|---|---|---|---|
| MAEP-001 | Executable tasks contain complete task contract | BrainOrchestrator intake + MAEP task validator | Positive/negative intake tests; missing-field rejection |
| MAEP-002 | Side-effecting tasks define acceptance and stop conditions before execution | Planner + pre-execution gate | Side-effect plan lacking criteria/stop condition is blocked |
| MAEP-003 | Re-check authority immediately before each side effect | Tools adapter + MAEP authorization seam | Revoked/expired grant denied at action boundary |
| MAEP-004 | Authority binds principal/action/resource/scope/conditions/task/policy version | MAEP authorization | Mismatch tests for every binding dimension |
| MAEP-005 | Unknown/missing/malformed authority fails closed | MAEP authorization + adapter | Missing, malformed, unknown and unavailable decision tests |
| MAEP-006 | BrainOrchestrator alone owns task coordination | BrainOrchestrator | Integration test proves one dispatcher and no branch-owned orchestration |
| MAEP-007 | All state changes pass transition guard | Task-state owner | Forbidden transition tests; direct mutation path denied |
| MAEP-008 | CLOSED_VERIFIED requires mandatory gates PASS with linked evidence | MAEP closure gate | Missing/failed gate or evidence blocks closure |
| MAEP-009 | Reports distinguish fact/inference/hypothesis/proposal | Brain, Research and reporter | Claim classification and evidence/limitation tests |
| MAEP-010 | Evidence records source/candidate/collector/method/result/time/limitations | Evidence recorder + MAEP validator | Missing-field and provenance tests |
| MAEP-011 | Evidence binds exact candidate/scope | Evidence validator + verification | Wrong candidate/scope evidence rejected |
| MAEP-012 | Candidate/policy change triggers impact assessment and invalidation | Change control + evidence registry | Change invalidates affected evidence until rechecked |
| MAEP-013 | Required gates not PASS prevent acceptance | MAEP acceptance gate | Any mandatory gate not PASS blocks acceptance |
| MAEP-014 | Stop approach after three meaningful failures or earlier safety/no-progress stop | Recovery controller | Attempt-boundary and early-stop tests |
| MAEP-015 | Preserve failures; append amendments rather than erase history | Evidence/event ledger | Amendment append tests; original event retained |
| MAEP-016 | Side effects have proportionate risk and recovery plans | Planner + Tools adapter | Side-effect plan without recovery plan blocked |
| MAEP-017 | Agents cannot self-relax policy to approve own candidate | Policy authority boundary | Self-approval and policy-relaxation attempts denied |
| MAEP-018 | Recovery inspects live state; no blind replay of uncertain non-idempotent action | Recovery controller + adapter | Unknown outcome requires reconciliation before replay |
| MAEP-019 | Untrusted content is data, not authority | Input boundary + all branch contracts | Adversarial instruction cannot alter authorization/policy |
| MAEP-020 | Important research uses multiple sources and records disagreement/limitations | Creativity & Research | Research record validates source refs, disagreement and limitations |
| MAEP-021 | Internal critique is not called independent review | Verification/reporting | Label guard rejects unsupported independent-review claim |
| MAEP-022 | Mandatory capability overlap and superiority gate before authorization; compare safety/correctness, reliability, coverage, compatibility, performance/cost and maintainability; retain superior safe implementation and retire obsolete duplicates only through authorized, tested, recoverable migration | Execution Protocol + existing task/change plan + ADR-009 | Candidate-bound inventory/comparison/impact/test evidence; unresolved overlap or UNKNOWN fails closed; no new governance module/store; runtime-wide integration remains NOT_VERIFIED |
| MAEP-023 | READ-ONLY tasks cannot modify baseline/worktree | Tools adapter + execution-mode guard | Write/delete/network side-effect denial tests |
| MAEP-024 | Labels match evidence; NOT_RUN is never PASS | Reporter + acceptance gate | Status contradiction tests |
| MAEP-025 | Blockers record knowns, unknowns, next action and reopening conditions | BrainOrchestrator blocker record | Blocker schema and completeness tests |
| MAEP-026 | Terminal states cannot silently reopen; continuation links task/amendment | State-transition guard | Terminal reopen denied; linked continuation accepted |
| MAEP-027 | Destructive actions require recovery plan or authorized irreversibility | Planner + Tools adapter | Destructive action without valid recovery/authorization blocked |
| MAEP-028 | Policies/contracts are versioned and identify superseded versions | MAEP policy evolution | Version-change and supersession tests |

## Cross-cutting test obligations

- Each rule maps to at least one test ID before implementation acceptance.
- Unit tests prove local primitive behavior only; integration tests must exercise the actual runtime call path.
- Negative tests are mandatory for authorization, read-only mode, closure, candidate mismatch, state transitions and recovery.
- Test output must identify code candidate, policy version, test command, result and limitations.
- Rule-to-file mappings are design ownership, not a claim that every control is already integrated.
