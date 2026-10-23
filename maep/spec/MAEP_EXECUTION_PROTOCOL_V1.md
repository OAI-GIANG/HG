# MAEP Execution Protocol V1
1. Intake: validate task envelope and canonical input references.
2. Assess: classify read-only/side-effecting actions, scope, trust boundary, risk and dependencies.
3. Plan: define ordered actions, acceptance, evidence, stop conditions and recovery.
4. Authorize: evaluate principal/action/resource/scope/conditions against current policy.
5. Execute: re-check authorization before each side effect; record action identity/outcome.
6. Verify: compare observed results with criteria using candidate-bound evidence.
7. Accept: all mandatory criteria and gates must PASS.
8. Close: record final state, limitations, gate/evidence references and timestamp.

Lifecycle: DRAFT -> READY -> ASSESSED -> PLANNED -> AUTHORIZED -> RUNNING -> VERIFYING -> ACCEPTED -> CLOSED_VERIFIED. Alternative outcomes: BLOCKED, FAILED, CANCELLED, UNVERIFIED. Only transitions in STATE_TRANSITION_TABLE_V1.md are allowed.

Drafts may be incomplete but cannot execute. A blocker is not success or failure: record knowns, unknowns, missing prerequisite, next action and reopen condition. After three meaningful failed attempts on the same approach, stop it; do not repeat identical calls merely to increment count. Stop earlier for safety, irreversible risk or no progress.

Stop if authority is missing, target/candidate is uncertain, required evidence cannot be preserved, recovery is unsafe or scope is exceeded. Inspect live state before resuming. Never blindly replay an uncertain non-idempotent action.
