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
