"""Version 1 contract for the Tools & Automation branch.

No adapter is authorized by mere registration. BrainOrchestrator remains the sole
coordinator and MAEP/NativePolicyEngine remains the source of authorization.
This module is standard-library-only and intentionally performs no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Protocol


class AdapterError(RuntimeError):
    """Adapter contract violation detected before an external effect."""


class AdapterOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AdapterRequest:
    """Minimal operation identity passed to a tool adapter.

    The request intentionally carries references and bounded scope, not ambient
    credentials, unrestricted filesystem roots, or arbitrary capability handles.
    """
    contract_version: str
    task_ref: str
    action: str
    resource: str
    scope: tuple[str, ...]
    idempotency_key: str
    deadline: str | None = None


@dataclass(frozen=True)
class AdapterContext:
    """Authorization result and execution correlation supplied by the coordinator."""
    authorization: Any
    correlation_id: str
    expected_action: str
    expected_resource: str
    expected_scope: tuple[str, ...]


class ToolAdapter(Protocol):
    """Implementations must enforce resource/action scope at the point of effect."""

    def execute(self, *, request: dict[str, Any], authorization: Any,
                idempotency_key: str) -> dict[str, Any]:
        """Execute one bounded operation and return a structured outcome."""
        ...


_REQUIRED_REQUEST_FIELDS = ("task_ref", "action", "resource", "scope")
_ALLOWED_OUTCOMES = {item.value for item in AdapterOutcome}
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")


def validate_adapter_request(request: Any, *, idempotency_key: Any) -> AdapterRequest:
    """Validate structural bounds only; this function does not grant authorization."""
    if not isinstance(request, dict):
        raise AdapterError("request must be an object")
    if any(key not in request for key in _REQUIRED_REQUEST_FIELDS):
        raise AdapterError("request missing task/action/resource/scope")
    for field in ("task_ref", "action", "resource"):
        value = request[field]
        if not isinstance(value, str) or not _REF_RE.fullmatch(value):
            raise AdapterError("invalid " + field)
    scope = request["scope"]
    if (not isinstance(scope, (list, tuple)) or not scope
            or any(not isinstance(item, str) or not _REF_RE.fullmatch(item) for item in scope)
            or len(set(scope)) != len(scope)):
        raise AdapterError("scope must be a non-empty list of unique bounded references")
    if not isinstance(idempotency_key, str) or not _REF_RE.fullmatch(idempotency_key):
        raise AdapterError("invalid idempotency key")
    deadline = request.get("deadline")
    if deadline is not None and (not isinstance(deadline, str) or len(deadline) > 64):
        raise AdapterError("invalid deadline representation")
    version = request.get("contract_version", "hg.tool-adapter.v1")
    if version != "hg.tool-adapter.v1":
        raise AdapterError("unsupported tool adapter contract version")
    return AdapterRequest(
        contract_version=version,
        task_ref=request["task_ref"],
        action=request["action"],
        resource=request["resource"],
        scope=tuple(scope),
        idempotency_key=idempotency_key,
        deadline=deadline,
    )


def validate_adapter_result(result: Any) -> dict[str, Any]:
    """Validate a result payload without converting ambiguity into success."""
    if not isinstance(result, dict):
        raise AdapterError("adapter result must be an object")
    outcome = result.get("outcome")
    if outcome not in _ALLOWED_OUTCOMES:
        raise AdapterError("adapter result outcome must be SUCCESS, FAILURE, or UNKNOWN")
    # References in result are identifiers, never proof of their own integrity.
    for field in ("provider_ref", "evidence_ref"):
        value = result.get(field)
        if value is not None and (not isinstance(value, str) or not _REF_RE.fullmatch(value)):
            raise AdapterError("invalid " + field)
    if "idempotent" in result and not isinstance(result["idempotent"], bool):
        raise AdapterError("idempotent must be boolean when provided")
    return dict(result)
