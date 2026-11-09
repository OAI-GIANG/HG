# OWNER DECISION OD-IR-20261109 — No mandatory independent review in HG

| Field | Value |
|---|---|
| ID / version | OD-IR-20261109, v1 |
| Decided | 2026-11-09 23:15 +07 (Asia/Ho_Chi_Minh) |
| Authority | The owner, GitHub account `OAI-GIANG` ("Chủ Nhân"), trust root of HG |
| Source | Owner directive "HG — GLOBAL INDEPENDENT REVIEW REQUIREMENT ELIMINATION — COMPLETE GOVERNANCE REMEDIATION — ALL TASKS / ALL GATES", given in the owner's own claude.ai session (`https://claude.ai/code/session_01FGekwBZyxFHVSCyQkC7E7x`) |
| Recorded by | STT (Claude) under the standing delegation. The decision is the owner's; recording it is not agent self-approval (MAEP-017) |
| MAEP policy version | Unchanged: MAEP-1.1.0. No rule MAEP-001..028 required an independent review (see §4), so no MAEP rule changes |
| Supersedes | Every earlier instruction, prompt, checklist row, PR text or schedule rule that made an independent review a condition (listed in §4 and §5) |

## 1. Decision

```
INDEPENDENT_REVIEW_REQUIRED = false
```

This holds for every HG task, gate and lifecycle stage, without exception by priority, task type, workstream, code, documents, environment or phase.

No HG task needs an independent reviewer to proceed, be accepted, close, merge, release or deploy. Nothing below is a condition:

- a second person assessing the task;
- a reviewer on a GitHub account other than the author's, or from another organisation or party;
- an independent AI or agent (Gemini or any other model) confirming the result;
- independent adversarial, human or technical review; independent approval; independent verification and validation used as an approval condition;
- two people or two accounts confirming the same task;
- an outside reviewer issuing ACCEPT before work continues;
- any equivalent independent confirmation under another name.

The absence of an independent reviewer is not a defect, not a blocker, not a reason for HOLD, BLOCK, REJECT or NO-GO, and not a reason to delay execution, acceptance, merge, release or deploy. This requirement must not be recreated under another name; reversing it needs a new owner decision.

## 2. How decisions are made now

1. The owner, or whoever the owner has authorised, decides a task's outcome.
2. The executing agent may check its own work, run the tests, compare against requirements and assemble the evidence.
3. Other people or AIs may be invited to advise, challenge or assess.
4. Such extra assessments are advisory only. A real defect they find is still a defect: it fails the technical gate it belongs to (tests, security, integrity), not a review gate.
5. Nothing is held, blocked, rejected or refused closure only because there is no independent reviewer.
6. Execution, acceptance, merge, release and deploy are not delayed for want of an independent confirmation.
7. The conclusion of the person with authority under owner-approved governance is final.

## 3. What stays (deliberately not removed)

| Control | Why it stays |
|---|---|
| Unit, integration, regression, security and fault-injection tests; mutation checks; CI status checks `unittest (3.13)` / `unittest (3.14)` required by ruleset `main-maep`; `rt06-anchor` | Technical gates, not reviewer gates |
| `main` changes only through a merged pull request with green CI (ruleset `main-maep`: pull request with **0** required approvals, no deletion, no force push) | Change record and CI gate; it never required a reviewer |
| Static, syntax and shell checks (`sh -n`, `dash -n`, `git diff --check`, byte-compile), deterministic release build, hash/checksum verification, evidence integrity | Technical integrity |
| Authentication and authorization (PolicyEvaluator, RT-06 trust anchor, gateway permits), secrets protection | Security boundary |
| Recovery points, rollback, checkpoints, target hashes, ChangeBudget, audit ledgers | Recoverability |
| Termux on-device gates (R4) and authenticated READY / smoke after deploy | Technical acceptance on the target |
| **MAEP-021** "internal critique is not described as independent review" and `maep.core.validate_review_label` | A labeling (honesty) rule: self-review must not be *called* independent. It never required an independent review and blocks nothing |
| **MAEP-017** agents cannot relax policy to approve their own candidate; policy changes need owner authorization (MAEP-028) | Owner authority. Owner approval is not independent review |
| Technical independence: independent read-back of written files, independent-process verifier (`hg/verification/independent.py`), independently written held-out evaluation sets, adapters checking scope independently, an independent false-accept oracle | Test and measurement design, not a reviewer |
| Platform controls outside HG (the Claude Code session safety control that has refused agent merges "without review"; GitHub itself) | Not HG governance; HG cannot and does not remove or bypass them. The owner can merge directly |

## 4. Inventory — sources found and what was done

Search: every tracked file on `main` `2521edc` and on the open PR branches (#87, #88, #77, #64, #55, #11) and `stt/s03-cross-store-recovery-20261106`, for independent/external/second/separate review, reviewer or approval, reviewer identity, other-than-`OAI-GIANG`, two-person/four-eyes, formal review, merge gate, `review độc lập` and related wording; plus GitHub configuration, PR records, the hourly schedule and the phone's status document. Class: **MANDATE** made a review a condition and was remediated; **LABEL** is MAEP-021 honesty and stays; **TECH** is technical independence and stays; **RECORD** is dated history kept verbatim.

| Source | Class | Action |
|---|---|---|
| `maep/spec/ACCEPTANCE_CHECKLIST_V1.md` AC-14 "Independent review" (acceptance criterion, NOT_PERFORMED-BY-DIRECTIVE) | MANDATE | Now NOT_APPLICABLE (OD-IR-20261109) |
| `maep/spec/STATUS_RECONCILIATION_20261028.md` row "AC-14 … A different party must perform it" | MANDATE | Row annotated as superseded; the old reason is kept in past tense |
| `docs/V1_SCOPE.md` §4.2 V2_DEFERRED "review độc lập AC-14" (scheduled as later work) | MANDATE | Removed from the deferred list with a dated note |
| `docs/governance/HG_MASTER_COMPLETION_LEDGER_V1.md` §next actions "P0 — PR #77: … formal independent review" (2026-11-06 snapshot) | RECORD with a MANDATE | Snapshot unchanged; superseded by ledger reconciliation 2026-11-09 C |
| `CLAUDE.md` | — | Decision added so agent sessions do not re-impose it |
| `maep/core.py` `validate_review_label`, MAEP-021 in constitution, traceability matrices, ADR-010, validation records ("no independent review is claimed"), `hg/brain/orchestrator.py` / `hg/__main__.py` "internal check, not independent review" | LABEL | Kept |
| `maep/core.py` `validate_policy_change(self_approval=…)`, MAEP-017 | Owner authority | Kept |
| Independent read-back, independent-process verifier, independent eval sets, independent holdout, false-accept oracle, adapter scope checks | TECH | Kept |
| `deploy/termux/switch_service.sh` "state copy contains a symlink; manual review required" | TECH (fail-closed integrity refusal) | Kept |
| `maep/spec/RT06_VALIDATION_RECORD_V1.md` O-2 (separate agent identity so the trust root differs from agents, T-1) | Security proposal about authority, not review | Kept |
| `docs/evidence/**` | RECORD | Unchanged |
| Runtime code (ActionGateway, AcceptanceGate, TaskStore, state table, `hg serve`), workflows, hooks | — | No independent-review enforcement exists; confirmed by `hg/tests/test_no_mandatory_independent_review_runtime.py` |

## 5. Outside the repository

| Source | Before | After |
|---|---|---|
| GitHub ruleset `main-maep` (id 25706034), the only rule source on `main` (`GET /rules/branches/main`) | pull request rule: 0 approvals, no code-owner review, no last-push approval, no required reviewers; `require_extra_approval_for_unattributed_changes: true` (one extra approval for Copilot PRs not attributed to a person; inert at 0 approvals) | **Unchanged** (read back 2026-11-09, `updated_at` 2026-10-23T14:49:47+07:00). No rule requires an approval: GitHub documents that the unattributed-Copilot option has no effect when 0 approvals are required. The agent's attempt to turn it off (a `PUT` changing only that flag) was refused by the session's platform safety control ("CI Bypass") and was not retried; turning it off is an owner action in ruleset `main-maep`'s pull-request rule |
| Classic branch protection on `main` | None (HTTP 404 "Branch not protected") | None |
| CODEOWNERS | None in the tree | None |
| Organisation rules | Not applicable: the repository is owned by a user account | — |
| Environment protection / deployment approvals | Not readable here (the session proxy refuses `GET /environments`). No workflow job uses `environment:`; deploys run from `deploy/termux/` on the phone, not from GitHub | No GitHub environment gates any HG step |
| PR #87, PR #88, PR #77 records | Held for an independent formal review / "reviewer other than `OAI-GIANG`" | Hold superseded by this decision, recorded in ledger reconciliation C and in a governance-update comment on each PR (2026-11-09), with the remaining technical blockers kept. Clearing PR #87's Draft flag was refused by the session's platform safety control (owner: "Ready for review") |
| Hourly scheduled task "HG phiên làm việc tự chủ" (`trig_01Ec7zQi4e5TGp7t2arV8rbv`) | Prompt V1.1 §1, §3, §8, §10 and V1.0 (council ACCEPT before merge, "not an independent review") keep PR #87 Draft / WAITING_INDEPENDENT_REVIEW and require an independent exact-head review | **Not changed**: the prompt update (V1.2 header plus six line edits, everything else verbatim) was refused by the session's platform safety control. The proposed text was handed to the owner. Until it is applied, its own precedence rule (the owner's latest directive ranks above the schedule) and this record on `main` govern |
| Phone status document `~/hg-v1-evidence/hg-status.md` | Listed an independent review of PR #77 as an owner item | Item amended; owner item 5 added (sha256 before `001d5fdc…`, after `16f768cc…`) |

Before/after evidence: `docs/evidence/HG-IR-20261109/` (public-safe) and `~/hg-v1-evidence/20261109-ir-no-mandatory-review/` on the phone (status document before/after, manifest, SHA256SUMS).

## 6. Tests

- `maep/tests/test_no_mandatory_independent_review.py`: the decision record sets the rule; no governing document imposes an independent review (dated records and this file excluded); AC-14 is NOT_APPLICABLE; `CLAUDE.md` states the decision; MAEP-021 and MAEP-017 still hold. Failed on `main` `2521edc` (3 failures, 1 error) before this change.
- `hg/tests/test_no_mandatory_independent_review_runtime.py`: through the real runtime, a task with no reviewer of any kind, one identity and no external approval closes CLOSED_VERIFIED; a failing verifier, a missing verifier and a missing authorization are still refused.

## 7. Rollback

Revert the pull request that added this file. Ruleset: not changed by this work; its before-state is `docs/evidence/HG-IR-20261109/ruleset_25706034_before.json`. Schedule prompt: unchanged, nothing to restore. A rollback that re-introduces an independent review is itself a new owner decision.
