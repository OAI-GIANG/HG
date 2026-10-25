"""Explicit provider construction for HG reasoning.

The factory deliberately supports only a local OpenAI-compatible endpoint today.
Provider selection is supplied by the trusted runtime composition; this module does
not read environment variables, discover credentials, start services, or make remote
network calls. New provider adapters must implement JSONReasoningProvider and receive
explicit security/timeout limits before they can be added here.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain.planning import JSONReasoningProvider, LocalOpenAICompatibleProvider, PlanningError

_PROVIDER_TYPE = "openai_compatible_local"
_ALLOWED_FIELDS = {
    "provider_type", "endpoint", "model", "api_key", "timeout_seconds",
    "max_response_bytes",
}


def build_reasoning_provider(config: Mapping[str, Any]) -> JSONReasoningProvider:
    """Build a reasoning provider from explicit trusted configuration.

    The current adapter is compatible with local llama.cpp servers and other
    OpenAI-compatible servers only when bound to HTTP loopback. It does not imply
    that any server is running or that the selected model is available.
    """
    if not isinstance(config, Mapping):
        raise PlanningError("reasoning provider config must be a mapping")
    unknown = set(config) - _ALLOWED_FIELDS
    if unknown:
        raise PlanningError("unknown reasoning provider config fields: " + ", ".join(sorted(map(str, unknown))))
    if config.get("provider_type") != _PROVIDER_TYPE:
        raise PlanningError("unsupported reasoning provider type")
    endpoint = config.get("endpoint")
    model = config.get("model")
    if not isinstance(endpoint, str) or not isinstance(model, str):
        raise PlanningError("local provider endpoint and model must be explicit strings")
    kwargs: dict[str, Any] = {"endpoint": endpoint, "model": model}
    for field in ("api_key", "timeout_seconds", "max_response_bytes"):
        if field in config:
            kwargs[field] = config[field]
    try:
        return LocalOpenAICompatibleProvider(**kwargs)
    except TypeError as exc:
        raise PlanningError("local provider configuration is invalid") from exc
