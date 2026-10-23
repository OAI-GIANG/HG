# MAEP — HG Operating Governance

Policy version: MAEP-1.1.0 (supersedes MAEP-1.0.0; see `spec/MAEP_OWNER_DELEGATION_V1.md`). Status: implemented and locally tested foundation; runtime integration remains deferred.

MAEP is a cross-cutting governance layer for task intake, authority, state transitions, evidence, acceptance, recovery and closure. It is not a sixth HG domain. BrainOrchestrator remains the sole task coordinator.

- `spec/`: constitution, execution protocol, authority, evidence/acceptance, evolution, threat model, state transitions, traceability, risks and ADRs.
- `schemas/`: six JSON Schema Draft 2020-12 contract files.
- `core.py`: fail-closed governance primitives implemented with Python standard library.
- `policy.py`: `PolicyEvaluator`, which takes grants and condition facts from sources fixed at construction instead of from the request. It is not a trust root.
- `ledger.py`: single-writer append-only JSONL event/evidence ledger (not tamper-proof against privileged filesystem edits).
- `tests/`: standard-library conformance tests.
- `spec/MAEP_CONFORMANCE_TEST_CATALOGUE_V1.md`: rule-to-test catalogue.
- `spec/ACCEPTANCE_CHECKLIST_V1.md`: implementation and integration acceptance status.
- `spec/SOURCE_REFERENCES_V1.md`: official references and limitations.

Run from repository root:
```sh
python -m unittest discover -s maep/tests -v
```

Important limits:
- `core.py` is the business-policy layer, not a JSON Schema validator.
- The six schemas were checked with JSON Schema Draft 2020-12 validator `jsonschema==4.17.3` installed temporarily for development; that validator is not a runtime dependency.
- Runtime integration with BrainOrchestrator is not yet demonstrated by end-to-end tests.
- This package has not undergone independent review or certification.

References:
- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12
- NIST SP 800-218 SSDF: https://csrc.nist.gov/pubs/sp/800/218/final
- OWASP Secure Product Design: https://cheatsheetseries.owasp.org/cheatsheets/Secure_Product_Design_Cheat_Sheet.html
- RFC 8785: https://www.rfc-editor.org/rfc/rfc8785

References inform design; they do not certify this implementation.
