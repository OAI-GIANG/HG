# MAEP — HG Operating Governance

Current policy version: MAEP-1.2.0 (`spec/MAEP_CONSTITUTION_V1_2.md`), superseding MAEP-1.1.0 for current and future HG work. MAEP-022 now defines a mandatory Capability Overlap & Superiority Gate; MAEP-031 requires evidence-driven continuous evolution. Foundation code includes a fail-closed capability-decision validator, but runtime-wide authorization integration remains unverified.

System-wide policy: signature functionality/workflows and independent-review workflows remain prohibited under MAEP-029/030. Their normative rule text is carried forward unchanged. Internal inspection, critique, tests and evidence-based verification remain allowed; they must not be labelled independent review.

MAEP is a cross-cutting governance layer for task intake, authority, state transitions, evidence, acceptance, recovery and closure. It is not a sixth HG domain. BrainOrchestrator remains the sole task coordinator.

- `spec/`: constitution, execution protocol, authority, evidence/acceptance, evolution, threat model, state transitions, traceability, risks and ADRs.
- `schemas/`: six JSON Schema Draft 2020-12 contract files.
- `core.py`: fail-closed governance primitives implemented with Python standard library.
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
- No independent-review workflow is permitted under current policy. This statement does not certify runtime-wide enforcement.

References:
- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12
- NIST SP 800-218 SSDF: https://csrc.nist.gov/pubs/sp/800/218/final
- OWASP Secure Product Design: https://cheatsheetseries.owasp.org/cheatsheets/Secure_Product_Design_Cheat_Sheet.html
- RFC 8785: https://www.rfc-editor.org/rfc/rfc8785

References inform design; they do not certify this implementation.

## Anti-forgetting / task continuity

maep/spec/MAEP_ANTI_FORGETTING_CONTINUITY_PROTOCOL_V1.md defines the proposed MAEP-AFCP-1.0.0 design for durable task continuity, checkpoint validation, stale-state detection, and mandatory live-state reconciliation before resume. It is a DESIGN PROPOSAL only: no runtime implementation or cross-session/restart behavior is claimed. MAEP-029 and MAEP-030 remain unchanged.


## Universal MAEP binding

`spec/MAEP_UNIVERSAL_BINDING_CONTRACT_V1.md` defines the owner-directed operating contract for applying MAEP to every HG task and every STT-assisted task in this operating context. It specifies lightweight preflight for simple conversational requests, the full task envelope for substantive/executable work, fail-closed execution invariants, evidence/reporting rules, and the technical proof required before claiming universal runtime enforcement. This contract is not evidence that all runtime entry points are already integrated; runtime-wide enforcement remains unverified until the listed end-to-end checks pass.
