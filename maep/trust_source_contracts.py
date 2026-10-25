"""Contracts for externally approved HG trust-source providers.

These interfaces describe required production dependencies; they do not implement,
bootstrap, or infer trust. A caller-supplied boolean or record field is not a source
of authority. Concrete implementations must be provided by an owner-approved runtime
boundary before production use.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from maep.native_authority import AuthorityError


@runtime_checkable
class ApprovedPolicySourceVerifier(Protocol):
    def verify_policy_source(self, record: dict[str, Any], *, root: Any,
                             policy: dict[str, Any]) -> bool: ...


@runtime_checkable
class AuthenticatedSessionResolver(Protocol):
    def resolve_authenticated_session(self, authenticated_context: Any) -> dict[str, Any] | None: ...


@runtime_checkable
class ApprovedMemoryRecordVerifier(Protocol):
    def verify_approved_memory_record(self, record: dict[str, Any], *, record_type: str,
                                      root: Any, policy: dict[str, Any]) -> bool: ...


@runtime_checkable
class CanonicalTaskIdSource(Protocol):
    def list_canonical_task_ids(self) -> list[str] | tuple[str, ...]: ...


def require_trust_source_contract(provider: Any, method: str, *, source_name: str) -> Any:
    """Require an explicitly injected implementation; never manufacture a fallback."""
    if provider is None or not callable(getattr(provider, method, None)):
        raise AuthorityError(f"approved trust source unavailable: {source_name}.{method}")
    return provider


def require_verified_source_result(result: Any, *, source_name: str) -> None:
    """Accept only literal True from the source verifier; truthy values are insufficient."""
    if result is not True:
        raise AuthorityError(f"approved trust source did not verify: {source_name}")
