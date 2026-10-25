# MAEP Risk Register V1
| ID | Risk | Severity | Mitigation | Closure evidence |
|---|---|---|---|---|
| R-01 | Rules prose-only | High | executable guards and tests | test per MUST |
| R-02 | Orchestrator single point failure | High | recovery and blocked state | recovery tests |
| R-03 | False closure | High | gate/evidence guard | negative tests |
| R-04 | Excess authority | High | least privilege/scope | authorization tests |
| R-05 | Legacy content imported unreviewed | Medium | source provenance and adoption decision | source register |
| R-06 | Stale memory | Medium | provenance/freshness/supersession | memory tests |
| R-07 | Architecture bloat | Medium | module economy gate | ADR |
| R-08 | Migration data loss | High | recovery and consistency checks | restore tests |
| R-09 | Evidence reused on wrong candidate | High | candidate binding | mismatch test |
| R-10 | Missing permissions hidden | High | explicit BLOCKED | reporting test |
| R-11 | Partial JSON Schema support overstated | High | disclose stdlib validator scope | conformance statement |
| R-12 | Policy relaxed to pass candidate | High | separately authorized version change | negative test |
| R-13 | Unknown action outcome replayed | High | reconcile before retry | recovery test |
| R-14 | Rule/code drift | Medium | traceability audit | coverage report |

| R-15 | Lost or reconstructed task context across sessions/restarts | High | versioned continuity record, durable checkpoint, mandatory live-state reconciliation, fail-closed resume | AF-001–AF-016 plus restart and HG end-to-end evidence; currently NOT_VERIFIED |
