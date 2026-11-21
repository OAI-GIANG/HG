# G6 Post-merge Staging Cutover and Rollback Rehearsal

Date: 2026-11-18 (+07)
Source: device directory $HOME/hg-staging-postmerge-20261118/rehearsal-20261117T225455Z
Canonical record: SHA256SUMS

## Exact result

- Candidate source commit: 6f6cb96d3120c4d06a7d6def3b37a1953a448d60
- Candidate release ID: 6e6f5f288f88f5d03519875ad5fed4da84006f72db56c67c487d65be03c275b8
- Production release before and after: 030a88d534bdec086c10b87a4732322d72791260178c1129b0538bb3b42bc7d5
- Initial traffic R0: PASS.
- Candidate cutover: SWITCH_OK.
- J2 action/file/memory/tasks: CLOSED_VERIFIED.
- J1 chat: ANSWERED_NO_ACTION (no action).
- Restore to prior production release: RESTORED.
- Controlled TERM interruption: ROLLBACK_READY_VERIFIED.
- Post-restore traffic R2: PASS.
- Overall driver result: REHEARSAL_PASS.
- Production snapshot comparison: prod-diff.txt is 0 bytes.
- Staging supervisor and port were torn down; no staged process/listener remained after rehearsal.

SHA256SUMS validation on device returned OK for every listed evidence file (30/30). The rehearsal directory contained the original before/after snapshots and all logs; they were not modified by this report.

## Acceptance boundary

This verifies only the isolated staging cutover, restoration and rollback procedure. Candidate release 6e6f5f2... was not deployed to production. Production remained on release 030a88d5... and the separate owner production-approval gate remains in force.
