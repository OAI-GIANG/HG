# Runtime.service policy action matrix — proposed scope, not active authority

Source-derived operation matrix for owner review. No permission is granted by this document.

| Operation | Candidate action/resource/scope from route code | Recommendation |
|---|---|---|
| Create task | `WRITE`, `memory:task/<task_id>`, `memory:task:<task_id>:write` | Permit only for authenticated owner principal if this is an intended runtime function and generated task ID is validated; per-task exact resource. |
| Read task | `READ`, `memory:task/<task_id>`, read scope contract must be confirmed from `GET` path implementation | Restrict to exact task resource and explicit read scope; do not use wildcard scopes. |
| Transition task | `WRITE`, `memory:task/<task_id>`, `memory:task:<task_id>:transition` | Permit only actions/states allowed by MAEP state machine and exact task. |
| Write evidence | `WRITE`, resource `memory:evidence/<evidence_id>` bound to configured store, scope `memory:task:<task_id>:evidence:write` | Exact evidence/task binding; verified candidate/policy lineage required. |
| `fs.write` | `WRITE`, `file:<relative_path>`, scope prefix such as `file:out` | Allow only under a dedicated output root; exact resource matching; no authority/config/session/Memory path. The scope string must be confirmed against route/task contract before activation. |
| Dispatch | Action/resource/scope are request-specific, e.g. `WRITE`/`file:<relative_path>` for `fs.write` | No generic dispatch grant. The policy must match each registered adapter and exact request, with MAEP-022 acceptance gate and read-back required. |
| Reconcile | Route constructs a `READ` request with resource `reconcile`, scope `[]` | Current native engine requires a non-empty requested scope; confirm this route's contract and whether reconciliation has a separate read-only authority path before allowing it. Do not paper over the mismatch. |
| Review/simulate | Route requests `READ` on `memory:task/<task_id>` with empty `scope` | Must reconcile with the native engine's non-empty scope requirement. Leave blocked pending exact route-contract fix or owner-approved scope semantics. |
| Push/merge/deploy/delete/execute | Not a blanket runtime endpoint permission | Exclude from initial runtime-service API policy. Existing repository/tool authorization remains separately action-specific. |

## Critical pre-activation checks

The runtime routes for reconcile and review construct empty scopes while NativePolicyEngine currently rejects empty requested scopes. This is a contract mismatch that must be resolved in code or a documented, safe route-specific authorization design before these operations can be included in an ACTIVE policy. Do not use a broad wildcard rule to hide it.
