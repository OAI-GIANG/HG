# MAEP Threat Model V1
Assets: canonical source/baseline, authority decisions, policy versions, task state, evidence/tests, memory provenance, recovery material.
Trust zones: TZ0 owner-authorized policy; TZ1 BrainOrchestrator/governance primitives; TZ2 scoped specialist modules/tool adapters; TZ3 external/user/tool content not verified; TZ4 agent claims without corroboration.

Threats and controls:
- TH-01 prompt injection: external content is data; adversarial tests must not grant authority.
- TH-02 privilege escalation: exact scope check at action time.
- TH-03 state bypass: centralized transition guard and negative tests.
- TH-04 false closure: mandatory gate/evidence closure guard.
- TH-05 candidate mismatch: exact candidate binding.
- TH-06 evidence deletion: preserve history; corrections append amendments.
- TH-07 crash/retry duplication: inspect state, avoid blind replay.
- TH-08 competing orchestrators: BrainOrchestrator sole coordinator.
- TH-09 schema/business confusion: validate shape and business invariants separately.
- TH-10 policy self-relaxation: separately authorized policy version change.
- TH-11 partial/timeout tool output: distinguish success, empty, timeout and error.
- TH-12 migration data loss: recovery plan and pre/post consistency checks.

Fail closed on unknown authority, resource, scope, state, required gate or safety precondition. Read-only degraded mode only when policy allows and uncertainty is disclosed. Recovery reconciles uncertain non-idempotent outcomes before retry; unknown state stays BLOCKED/UNVERIFIED.
