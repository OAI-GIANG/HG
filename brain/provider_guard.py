"""Fail-closed provider-call gate for router-enabled HG runtime paths.

The guard is an in-process enforcement layer, not a security boundary against arbitrary
code that separately retains a raw provider reference. Runtime-owned engines receive
this wrapper and can invoke it only inside a trusted orchestrator authorization scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4


class ProviderCallBlocked(RuntimeError):
    """Provider invocation was not authorized/reserved by the HG runtime."""


@dataclass(frozen=True)
class ProviderCallAuthorization:
    ledger: Any
    task_ref: str
    candidate_ref: str
    policy_version: str
    route: str
    category: str
    limit: int


_ACTIVE_AUTHORIZATION: ContextVar[ProviderCallAuthorization | None] = ContextVar(
    "hg_provider_call_authorization", default=None
)


@contextmanager
def authorize_provider_calls(*, ledger: Any, task_ref: str, candidate_ref: str,
                              policy_version: str, route: str, category: str,
                              limit: int) -> Iterator[None]:
    """Establish a synchronous, scoped authorization from canonical runtime state."""
    if (not callable(getattr(ledger, "reserve_bound", None))
            or not all(isinstance(value, str) and value.strip() for value in
                       (task_ref, candidate_ref, policy_version, route, category))
            or isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ProviderCallBlocked("trusted provider-call authorization is incomplete")
    authorization = ProviderCallAuthorization(
        ledger=ledger, task_ref=task_ref, candidate_ref=candidate_ref,
        policy_version=policy_version, route=route, category=category, limit=limit,
    )
    token = _ACTIVE_AUTHORIZATION.set(authorization)
    try:
        yield
    finally:
        _ACTIVE_AUTHORIZATION.reset(token)


class GuardedJSONProvider:
    """Reserve one identity-bound budget unit before forwarding each model call."""

    def __init__(self, provider: Any):
        if provider is None or not callable(getattr(provider, "generate_json", None)):
            raise TypeError("wrapped provider must implement generate_json")
        self._provider = provider
        retry_hook = getattr(provider, "set_retry_reservation_callback", None)
        if callable(retry_hook):
            retry_hook(self._reserve_retry_attempt)

    @property
    def timeout_seconds(self):
        return getattr(self._provider, "timeout_seconds", None)

    @staticmethod
    def _reserve(authorization: ProviderCallAuthorization) -> None:
        call_id = "hg-call:" + uuid4().hex
        try:
            reserved = authorization.ledger.reserve_bound(
                task_ref=authorization.task_ref,
                candidate_ref=authorization.candidate_ref,
                policy_version=authorization.policy_version,
                route=authorization.route,
                category=authorization.category,
                call_id=call_id,
                limit=authorization.limit,
            )
        except Exception as exc:
            raise ProviderCallBlocked("provider call blocked: identity-bound budget reservation failed") from exc
        if reserved is not True:
            raise ProviderCallBlocked("provider call blocked: identity-bound budget reservation denied")

    def _reserve_retry_attempt(self) -> None:
        authorization = _ACTIVE_AUTHORIZATION.get()
        if authorization is None:
            raise ProviderCallBlocked("provider retry blocked: no active HG router authorization")
        self._reserve(authorization)

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        authorization = _ACTIVE_AUTHORIZATION.get()
        if authorization is None:
            raise ProviderCallBlocked("provider call blocked: no active HG router authorization")
        self._reserve(authorization)
        return self._provider.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)


def guard_provider(provider: Any) -> GuardedJSONProvider:
    """Wrap a provider once, preserving the provider contract without fallback."""
    if isinstance(provider, GuardedJSONProvider):
        return provider
    return GuardedJSONProvider(provider)
