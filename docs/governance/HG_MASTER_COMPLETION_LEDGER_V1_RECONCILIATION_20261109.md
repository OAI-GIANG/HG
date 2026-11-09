# HG MASTER COMPLETION LEDGER V1 — RECONCILIATION 2026-11-09

**Repository:** `OAI-GIANG/HG`
**Observed on:** 2026-11-09 (Asia/Ho_Chi_Minh), read-only GitHub REST, local git history
**Relation to snapshot:** ADDITIVE. The 2026-11-06 snapshot (`HG_MASTER_COMPLETION_LEDGER_V1.md`, `.csv`, `.sha256`) is unchanged and remains provenance. This file records what changed after it. Where the two disagree, the snapshot describes 2026-11-06 and this file describes 2026-11-09.

**Labels:** FACT = observed in GitHub or git during this reconciliation. INFERENCE = derived from FACT. UNKNOWN = not established. PROPOSAL = recommendation for owner decision.

---

## 1. Reconciled facts

| Item | State on 2026-11-09 | Source |
|---|---|---|
| `main` tip | `61d26cf8259ecbc94121f953b3a9d22406ac0853` (snapshot tip was `63f9e120858bca0371eb43986da40c56b1b1b811`) | FACT, `git rev-parse origin/main` |
| PR #82 | MERGED. Merge commit `5536c598f3dae40c6fe9eade4fc75fd8ebd0c3c9`, head `71566ea55ee3641febe15eba3cd351cb0c443859`. Title: `test(s03): exercise evidence cross-store failure recovery` | FACT, REST `pulls/82` |
| PR #83 | MERGED. Merge commit `61d26cf8259ecbc94121f953b3a9d22406ac0853`, head `d03ae464e32413009a901c8e2a6db4526d2ae449`. Title: `fix(ledger): refuse a torn final record instead of reading it as committed (C1)`. PR body states that evidence idempotency (`evidence_operation_id`, EC07 part 2) is out of scope and follows in a separate PR. | FACT, REST `pulls/83` |
| PR #81 (this ledger) | OPEN, **HOLD: do not merge** (owner direction 2026-11-09). Base `63f9e120…` (behind main, no file overlap). Head at snapshot `b207f3bcd493156173eb8f1d545546ad267007f7`; this reconciliation adds a commit on top. Formal reviews: 0. | FACT, REST `pulls/81`, `/reviews` |
| PR #77 (listener attestation HG-LA-2) | OPEN, **HOLD**. Head `c096cbf18d1e42623827e73585fda9929e4d69f9`. Compare with `main` `61d26cf`: `diverged`, ahead 16, behind 5, 67 files changed. Formal reviews: 0. Review comments: 0. Issue comments: 1 (2026-10-31, posted under the owner's GitHub account by an agent session; it is agent-authored and is NOT owner approval). | FACT, REST `compare/main...feat/listener-attestation-hg-la-2-20261031`, `pulls/77/reviews`, `issues/77/comments` |
| PR #77 checks on head `c096cbf` | `unittest (3.13)` SUCCESS; `unittest (3.14)` SUCCESS; `rt06-anchor (3.13)` SUCCESS; `rt06-anchor (3.14)` SUCCESS; `l5-capability-gate (real kernel; red = BLOCKED)` FAILURE. Run `42260873155`, job `128040142435`. | FACT, REST `commits/c096cbf…/check-runs` |
| Open PRs (2026-11-09) | #81 (ledger, HOLD); #77 (listener attestation, HOLD); #64 (opt-in policy v2, base `stt/maep-v1-20261022`, frozen branch); #55 (Claude setup, base main, last update 2026-10-26); #11 (draft, audit-only execution host, last update 2026-10-25) | FACT, REST `pulls?state=open` |
| PR #61 | MERGED to `stt/maep-v1-20261022` (merge `ba12ada35800542d2596fa7761926abd6e2586b2`), NOT to `main`. Unchanged from snapshot. | FACT, REST `pulls/61` |

**Ancestry check (FACT):** merge commits of PR #78 (`ee0b648`), PR #79 (`e99c83e`) and PR #80 (`63f9e12`) are ancestors of `origin/main`.

---

## 2. Denominator and statuses

- Denominator unchanged: **15 functional workstreams** (WS-01 … WS-15). WS-00 remains tracked and not counted.
- **DONE: 0.** No status was upgraded by this reconciliation.
- Evidence deltas per workstream (status unchanged; see CSV companion file):
  - **WS-01:** PR #83 merged (torn final record refused, C1). Still IN_PROGRESS: state-owner inventory and EC03–EC06 open.
  - **WS-04:** PR #82 merged (cross-store failure recovery tests); PR #83 touches ledger refusal. Still IN_PROGRESS: independent false-accept oracle, cross-store recovery acceptance, and evidence idempotency (EC07 part 2) are not implemented.
  - **WS-12:** PR #77 head moved to `c096cbf`; unit and RT06 checks green; L5 gate BLOCKED; zero formal reviews. Still IN_PROGRESS. PR #77 remains HOLD.

---

## 3. PR #77 — L5 capability evidence

- FACT: the `l5-capability-gate` job defines red as BLOCKED. Its log (job `128040142435`) shows `HG_REQUIRE_PROC_TESTS=1` turning three probe tests into failures with status `BLOCKED`, gaps `UNINSPECTABLE_SAME_UID`, `UNINSPECTABLE_ROOT`, `UNINSPECTABLE_OTHER_UID`, `UNREADABLE_DESCRIPTORS`, `SCOPE_PARTIAL`, and reason `SHARING_SCAN_INCOMPLETE`.
- FACT (local, cloud sandbox, Linux, root, Python 3.13.18, `python3 -I -m unittest discover -s hg/tests -t . -p test_l5_probe.py` on the materialised `c096cbf` tree): 29 tests, OK, **skipped=3**. The three skips are the tests that require complete `/proc` observation, with the same runner-policy reason.
- INFERENCE: the cloud sandbox is not a runner that satisfies the L5 gate. Unit tests and RT06 are green; the L5 evidence gap is environmental.
- UNKNOWN: whether any available Linux or Android environment satisfies complete `/proc` and `pidfd_getfd` observation for the target. No such environment has been verified.
- PROPOSAL (owner decision required): (a) provide an owner-controlled Linux runner or device where the probe can run without the runner-policy gaps; or (b) accept L5 as BLOCKED for this PR and split the PR so the non-L5 parts can be reviewed on their own; or (c) keep the PR HOLD. No option lowers the L5 acceptance criteria.

---

## 4. Change control in this reconciliation

- No source code changed. No merge, close, deploy, branch deletion or ruleset change was performed.
- PR #81 remains HOLD. PR #77 remains OPEN/HOLD.
- Review status: **owner review is requested.** Verdicts from agent sessions or same-model-family councils are recorded as analysis only and are not counted as owner approval or independent review.

---

## 5. Limits

- Read-only GitHub REST and local git. No runner logs beyond those listed above were re-downloaded.
- The EC07 acceptance text is not present in the repository. Its source is the G1 acceptance package (V2.2) in the project library, which is not accessible from this sandbox. The EC07 work package is therefore planned from repository code and the PR #83 description only; see the plan in the session report.
- Snapshot statements about workstream status are carried forward unless a specific FACT above changes the evidence.
