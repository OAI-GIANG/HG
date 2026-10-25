"""Fail-closed resolver for explicitly referenced, task-scoped Memory claims.

Memory's VERIFIED flag is a stored assertion, not independent proof. A caller must
inject source-evidence and applicability verifiers; neither is replaced by metadata.
No cross-task lookup, direct database access, or TTL inference is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ExperienceResolutionBlocked(RuntimeError):
    """The claim cannot be safely reused under current bindings."""


@dataclass(frozen=True)
class ResolvedExperience:
    task_id: str
    claim_id: str
    record_id: str
    version: int
    candidate_ref: str
    policy_version: str
    evidence_refs: tuple[str, ...]
    statement: str
    freshness: str = "CURRENT"
    authority_effect: str = "NONE"


class ExperienceResolver:
    """Resolve a claim only when Memory bindings and independent checks agree."""

    def __init__(
        self,
        *,
        memory_api: Any,
        evidence_verifier: Callable[..., bool],
        applicability_verifier: Callable[..., bool],
    ):
        if not callable(getattr(memory_api, "get_knowledge", None)):
            raise ValueError("Memory API must provide authorized get_knowledge")
        if not callable(getattr(memory_api, "get_evidence", None)):
            raise ValueError("Memory API must provide authorized get_evidence")
        if not callable(evidence_verifier) or not callable(applicability_verifier):
            raise ValueError("independent evidence and applicability verifiers are required")
        self._memory = memory_api
        self._verify_evidence = evidence_verifier
        self._verify_applicability = applicability_verifier

    def resolve(
        self, *, task_id: str, claim_id: str, candidate_ref: str, policy_version: str,
        applicability_context: dict[str, Any],
    ) -> ResolvedExperience:
        for name, value in (("task_id", task_id), ("claim_id", claim_id),
                            ("candidate_ref", candidate_ref), ("policy_version", policy_version)):
            if not isinstance(value, str) or not value.strip():
                raise ExperienceResolutionBlocked(name + " is required")
        if not isinstance(applicability_context, dict):
            raise ExperienceResolutionBlocked("applicability context must be an observed object")
        if applicability_context.get("conflict_detected") is not False:
            raise ExperienceResolutionBlocked("conflict state is unknown or conflicting")

        try:
            record = self._memory.get_knowledge(task_id, claim_id, include_stale=True)
        except Exception as exc:
            raise ExperienceResolutionBlocked("authorized knowledge read failed") from exc
        if not isinstance(record, dict):
            raise ExperienceResolutionBlocked("claim not found")
        if record.get("record_status") != "CURRENT":
            raise ExperienceResolutionBlocked("claim is stale")
        if record.get("verification_status") != "VERIFIED":
            raise ExperienceResolutionBlocked("claim is not verified")
        if (record.get("task_id") != task_id or record.get("candidate_ref") != candidate_ref
                or record.get("policy_version") != policy_version):
            raise ExperienceResolutionBlocked("claim task/candidate/policy binding mismatch")
        claim = record.get("claim")
        if not isinstance(claim, dict) or claim.get("claim_id") != claim_id:
            raise ExperienceResolutionBlocked("claim identity is malformed")
        verification = record.get("verification")
        if not isinstance(verification, dict):
            raise ExperienceResolutionBlocked("independent verification binding is missing")
        verified_refs = verification.get("evidence_refs")
        claim_refs = claim.get("evidence_refs")
        if (not isinstance(verified_refs, list) or not verified_refs
                or not isinstance(claim_refs, list) or not claim_refs
                or set(verified_refs) != set(claim_refs)
                or any(not isinstance(ref, str) or not ref.strip() for ref in verified_refs)):
            raise ExperienceResolutionBlocked("claim and verification evidence references disagree")

        for evidence_id in verified_refs:
            try:
                binding = self._memory.get_evidence(task_id, evidence_id)
            except Exception as exc:
                raise ExperienceResolutionBlocked("authorized evidence read failed") from exc
            if not isinstance(binding, dict):
                raise ExperienceResolutionBlocked("referenced evidence is missing or revoked")
            evidence = binding.get("evidence")
            if (binding.get("task_id") != task_id or binding.get("candidate_ref") != candidate_ref
                    or binding.get("policy_version") != policy_version
                    or not isinstance(evidence, dict)
                    or evidence.get("evidence_id") != evidence_id
                    or evidence.get("candidate_ref") != candidate_ref):
                raise ExperienceResolutionBlocked("evidence task/candidate/policy binding mismatch")
            try:
                independently_verified = self._verify_evidence(
                    task_id=task_id, candidate_ref=candidate_ref, policy_version=policy_version,
                    evidence_id=evidence_id, evidence=evidence, provenance=record.get("provenance"),
                )
            except Exception as exc:
                raise ExperienceResolutionBlocked("independent evidence verifier failed") from exc
            if independently_verified is not True:
                raise ExperienceResolutionBlocked("evidence was not independently verified")

        try:
            applicable = self._verify_applicability(
                claim=claim, source_task_id=task_id, target_task_id=task_id,
                candidate_ref=candidate_ref, policy_version=policy_version,
                context=applicability_context,
            )
        except Exception as exc:
            raise ExperienceResolutionBlocked("applicability verifier failed") from exc
        if applicable is not True:
            raise ExperienceResolutionBlocked("claim applicability is not established")

        version = record.get("version")
        record_id = record.get("record_id")
        statement = claim.get("statement")
        if (isinstance(version, bool) or not isinstance(version, int) or version < 1
                or not isinstance(record_id, str) or not record_id.strip()
                or not isinstance(statement, str) or not statement.strip()):
            raise ExperienceResolutionBlocked("claim record is malformed")
        return ResolvedExperience(
            task_id=task_id, claim_id=claim_id, record_id=record_id, version=version,
            candidate_ref=candidate_ref, policy_version=policy_version,
            evidence_refs=tuple(verified_refs), statement=statement,
        )
