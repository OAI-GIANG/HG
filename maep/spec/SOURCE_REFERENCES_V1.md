# MAEP Official Source References V1

## SRC-01 — JSON Schema Draft 2020-12
URL: https://json-schema.org/draft/2020-12/
Use: contract shape vocabulary, schema dialect and validation concepts.
Limit: a schema file declaring the dialect is not proof it conforms to that dialect. The local environment lacked a standards-complete validator, so full schema conformance remains NOT_RUN.

## SRC-02 — NIST SP 800-218 SSDF 1.1
URL: https://csrc.nist.gov/pubs/sp/800/218/final
Use: secure development lifecycle, vulnerability prevention and repeatable engineering practices.
Limit: SSDF is a framework of recommended practices, not a certification of HG or MAEP. NIST lists SP 800-218 Rev. 1 / SSDF 1.2 as a draft in its publications catalogue; this package uses the final 1.1 publication as a stable final reference and does not claim compliance.

## SRC-03 — OWASP Secure Product Design Cheat Sheet
URL: https://cheatsheetseries.owasp.org/cheatsheets/Secure_Product_Design_Cheat_Sheet.html
Use: secure defaults, least privilege, defense in depth, fail-secure behavior, threat modeling and testing.
Limit: OWASP guidance is design guidance, not a formal certification or proof that the implementation enforces these controls.

## SRC-04 — RFC 8785 JSON Canonicalization Scheme
URL: https://www.rfc-editor.org/rfc/rfc8785
Use: optional future reference if deterministic JSON serialization is needed for hashing.
Limit: canonical serialization does not prove identity, provenance or authorization. Not implemented in MAEP V1.

## Source handling rule
External sources are references, not canonical HG policy. A source may inform a proposed rule but cannot grant authority or silently override owner directives. Record exact URL, use, limitations and the decision informed by it.
