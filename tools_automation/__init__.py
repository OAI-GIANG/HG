"""Tools & Automation boundary contracts for HG.

This package defines typed, bounded adapters. It performs no ambient I/O and grants
no authority: callers must pass a request that BrainOrchestrator has authorized.
Adapters must independently enforce the supplied action/resource scope and return a
structured outcome. Any ambiguous post-invocation condition is UNKNOWN, not FAILURE.
"""
from .contracts import (
    AdapterContext,
    AdapterError,
    AdapterOutcome,
    AdapterRequest,
    ToolAdapter,
    validate_adapter_request,
    validate_adapter_result,
)

__all__ = [
    "AdapterContext",
    "AdapterError",
    "AdapterOutcome",
    "AdapterRequest",
    "ToolAdapter",
    "validate_adapter_request",
    "validate_adapter_result",
]
