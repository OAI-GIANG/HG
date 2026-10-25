"""Creativity & Research contracts for HG.

This branch prepares source-bounded research records; it does not fetch sources,
write Memory, call tools, dispatch work, or confer authorization. BrainOrchestrator
is the only cross-branch coordinator. MAEP remains the canonical governance owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from maep.core import MAEPError, POLICY_VERSION, validate_research_record


CONTRACT_VERSION = "hg.creativity-research.v1"


class ResearchContractError(ValueError):
    """A research request or result violates its versioned branch contract."""


@dataclass(frozen=True)
class ResearchRequest:
    contract_version: str
    task_ref: str
    research_id: str
    question: str
    scope: str
    source_limit: int
    required_evidence: tuple[str, ...]
    policy_version: str = POLICY_VERSION


class SourceProvider(Protocol):
    """Read-only, explicitly injected source collector; never an authority source."""

    def collect(self, *, question: str, scope: str, limit: int) -> list[dict[str, Any]]:
        """Return source records with provenance and limitations."""
        ...


class ResearchService:
    """Build a validated research record over an explicitly injected source provider."""

    def __init__(self, *, source_provider: SourceProvider):
        if source_provider is None or not callable(getattr(source_provider, "collect", None)):
            raise ResearchContractError("explicit read-only source provider is required")
        self._source_provider = source_provider

    def prepare(self, *, request: dict[str, Any], claims: list[dict[str, Any]],
                disagreements: list[dict[str, Any]] | None = None,
                limitations: list[str] | None = None) -> dict[str, Any]:
        parsed = validate_research_request(request)
        sources = self._source_provider.collect(
            question=parsed.question, scope=parsed.scope, limit=parsed.source_limit
        )
        record = {
            "contract_version": CONTRACT_VERSION,
            "research_id": parsed.research_id,
            "task_ref": parsed.task_ref,
            "question": parsed.question,
            "research_scope": parsed.scope,
            "policy_version": parsed.policy_version,
            "sources": sources,
            "claims": claims,
            "disagreements": disagreements if disagreements is not None else [],
            "limitations": limitations if limitations is not None else [],
            "status": "PREPARED_UNVERIFIED",
            "authority_effect": "NONE",
        }
        try:
            validate_research_record(record)
        except MAEPError as exc:
            raise ResearchContractError(str(exc)) from exc
        return record


def validate_research_request(value: Any) -> ResearchRequest:
    """Validate a bounded request shape; this is not MAEP authorization."""
    if not isinstance(value, dict):
        raise ResearchContractError("research request must be an object")
    required = {"contract_version", "task_ref", "research_id", "question", "scope",
                "source_limit", "required_evidence", "policy_version"}
    if not required.issubset(value):
        raise ResearchContractError("research request missing required fields")
    if value.get("contract_version") != CONTRACT_VERSION:
        raise ResearchContractError("unsupported research contract version")
    for field in ("task_ref", "research_id", "question", "scope", "policy_version"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ResearchContractError(field + " must be a non-empty string")
    if value["policy_version"] != POLICY_VERSION:
        raise ResearchContractError("research request policy version is stale")
    limit = value.get("source_limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ResearchContractError("source_limit must be an integer from 1 through 50")
    evidence = value.get("required_evidence")
    if not isinstance(evidence, list) or not evidence or any(
        not isinstance(ref, str) or not ref.strip() for ref in evidence
    ) or len(set(evidence)) != len(evidence):
        raise ResearchContractError("required_evidence must be a non-empty unique list of references")
    return ResearchRequest(
        contract_version=value["contract_version"], task_ref=value["task_ref"],
        research_id=value["research_id"], question=value["question"], scope=value["scope"],
        source_limit=limit, required_evidence=tuple(evidence), policy_version=value["policy_version"],
    )
