# MAEP Evolution Protocol V1
Loop: observe -> capture evidence -> hypothesis -> proposal -> risk assessment -> policy review -> scoped implementation -> tests -> verification -> accept/reject -> record learning.

The system MAY propose improvements within authorized scope. It MUST NOT grant itself authority, relax a mandatory gate for its own candidate, erase failure evidence or silently change canonical policy. Policy changes require a new version and explicit authorization. Every material change has baseline, scope, criteria, risk assessment, test plan and proportionate recovery plan. Rejected proposals remain available for learning with provenance, confidence, applicability and freshness.

Rollback is a new controlled action, not deletion of history. Verify target and recovery material before rollback; run consistency checks afterwards. If safe recovery is unknown, stop BLOCKED.
