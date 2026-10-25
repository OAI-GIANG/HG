"""Explicit provider construction for HG reasoning.

The factory supports a loopback-only OpenAI-compatible local endpoint and an explicit
DeepSeek adapter. Provider selection is supplied by trusted runtime composition. This
module does not read environment variables, discover credentials, start services, or
make network calls during construction. DeepSeek credentials must come from an explicit
runtime-owned callback; its live requests must pass through the router's guarded provider.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain.planning import JSONReasoningProvider, LocalOpenAICompatibleProvider, PlanningError
from brain.deepseek_provider import DeepSeekJSONProvider

_LOCAL_PROVIDER_TYPE = "openai_compatible_local"
_DEEPSEEK_PROVIDER_TYPE = "deepseek"
_ALLOWED_FIELDS = {
    "provider_type", "endpoint", "model", "api_key", "credential_provider",
    "timeout_seconds", "max_response_bytes", "max_output_tokens", "max_retries",
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
    provider_type = config.get("provider_type")
    endpoint = config.get("endpoint")
    model = config.get("model")
    if not isinstance(endpoint, str) or not isinstance(model, str):
        raise PlanningError("provider endpoint and model must be explicit strings")
    if provider_type == _LOCAL_PROVIDER_TYPE:
        if "credential_provider" in config or "max_output_tokens" in config or "max_retries" in config:
            raise PlanningError("DeepSeek-only fields cannot be supplied to the local provider")
        kwargs: dict[str, Any] = {"endpoint": endpoint, "model": model}
        for field in ("api_key", "timeout_seconds", "max_response_bytes"):
            if field in config:
                kwargs[field] = config[field]
        try:
            return LocalOpenAICompatibleProvider(**kwargs)
        except TypeError as exc:
            raise PlanningError("local provider configuration is invalid") from exc
    if provider_type == _DEEPSEEK_PROVIDER_TYPE:
        if "api_key" in config:
            raise PlanningError("DeepSeek credentials must come from an explicit runtime credential provider")
        if "credential_provider" not in config:
            raise PlanningError("DeepSeek credential provider is required")
        kwargs = {"endpoint": endpoint, "model": model,
                  "credential_provider": config["credential_provider"]}
        for field in ("timeout_seconds", "max_response_bytes", "max_output_tokens", "max_retries"):
            if field in config:
                kwargs[field] = config[field]
        try:
            return DeepSeekJSONProvider(**kwargs)
        except TypeError as exc:
            raise PlanningError("DeepSeek provider configuration is invalid") from exc
    raise PlanningError("unsupported reasoning provider type")
