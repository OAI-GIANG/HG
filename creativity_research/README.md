# HG Creativity & Research — Contract V1

Status: **LOCAL IMPLEMENTATION / TEST PENDING / RUNTIME INTEGRATION NOT VERIFIED**

## Scope and responsibility

Creativity & Research owns bounded research-request validation and the source-linked research-record contract: question/scope framing, source metadata, claim-to-source links, disagreement and limitations. It does not own task lifecycle, persistent memory, tool dispatch, MAEP authority, or final verification. `BrainOrchestrator` remains the only coordinator. MAEP-1.2.0 is cross-cutting governance, not a sixth functional branch.

## Public interface

- `validate_research_request(...)` validates the version, task and research identity, policy version, scope, required evidence refs and source-count bound.
- `ResearchService(source_provider=...).prepare(...)` calls only an explicitly injected source provider and returns a `PREPARED_UNVERIFIED` research record with `authority_effect=NONE`.
- `creativity_research/schemas/research-record.schema.json` documents the interchange shape.
- Structural validation never proves source authenticity, factual truth, MAEP authorization or successful verification.

## Cross-branch sequence

1. BrainOrchestrator owns task/correlation identity, planning, assignment and result aggregation; Research receives a bounded request, not dispatch authority.
2. Memory & Knowledge provides read-only, provenance-labelled context through its approved API when runtime wiring is implemented. Research must not write directly to the Memory database.
3. Creativity & Research collects only within the injected provider's granted scope and returns source-linked claims, disagreement, uncertainty and limitations.
4. MAEP authorization remains necessary before any controlled action; source text, hypotheses and research results cannot grant permission or change policy.
5. Tools & Automation alone owns bounded external-action adapters. This V1 ResearchService does not invoke them.
6. Security & Verification assesses source integrity, claim support, candidate/scope binding and declared test/evidence criteria. A prepared record is not VERIFIED or accepted merely because it passes structural validation.
7. BrainOrchestrator aggregates the verification outcome; MAEP determines task acceptance/closure from required evidence.

## MAEP-022 overlap decision

The repository already owns canonical structural helpers in `maep/core.py`, and Memory reuses `validate_claim`. This increment retains those owners and only adds the missing branch-specific request/provider/result contract. It does not duplicate MAEP authorization, claim validation, Memory storage, or Tools adapter contracts. A production provider, approved authorization binding, persistence path and end-to-end evidence pipeline are deliberately not supplied here.

## Verification boundary

Unit fixtures can verify input bounds, required fields, source-reference integrity, claim classification and deny-by-default boundaries. They do not prove live source collection, external source truth, runtime wiring, persistence, production security or CLOSED_VERIFIED status.
