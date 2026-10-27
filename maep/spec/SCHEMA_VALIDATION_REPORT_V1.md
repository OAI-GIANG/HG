# MAEP Schema Validation Report V1

Date: 2026-10-22
Repository: OAI-GIANG/HG
Branch: stt/maep-v1-20261022
Candidate: uncommitted worktree; baseline HEAD before changes: d71b771987bbdfba41edb68d27ef0ba722bafabc
Scope: six MAEP JSON Schema contracts only.

## Method
- JSON Schema Draft 2020-12 validator: python package `jsonschema==4.17.3`.
- Validator was installed into a user cache directory for this validation only; it is not a project/runtime dependency.
- Ran `Draft202012Validator.check_schema(schema)` on all six schemas.
- For each schema, validated one positive sample and one negative sample missing a required field.
- Separately ran Python standard-library JSON parsing for every schema file.

## Results
- Meta-schema check: PASS, 6/6.
- Positive instance validation: PASS, 6/6.
- Negative required-field validation: PASS, 6/6 rejected as expected.
- JSON parse: PASS, 6/6.
- Python unit tests: PASS — 68 tests in the final pre-commit run; tests remain independent of the optional JSON Schema validator.

## Addendum 2026-10-28 — the check is now reproducible for the subset the contracts use

The run above was a one-off with a temporarily installed validator, so CI could not repeat it and
the contracts had parsing tests only. `maep/schema_check.py` now enforces the exact keyword subset
the six contracts use — `type` (including unions), `enum`, `const`, `required`, `properties`,
`additionalProperties` (false or a schema), `items`, `minItems`, `minLength`, `format: date-time`,
`$defs` and local `$ref` — and raises `UnsupportedSchemaKeyword` for anything else, so a contract
cannot gain a constraint that nothing checks.

`maep/schemas/fixtures.json` holds 42 hand-written instances (positive and negative per contract);
`maep/tests/test_schema_fixtures.py` asserts each verdict and, for negatives, the violation that
must be reported. Contract and fixture bytes are pinned in `maep/schemas/SHA256SUMS`, and the test
fails if either changes without the manifest being updated.

This does **not** replace the Draft 2020-12 meta-schema check: full meta-schema validation remains
NOT_RUN in CI. Validation now covers the keywords used, not a standards-complete implementation
(ADR-006).

## Limitations
- This validates schema syntax and representative required-field behavior; it does not prove every possible instance or all semantic business invariants.
- The custom runtime `maep/core.py` remains the business-policy layer; JSON Schema does not validate authorization authority, state transition history, evidence provenance or actual external resource existence.
- No BrainOrchestrator runtime exists in the canonical repository baseline, so end-to-end integration remains a separate future phase.
- No independent review or signature was performed or claimed.
