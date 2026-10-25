"""The single production factory for runtime.service (ADR-012).

Select it explicitly with ``HG_RUNTIME_FACTORY=runtime.production_config:create_service``
and point ``HG_RUNTIME_CONFIG`` at an owner-controlled JSON file. The factory validates the
configuration and the provisioned trust root, then refuses to compose the runtime until every
required production binding has an owner-approved implementation registered in this module.

Approved implementations are registered in code (reviewed by pull request), not injected
through configuration, so a configuration file cannot select a permissive verifier. Nothing
here creates a trust root, policy, principal, session, evidence, Memory database or ledger,
and nothing uses test fixtures.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

from maep.local_authority_store import LocalRootStore
from maep.native_authority import AuthorityError
from memory import AuthorityEvidenceReader
from runtime.errors import RuntimeStartupError

CONFIG_ENV = "HG_RUNTIME_CONFIG"
CONFIG_SCHEMA = "hg-runtime-factory-config-v1"
PATH_KEYS = ("checkout", "authority_dir", "policy_path", "evidence_dir",
             "memory_db", "idempotency_db", "receipts_dir")
CONFIG_KEYS = frozenset(("schema", "host", "port") + PATH_KEYS)

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
    ("live-state-provider", "no production implementation"),
    ("acceptance-provider", "no production implementation"),
)
APPROVED_BINDINGS: dict[str, Any] = {
    # Read-only authority record source (PR #18): breaks the authorize() -> Memory
    # -> authorize() cycle. Constructed per Memory database at composition time.
    "maep022-record-reader": AuthorityEvidenceReader,
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
    if not Path(config["checkout"]).is_dir():
        raise RuntimeStartupError("runtime configuration checkout is not a directory")
    return config


def missing_bindings() -> list[str]:
    return [f"{name} ({reason})" for name, reason in REQUIRED_BINDINGS
            if APPROVED_BINDINGS.get(name) is None]


def create_service():
    """HG_RUNTIME_FACTORY target. Fails closed until all production bindings exist."""
    config = load_config(os.environ.get(CONFIG_ENV))
    try:
        root = LocalRootStore(config["authority_dir"]).load_active()
    except AuthorityError as exc:
        raise RuntimeStartupError("provisioned trust root is invalid") from exc
    if root is None:
        raise RuntimeStartupError("no active trust root is provisioned (owner bootstrap required)")
    missing = missing_bindings()
    if missing:
        raise RuntimeStartupError("production bindings not provisioned: " + "; ".join(missing))
    raise RuntimeStartupError("production composition is not implemented for the registered bindings")
