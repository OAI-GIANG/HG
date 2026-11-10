# Model-call path audit — checkpoint V3-CP01

**Scope:** `OAI-GIANG/HG`; comparison of the live release and GO-LIVE candidate.
**Disposition:** G4 BLOCKED; production is unchanged.

## Live production release

The active release (`030a88d5…`, source commit `4eaac811…`) creates a plain `OllamaProvider` in `hg/assistant/config.py`. Its `attest_listener()` verifies the runit-supervised process is alive, named `ollama`, and owned by the current UID; the returned state is `VERIFIED_PROCESS`. This is not proof of listener socket ownership or non-sharing, and it is not a pre/post attestation bracket around every model request.

The live `ChatService` checks the supervised process and model tag before calling the local router. That is not a post-call check. Its own documentation says ChatService is outside BrainOrchestrator, TaskStore and ActionGateway enforcement. Do not treat production READY or MAEP trust LOADED as G4 evidence.

## Candidate improvements

The candidate adds `_AttestedOllamaProvider` around local Ollama. Its intended behavior:
- pre-call listener attestation;
- call buffering for streamed deltas;
- post-call re-verification before returning the response;
- refuse on failed attestation;
- require listener state for the local assistant/chat path.

The saved `LIVE_MODEL_CALL_GATE.json` records `REFUSED_BEFORE_MODEL_REQUEST` because the required listener proof was unavailable. That is a correct fail-closed result, not successful model-call qualification.

## Remaining G4 gaps

1. Current tests prove the wrapper with fake providers/attestors; they do not prove all live model call entrypoints.
2. The selected Anthropic provider path is not wrapped in the same full gateway contract.
3. Generic `ModelRouter` injection points used by planner/research abstractions can operate with arbitrary providers unless the runtime composition root is proved to be the only production constructor.
4. Request digest exists in the HG provider/router layer, but the complete required request ID + nonce + backend correlation + response digest verification is not established across providers.
5. No independently verified runtime/listener identity is available on this Android app sandbox.
6. The Android Broker candidate expects response headers `x-hg-request-id`, `x-hg-request-nonce`, and `x-hg-request-sha256`; no corresponding Ollama server-side echo/verification path is present in the candidate module.
7. The current production path is still the older `VERIFIED_PROCESS` implementation.

## Required implementation target

Use a single mandatory ModelCallGateway for all provider invocations:
- explicit MAEP/owner authorization before transport;
- a pinned runtime/provider identity;
- pre-call attestation bound to request ID, nonce and digest;
- backend correlation of that envelope;
- buffer streaming until the complete post-call check succeeds;
- response schema and SHA-256 integrity validation;
- fail-closed audit event with no secret prompt material;
- tests proving no bypass through CLI, HTTP chat, assistant, tools, agents, planning, streaming or background work.

Do not call this complete until negative bypass tests run on the actual supported runtime and Android target.
