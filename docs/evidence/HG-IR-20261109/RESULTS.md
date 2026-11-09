# HG-IR-20261109 — test and scan results (OD-IR-20261109)

Tree tested: `git write-tree` 97ac87c687874b63b86dd83a530cf50424db7195 (the staged change set of branch `stt/ir-no-mandatory-independent-review-20261109` on base `main` 2521edc22d7f0de52d574fbee6c25cd13d1e0aa0). Python 3.13.18, Linux, fresh `git archive` copy.

| Command | User | Exit | Result |
|---|---|---|---|
| `python3 -m unittest maep.tests.test_no_mandatory_independent_review` on 2521edc + new tests only (before the change) | root | 1 | Ran 8, failures=3, errors=1 — failing first for the expected reasons (`failfirst_policy_on_2521edc.log`) |
| `python3 -m unittest hg.tests.test_no_mandatory_independent_review_runtime` on 2521edc (before the change) | root | 0 | Ran 5, OK — the runtime path never required a reviewer (characterization, `characterization_runtime_on_2521edc.log`) |
| `python3 -m unittest discover -s maep/tests` | ubuntu (uid 1000) | 0 | Ran 362 tests in 1.786s OK (skipped=1)  |
| `python3 -m unittest discover -s hg/tests -t .` | ubuntu (uid 1000) | 0 | Ran 512 tests in 72.421s OK  |
| `python3 -m unittest discover -s .claude/hooks -p "test_*.py"` | ubuntu (uid 1000) | 0 | Ran 32 tests in 0.252s OK  |
| `python3 -m hg selfcheck` | ubuntu (uid 1000) | 0 | PASS |
| `python3 -m hg bench` | ubuntu (uid 1000) | 0 | PASS |
| `python3 -m unittest discover -s hg/tests -t .` | root | 1 | Ran 512, failures=1, skipped=1: `test_release…test_sealed_import_without_dont_write_bytecode_leaves_tree_unchanged` writes `__pycache__` because root ignores the read-only mode the test relies on. Same failure on unmodified `main` 2521edc as root; passes as uid 1000 (row above). Environment, not this change |

Mutation check of `maep/tests/test_no_mandatory_independent_review.py` (each mutant applied alone to the tested tree, then restored): 4/4 killed — M1 a mandate sentence appended to `CLAUDE.md`; M2 AC-14 reverted to NOT_PERFORMED-BY-DIRECTIVE; M3 negation handling disabled; M4 a reviewer-identity mandate appended to `docs/V1_SCOPE.md`.

Governing-text scan (`mandates()` over 56+ governing files; dated ledger records and the decision record excluded): before the change 2 offenders on `main` (`maep/spec/STATUS_RECONCILIATION_20261028.md:33` "A different party must perform it", `docs/V1_SCOPE.md:77` AC-14 independent review in V2_DEFERRED), plus the excluded snapshot line `HG_MASTER_COMPLETION_LEDGER_V1.md:171`; after the change 0. The same two offenders exist on the open PR branches #87, #88 and #77 (inherited from `main`); none of those branches adds another.

`git diff --cached --check`: clean.

## Continuation — 2026-11-09, Termux and external state

Continuation worktree: ~/HG-IR-REMEDIATION-20261109 on stt/ir-no-mandatory-independent-review-20261109; original ~/HG worktree and its pre-existing changes were preserved.

### Policy-scan hardening

The initial scanner could miss a positive gate after a nearby negated clause. It now evaluates clauses separately and includes contradictory same-line / same-paragraph regression cases:
- No independent review is required, but do not merge until an independent reviewer approves.
- No independent approval is required; however, release waits for a different reviewer.
- Independent review is not required. Do not deploy without a separate security reviewer.

It also recursively enumerates root-level text/config files and nested maep, docs, deploy, .claude and .github sources. Current scan: 67 governing files, 0 mandate findings. The dated immutable records and evidence archives are preserved as historical records, not treated as active governing instructions.

### Termux verification

Android Termux / Python 3.14.8, uid u0_a460:
| Command | Result |
|---|---|
| python3 -m unittest maep.tests.test_no_mandatory_independent_review -v | 8 tests PASS after clause-splitting regression cases were added |
| python3 -m unittest discover -s maep/tests | 362 tests PASS, 3 skipped |
| python3 -m unittest discover -s hg/tests -t . | 512 tests PASS |
| python3 -m unittest discover -s .claude/hooks -p "test_*.py" | 32 tests PASS |
| python3 -m hg selfcheck | PASS |
| python3 -m hg bench | PASS, 10/10 cases |
| python3 -m py_compile maep/tests/test_no_mandatory_independent_review.py | PASS |
| git diff --check | PASS |

Non-fatal ResourceWarning messages were emitted by existing test code for an unclosed file/socket. They did not fail the suites and are not suppressed in this record.

### GitHub current state

- PR #87: OPEN / READY (draft=false), head 5ac666df81216cfc3b6421eb3917e81e25718e2e; prior exact-head CI and Termux R4 evidence retained. No merge/deploy.
- PR #88: OPEN / DRAFT; its description no longer cites missing independent review; broader technical acceptance remains unresolved. No merge/deploy.
- PR #77: OPEN; independent-review requirements removed from description; technical HOLD remains for L5/L3/actual listener evidence. No merge/deploy.
- PR #89: OPEN / READY, head dbf6f49f35dc7c5d40a100b92b2445904e90672b at this continuation's start. CI on that exact SHA: MAEP run 42660030154 SUCCESS; RT06 run 42660029865 SUCCESS.

### Ruleset main-maep current read-back

Ruleset id 25706034 remains active. Review-related settings are now:
- required_approving_review_count = 0
- require_extra_approval_for_unattributed_changes = false
- require_code_owner_review = false
- require_last_push_approval = false
- required_review_thread_resolution = false
- required_reviewers = []

Required status checks remain exactly unittest (3.13) and unittest (3.14). Deletion and non-fast-forward protections remain enabled; allowed merge methods unchanged. The actual API read-back is stored at ruleset_25706034_after_readback.json.

### Prompt automation state

ChatGPT's Master Planned Work Completion and HG G0 Mission Follow-up task prompts were updated to supersede mandatory independent review; both tasks remain disabled as before. This is separate from Claude's hourly task trig_01Ec7zQi4e5TGp7t2arV8rbv. Its prompt was not updated because its schedule control plane is not exposed in this connected session; the V1.2 amendment remains a proposed diff. The owner's latest decision governs, but the separate scheduled prompt itself remains an outstanding administrative update.
