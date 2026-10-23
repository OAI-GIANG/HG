# MAEP State Transition Table V1
States: DRAFT, READY, ASSESSED, PLANNED, AUTHORIZED, RUNNING, VERIFYING, ACCEPTED, CLOSED_VERIFIED, BLOCKED, FAILED, CANCELLED, UNVERIFIED.

Allowed:
- DRAFT -> READY
- READY -> ASSESSED
- ASSESSED -> PLANNED
- PLANNED -> AUTHORIZED
- AUTHORIZED -> RUNNING
- RUNNING -> VERIFYING | BLOCKED | FAILED
- VERIFYING -> ACCEPTED | UNVERIFIED | BLOCKED | FAILED
- ACCEPTED -> CLOSED_VERIFIED
- BLOCKED -> ASSESSED | CANCELLED
- UNVERIFIED -> VERIFYING | BLOCKED
- FAILED/CANCELLED -> DRAFT only by creating a new linked task, never by mutating the terminal task.

Guards: READY requires complete task envelope; AUTHORIZED requires valid authorization; RUNNING requires current authority and prerequisites; VERIFYING requires a result/candidate; ACCEPTED requires all mandatory criteria/gates PASS; CLOSED_VERIFIED requires complete closure evidence and no mandatory blocker. BLOCKED -> ASSESSED requires evidence the blocker condition changed and a fresh authority/risk assessment.

Forbidden shortcuts include DRAFT->RUNNING, PLANNED->RUNNING, RUNNING->ACCEPTED, VERIFYING->CLOSED_VERIFIED, BLOCKED->RUNNING without reassessment, UNVERIFIED->ACCEPTED without verification, and direct state mutation outside the guard. If state is unknown, remain BLOCKED/UNVERIFIED.
