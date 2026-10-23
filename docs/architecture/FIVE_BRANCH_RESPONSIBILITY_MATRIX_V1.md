# Five-Branch Responsibility Matrix V1

Status: **DESIGN — NOT IMPLEMENTED**

| Branch | Owns | Inputs | Outputs | Allowed authority | Explicit non-responsibilities |
|---|---|---|---|---|---|
| HG Brain | Reasoning, decomposition, planning candidates, trade-off analysis | Task context, constraints, trusted knowledge refs | Candidate plan, rationale, uncertainties | Pure reasoning and scoped reads | No task dispatch ownership, no policy changes, no self-authorization |
| Memory & Knowledge | Retrieval, persistence, provenance, versioning and knowledge quality metadata | Scoped query or authorized write request | Data refs, source/provenance metadata, write receipt | Read/write only through approved APIs and scope | No task orchestration, no silent writes, no authority grant |
| Creativity & Research | Research workflow, source collection, synthesis, hypothesis generation | Research question, source limits, evidence requirements | Research record, source refs, disagreements and limitations | Scoped research/read actions | No policy authority; no treating hypothesis as verified fact |
| Tools & Automation | Tool adapters and bounded execution | Authorized operation envelope, minimal inputs | Result, effect summary, evidence refs, structured errors | Only exact action/resource/scope authorized | No unrestricted ambient access, no self-expansion, no blind retry |
| Security & Verification | Threat analysis, validation, test execution plans/results, evidence checking | Candidate, test contract, evidence refs | Findings, verification status, blockers and risk assessment | Read and test within assigned scope; report findings | No independent-review claim without independent evidence; no permission grant; no policy override |

## Shared rules

1. BrainOrchestrator is the only cross-branch coordinator.
2. MAEP is cross-cutting governance, not a sixth functional branch.
3. Cross-branch interaction uses versioned contracts and references.
4. A branch owns its data and implementation internals; consumers use its public interface.
5. A branch may not call another branch's private modules.
6. All side effects pass MAEP authorization and adapter enforcement.
7. Shared libraries must be pure or have an explicitly documented owner and trust boundary.
8. Security findings can block or inform a gate but do not independently grant authorization.
9. Research and memory data do not become trusted merely because they are stored.
10. No new branch/module is accepted without an ADR showing a distinct responsibility and why existing owners are insufficient.

## Duplicate-capability review questions

For every proposed module, document: capability; existing owner; reason current owner cannot satisfy the need; new trust boundary; dependency impact; test ownership; lifecycle; and removal cost. If no concrete boundary or capability gap is demonstrated, reuse the existing owner.
