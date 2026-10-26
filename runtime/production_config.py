"""The single production factory for runtime.service (ADR-012).

Select it explicitly with ``HG_RUNTIME_FACTORY=runtime.production_config:create_service``
and point ``HG_RUNTIME_CONFIG`` at an owner-controlled JSON file. The factory validates the
configuration and the provisioned trust root, then refuses to compose the runtime until every
required production binding has an owner-approved implementation registered in this module.

Approved implementations are registered in code (reviewed by pull request), not injected
through configuration, so a configuration file cannot select a permissive verifier. Nothing
here creates a trust root, policy, principal, session, evidence or Memory database, and
nothing uses test fixtures. Once every binding is registered, compose_service() wires the
production graph; until then create_service() blocks and names what is missing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_runtime_providers import (GitCandidateProvider, LocalLiveStateProvider, LocalPolicyProvider,
                                          LocalPrincipalProvider, LocalReceiptSink, SQLiteIdempotencyLedger)
from maep.memory_evidence_providers import (CanonicalMemoryTaskSelectors, MemoryLedgerProvenanceVerifier,
                                            MemoryMAEPRecordResolver)
from maep.native_authority import AuthorityError, TrustRootRecord
from maep.trust_source_contracts import require_trust_source_contract
from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider
from memory import AuthorityEvidenceReader
from runtime.errors import RuntimeStartupError
from runtime.session_auth import TokenSessionSource

CONFIG_ENV = "HG_RUNTIME_CONFIG"
CONFIG_SCHEMA = "hg-runtime-factory-config-v2"
PATH_KEYS = ("checkout", "authority_dir", "policy_path", "policy_approval_path", "evidence_dir",
             "memory_db", "idempotency_db", "receipts_dir", "session_record", "session_revocations")
CONFIG_KEYS = frozenset(("schema", "host", "port", "file_write_roots") + PATH_KEYS)

# Every binding build_runtime and HGHTTPServer need that has no production implementation
# yet. Each entry names the blocker it waits for. Register an owner-approved implementation
# in APPROVED_BINDINGS (by pull request) to clear an entry; never register a test double.
REQUIRED_BINDINGS = (
    ("approved-policy-source-verifier", "D2: owner rule for policy approval evidence"),
    ("authenticated-session-resolver", "D3: owner-defined session source"),
    ("request-authenticator", "D3: owner-defined HTTP authentication"),
    ("authenticated-context-provider", "D3: runtime-bound authenticated context"),
    ("approved-memory-record-verifier", "D4: owner rule for approved Memory records"),
    ("maep022-record-reader", "D4: non-recursive authority read path"),
    ("tool-adapter-registry", "no production ToolAdapter implementation"),
    ("acceptance-provider", "no production implementation"),
)
def _build_record_reader(config: dict[str, Any]) -> AuthorityEvidenceReader:
    return AuthorityEvidenceReader(config["memory_db"])


def _build_session_source(config: dict[str, Any]) -> TokenSessionSource:
    # One shared source instance backs all three D3 seams so the authenticated context
    # and the principal resolver cannot diverge across separately constructed readers.
    return TokenSessionSource(session_path=config["session_record"],
                              revocation_path=config["session_revocations"])


def _build_session_bindings(config: dict[str, Any]) -> dict[str, Any]:
    source = _build_session_source(config)
    return {
        "authenticated-session-resolver": source,
        "request-authenticator": source.authenticate_request,
        "authenticated-context-provider": source.authenticated_context,
    }


# name -> builder(config) returning the binding object. Builders run only after the
# configuration and the trust root have been validated.
def _build_policy_approval_verifier(config: dict[str, Any]):
    from runtime.owner_approvals import LocalPolicyApprovalVerifier
    return LocalPolicyApprovalVerifier(config["policy_approval_path"])


def _build_memory_record_verifier(config: dict[str, Any]):
    from runtime.owner_approvals import AuthorizedWriteRecordVerifier
    return AuthorizedWriteRecordVerifier(
        evidence_sink=LocalEvidenceSink(config["evidence_dir"]), memory_store_path=config["memory_db"])


def _build_file_adapters(config: dict[str, Any]) -> dict[str, Any]:
    from tools_automation.file_write_adapter import RootedFileWriteAdapter
    roots = config["file_write_roots"]
    if not isinstance(roots, dict) or not roots:
        raise RuntimeStartupError("file_write_roots must name at least one owner-provisioned root")
    adapters = {}
    for name, root in roots.items():
        if not isinstance(name, str) or not name or not isinstance(root, str) or not Path(root).is_absolute():
            raise RuntimeStartupError("file_write_roots entries must be named absolute paths")
        if name in adapters:
            raise RuntimeStartupError("duplicate file write adapter name")
        adapters[name] = RootedFileWriteAdapter(root)
    return adapters


def _build_acceptance_provider(config: dict[str, Any]):
    from runtime.acceptance import build_acceptance_provider
    return build_acceptance_provider(config=config,
        policy_verifier=_build_policy_approval_verifier(config),
        memory_verifier=_build_memory_record_verifier(config),
        file_adapters=_build_file_adapters(config))


# These are production builders, never test doubles. Owner-controlled config provides
# only paths; authorization semantics remain code-owned and fail closed.
APPROVED_BINDINGS: dict[str, Any] = {
    "maep022-record-reader": _build_record_reader,
    "approved-policy-source-verifier": _build_policy_approval_verifier,
    "approved-memory-record-verifier": _build_memory_record_verifier,
    "tool-adapter-registry": _build_file_adapters,
    "acceptance-provider": _build_acceptance_provider,
    "authenticated-session-resolver": lambda config: _build_session_source(config),
    "request-authenticator": lambda config: _build_session_source(config).authenticate_request,
    "authenticated-context-provider": lambda config: _build_session_source(config).authenticated_context,
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-finite JSON constant is not permitted")


def load_config(path: str | None) -> dict[str, Any]:
    """Load the owner-controlled factory configuration strictly; any anomaly blocks."""
    if not isinstance(path, str) or not path.strip():
        raise RuntimeStartupError(f"{CONFIG_ENV} is required; no runtime configuration is implicit")
    config_path = Path(path)
    if not config_path.is_absolute():
        raise RuntimeStartupError(f"{CONFIG_ENV} must be an absolute path")
    try:
        info = config_path.lstat()
    except OSError as exc:
        raise RuntimeStartupError("runtime configuration file is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeStartupError("runtime configuration must be a regular non-symlink file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise RuntimeStartupError("runtime configuration is not owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeStartupError("runtime configuration permissions must exclude group/other access")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"),
                            object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeStartupError("runtime configuration is not strict JSON") from exc
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise RuntimeStartupError("runtime configuration keys do not match the schema")
    if config["schema"] != CONFIG_SCHEMA:
        raise RuntimeStartupError("runtime configuration schema is not supported")
    if config["host"] != "127.0.0.1":
        raise RuntimeStartupError("runtime must bind to IPv4 loopback 127.0.0.1 only")
    port = config["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise RuntimeStartupError("runtime port must be an integer in 1024-65535")
    for key in PATH_KEYS:
        value = config[key]
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise RuntimeStartupError(f"runtime configuration {key} must be an absolute path")
    roots = config["file_write_roots"]
    if not isinstance(roots, dict) or not roots or any(
            not isinstance(name, str) or not name or not isinstance(value, str) or not Path(value).is_absolute()
            for name, value in roots.items()):
        raise RuntimeStartupError("runtime configuration file_write_roots must be a non-empty name-to-absolute-path map")
    if not Path(config["checkout"]).is_dir():
        raise RuntimeStartupError("runtime configuration checkout is not a directory")
    return config


def missing_bindings() -> list[str]:
    return [f"{name} ({reason})" for name, reason in REQUIRED_BINDINGS
            if APPROVED_BINDINGS.get(name) is None]


def _require_callable(value: Any, name: str) -> Any:
    if not callable(value):
        raise RuntimeStartupError(f"production binding {name} is not callable")
    return value


def _require_contract(value: Any, method: str, name: str) -> Any:
    try:
        return require_trust_source_contract(value, method, source_name=name)
    except AuthorityError as exc:
        raise RuntimeStartupError(f"production binding {name} contract is invalid") from exc


def _verified_root(config: dict[str, Any]) -> tuple[LocalRootStore, TrustRootRecord]:
    root_store = LocalRootStore(config["authority_dir"])
    try:
        root = root_store.load_active()
    except AuthorityError as exc:
        raise RuntimeStartupError("provisioned trust root is invalid") from exc
    if root is None:
        raise RuntimeStartupError("no active trust root is provisioned (owner bootstrap required)")
    if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
        raise RuntimeStartupError("provisioned trust root is invalid")
    return root_store, root


def compose_service(config: dict[str, Any], bindings: dict[str, Any]):
    """Wire HG's production graph from a validated configuration and binding objects.

    ``bindings`` maps every REQUIRED_BINDINGS name to an object (not a builder). This
    function performs no trust decision of its own: identity, policy provenance and
    Memory record approval come only from the supplied bindings, and build_runtime()
    re-checks the trust root and active policy binding before anything is constructed.
    It creates no trust root, policy, session, evidence or Memory database. The only
    file it may create is the idempotency ledger, after every check has passed.
    """
    from runtime.composition import build_runtime
    from runtime.http_server import HGHTTPServer

    missing = [name for name, _reason in REQUIRED_BINDINGS if bindings.get(name) is None]
    if missing:
        raise RuntimeStartupError("production bindings not provisioned: " + "; ".join(missing))
    unknown = sorted(set(bindings) - {name for name, _reason in REQUIRED_BINDINGS})
    if unknown:
        raise RuntimeStartupError("unknown production bindings: " + ", ".join(unknown))
    policy_source = _require_contract(bindings["approved-policy-source-verifier"],
                                      "verify_policy_source", "approved-policy-source-verifier")
    session_resolver = _require_contract(bindings["authenticated-session-resolver"],
                                         "resolve_authenticated_session", "authenticated-session-resolver")
    memory_verifier = _require_contract(bindings["approved-memory-record-verifier"],
                                        "verify_approved_memory_record", "approved-memory-record-verifier")
    authenticate_request = _require_callable(bindings["request-authenticator"], "request-authenticator")
    context_provider = _require_callable(bindings["authenticated-context-provider"],
                                         "authenticated-context-provider")
    acceptance_provider = _require_callable(bindings["acceptance-provider"], "acceptance-provider")
    reader = bindings["maep022-record-reader"]
    if not isinstance(reader, AuthorityEvidenceReader):
        raise RuntimeStartupError("production binding maep022-record-reader must be memory.AuthorityEvidenceReader")
    if reader.path != Path(config["memory_db"]).expanduser().absolute():
        raise RuntimeStartupError("maep022-record-reader is bound to another Memory database")
    adapters = bindings["tool-adapter-registry"]
    if (not isinstance(adapters, dict) or not adapters
            or any(not isinstance(name, str) or not callable(getattr(adapter, "execute", None))
                   for name, adapter in adapters.items())):
        raise RuntimeStartupError("production binding tool-adapter-registry is invalid")
    if not Path(config["memory_db"]).is_file():
        raise RuntimeStartupError("Memory database is not provisioned (owner initialization required)")

    root_store, root = _verified_root(config)
    checkout = str(Path(config["checkout"]).expanduser().absolute())
    candidate_provider = GitCandidateProvider(checkout)
    principal_provider = LocalPrincipalProvider(session_resolver)
    policy_provider = LocalPolicyProvider(config["policy_path"], policy_source)
    # Verify the active policy before anything is written (build_runtime re-checks it).
    try:
        policy_provider.load_active(root)
    except AuthorityError as exc:
        raise RuntimeStartupError("production composition blocked: active policy is not verified") from exc
    # Live state is observed from the already-composed candidate/policy/root providers;
    # it is not an owner-decision seam.
    live_state_provider = LocalLiveStateProvider(candidate_provider=candidate_provider, checkout=checkout,
                                                 policy_provider=policy_provider, root_store=root_store)
    selectors = CanonicalMemoryTaskSelectors(memory_store=reader, canonical_task_id_source=reader)
    record_resolver = MemoryMAEPRecordResolver(memory_store=reader, selectors=selectors)
    provenance = MemoryLedgerProvenanceVerifier(memory_verifier)
    applicability = TrustedApplicabilityProvider(root_store=root_store, policy_provider=policy_provider,
                                                 resolver=record_resolver, verifier=provenance,
                                                 memory_store_path=str(reader.path))
    gate = TrustedGateEvidenceProvider(root_store=root_store, policy_provider=policy_provider,
                                       resolver=record_resolver, verifier=provenance)

    def candidate_target(_request=None):
        return checkout

    def memory_principal():
        principal = principal_provider.resolve(context_provider())
        if not isinstance(principal, dict) or not principal.get("principal_id"):
            raise AuthorityError("Memory principal unavailable: runtime session is not active")
        return principal["principal_id"]

    def memory_candidate_ref(_task_id):
        candidate = candidate_provider.inspect(checkout)
        if not isinstance(candidate, dict) or candidate.get("verified") is not True:
            raise AuthorityError("Memory candidate unavailable: checkout is not a verified HG candidate")
        return candidate["candidate_ref"]

    def readiness_provider():
        # Readiness is evidence-based and re-evaluated per request. A dirty or
        # unverified checkout is not reported as a verified release.
        try:
            active_root = root_store.load_active()
            if not isinstance(active_root, TrustRootRecord) or not active_root.verify_integrity():
                return None
            active_policy = policy_provider.load_active(active_root)
            if (not isinstance(active_policy, dict) or active_policy.get("status") != "ACTIVE"
                    or active_policy.get("provenance_verified") is not True
                    or active_policy.get("root_generation") != active_root.generation):
                return None
            current_candidate = candidate_provider.inspect(checkout)
            if (not isinstance(current_candidate, dict) or current_candidate.get("verified") is not True
                    or current_candidate.get("repository") != "OAI-GIANG/HG"
                    or current_candidate.get("working_tree_dirty") is not False):
                return None
            return {"release": "VERIFIED", "trust": "LOADED"}
        except Exception:
            return None

    try:
        runtime = build_runtime(
            root_store=root_store, principal_provider=principal_provider,
            candidate_provider=candidate_provider, policy_provider=policy_provider,
            applicability_provider=applicability, gate_provider=gate,
            evidence_sink=LocalEvidenceSink(config["evidence_dir"]),
            authenticated_context_provider=context_provider,
            candidate_target_provider=candidate_target,
            memory_principal_provider=memory_principal,
            memory_candidate_ref_provider=memory_candidate_ref,
            memory_db_path=config["memory_db"], live_state_provider=live_state_provider,
            acceptance_provider=acceptance_provider, adapter_registry=dict(adapters),
            idempotency_ledger=SQLiteIdempotencyLedger(config["idempotency_db"]),
            receipt_sink=LocalReceiptSink(config["receipts_dir"]),
            readiness_provider=readiness_provider,
        )
    except AuthorityError as exc:
        raise RuntimeStartupError("production composition blocked: " + str(exc)) from exc
    return HGHTTPServer(runtime=runtime, authenticate_request=authenticate_request,
                        host=config["host"], port=config["port"])


def create_service():
    """HG_RUNTIME_FACTORY target. Fails closed until all production bindings exist."""
    config = load_config(os.environ.get(CONFIG_ENV))
    _verified_root(config)
    missing = missing_bindings()
    if missing:
        raise RuntimeStartupError("production bindings not provisioned: " + "; ".join(missing))
    bindings = {}
    for name, _reason in REQUIRED_BINDINGS:
        try:
            bindings[name] = APPROVED_BINDINGS[name](config)
        except RuntimeStartupError:
            raise
        except Exception as exc:
            raise RuntimeStartupError(f"production binding {name} could not be constructed "
                                      f"({type(exc).__name__})") from exc
    return compose_service(config, bindings)
