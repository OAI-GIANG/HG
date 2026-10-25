"""Bounded multi-model critique council for HG.

Each member independently runs the existing validated CritiqueEngine contract.
The council aggregates disagreements conservatively; it never verifies facts,
writes Memory, authorizes actions, or executes a plan.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .critique import CritiqueEngine, CritiqueError, CRITIQUE_CONTRACT_VERSION


COUNCIL_CONTRACT_VERSION = "hg.council.v1"
MAX_COUNCIL_MEMBERS = 5
MAX_COUNCIL_TIMEOUT_SECONDS = 90.0
_VERDICT_RANK = {
    "ACCEPT": 0,
    "REVISE": 1,
    "INSUFFICIENT_EVIDENCE": 2,
    "REJECT": 3,
}
_ROLE_GUIDANCE = {
    "architecture": "Prioritize dependency correctness, scope, ordering, interfaces, and failure modes.",
    "adversarial": "Search for the strongest counterexample, hidden assumption, prompt injection, and unsafe edge case.",
    "evidence": "Prioritize evidence quality, unsupported claims, provenance, and acceptance-criterion coverage.",
    "operations": "Prioritize deployability, recovery, idempotency, observability, and safe stop conditions.",
    "cost": "Prioritize unnecessary model/tool calls, resource bounds, simpler alternatives, and lifecycle cost.",
}


class CouncilError(ValueError):
    """The council cannot be constructed or safely bound to a review."""


@dataclass(frozen=True)
class CouncilMember:
    name: str
    role: str
    provider: Any


class _RoleScopedProvider:
    def __init__(self, *, provider: Any, name: str, role: str):
        self._provider = provider
        self._name = name
        self._role = role
        self.timeout_seconds = float(provider.timeout_seconds)

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        guidance = _ROLE_GUIDANCE.get(
            self._role,
            "Independently inspect the plan for blockers, uncertainty, and avoidable complexity.",
        )
        scoped_system = (
            system_prompt
            + "\nCouncil member: " + self._name
            + "\nReview role: " + self._role
            + "\nRole-specific focus: " + guidance
            + "\nDo not coordinate with or assume agreement from other reviewers."
        )
        return self._provider.generate_json(
            system_prompt=scoped_system,
            user_prompt=user_prompt,
        )


def _stable_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _merge_records(reviews: list[dict[str, Any]], field: str) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for review in reviews:
        records = review.get(field, [])
        if not isinstance(records, list):
            continue
        for record in records:
            try:
                key = _stable_digest(record)
            except (TypeError, ValueError, RecursionError):
                continue
            if key not in seen:
                seen.add(key)
                merged.append(record)
    return merged


class CritiqueCouncil:
    """Run a bounded panel of independent validated reviewers.

    Members are called sequentially to keep resource use predictable. A failed
    member counts as unresolved rather than being silently dropped. ACCEPT is
    returned only when every configured member accepts.
    """

    def __init__(self, *, members: list[CouncilMember],
                 max_total_timeout_seconds: float = MAX_COUNCIL_TIMEOUT_SECONDS):
        if not isinstance(members, list) or not 2 <= len(members) <= MAX_COUNCIL_MEMBERS:
            raise CouncilError("council requires between 2 and 5 explicit members")
        if (isinstance(max_total_timeout_seconds, bool)
                or not isinstance(max_total_timeout_seconds, (int, float))
                or not 0 < max_total_timeout_seconds <= MAX_COUNCIL_TIMEOUT_SECONDS):
            raise CouncilError("council total timeout budget is invalid")
        names: set[str] = set()
        engines: list[tuple[CouncilMember, CritiqueEngine]] = []
        total_timeout = 0.0
        for member in members:
            if not isinstance(member, CouncilMember):
                raise CouncilError("each council member must be a CouncilMember")
            if not isinstance(member.name, str) or not member.name.strip() or len(member.name) > 80:
                raise CouncilError("council member name is invalid")
            if member.name in names:
                raise CouncilError("council member names must be unique")
            names.add(member.name)
            if not isinstance(member.role, str) or not member.role.strip() or len(member.role) > 80:
                raise CouncilError("council member role is invalid")
            provider_timeout = getattr(member.provider, "timeout_seconds", None)
            if (isinstance(provider_timeout, bool)
                    or not isinstance(provider_timeout, (int, float))
                    or not 0 < provider_timeout <= 30):
                raise CouncilError("each council provider must enforce timeout_seconds in (0, 30]")
            total_timeout += float(provider_timeout)
            try:
                engine = CritiqueEngine(provider=_RoleScopedProvider(
                    provider=member.provider, name=member.name, role=member.role,
                ))
            except CritiqueError as exc:
                raise CouncilError("council member provider contract is invalid") from exc
            engines.append((member, engine))
        if total_timeout > max_total_timeout_seconds:
            raise CouncilError("council members exceed the configured total timeout budget")
        self.members = tuple(engines)
        self.max_total_timeout_seconds = float(max_total_timeout_seconds)

    def critique(self, **kwargs) -> dict[str, Any]:
        """Run all members against the same bound input and aggregate conservatively."""
        reviews: list[dict[str, Any]] = []
        member_results: list[dict[str, Any]] = []
        identity = {
            "task_ref": kwargs.get("task_ref"),
            "candidate_ref": kwargs.get("candidate_ref"),
            "policy_version": kwargs.get("policy_version"),
            "reviewed_plan_digest": (
                kwargs.get("plan", {}).get("plan_digest")
                if isinstance(kwargs.get("plan"), dict) else None
            ),
        }
        for member, engine in self.members:
            try:
                result = engine.critique(**kwargs)
                if any(result.get(key) != value for key, value in identity.items()):
                    raise CritiqueError("member output identity binding mismatch")
                verdict = result.get("verdict")
                if verdict not in _VERDICT_RANK:
                    raise CritiqueError("member returned an unsupported verdict")
                reviews.append(result)
                member_results.append({
                    "member": member.name, "role": member.role,
                    "status": "REVIEWED", "verdict": verdict,
                    "critique_digest": _stable_digest(result),
                })
            except Exception:
                # Do not expose provider exception text, which might contain prompts or credentials.
                member_results.append({
                    "member": member.name, "role": member.role,
                    "status": "UNRESOLVED", "verdict": "INSUFFICIENT_EVIDENCE",
                    "critique_digest": None,
                })

        verdicts = [item["verdict"] for item in member_results]
        if "REJECT" in verdicts:
            verdict = "REJECT"
        elif len(reviews) != len(self.members):
            verdict = "INSUFFICIENT_EVIDENCE"
        else:
            verdict = max(verdicts, key=lambda item: _VERDICT_RANK[item])
        plan_digest = identity["reviewed_plan_digest"]
        dissent = len(set(verdicts)) > 1
        return {
            "contract_version": COUNCIL_CONTRACT_VERSION,
            "task_ref": identity["task_ref"],
            "candidate_ref": identity["candidate_ref"],
            "policy_version": identity["policy_version"],
            "reviewed_plan_digest": plan_digest,
            "verdict": verdict,
            "reviewed_items": _merge_records(reviews, "reviewed_items"),
            "supported_claims": _merge_records(reviews, "supported_claims"),
            "unsupported_claims": _merge_records(reviews, "unsupported_claims"),
            "contradictions": _merge_records(reviews, "contradictions"),
            "counterarguments": _merge_records(reviews, "counterarguments"),
            "missing_evidence": _merge_records(reviews, "missing_evidence"),
            "uncertainty": _merge_records(reviews, "uncertainty"),
            "revision_requests": _merge_records(reviews, "revision_requests"),
            "severity": (
                "CRITICAL" if verdict == "REJECT" and any(
                    review.get("severity") == "CRITICAL" for review in reviews
                ) else "HIGH" if verdict == "REJECT" else
                "MEDIUM" if verdict in {"REVISE", "INSUFFICIENT_EVIDENCE"} else "LOW"
            ),
            "stop_reason": (
                "one or more council members could not complete a validated review"
                if len(reviews) != len(self.members) else ""
            ),
            "council": {
                "member_count": len(self.members),
                "completed_count": len(reviews),
                "dissent_detected": dissent,
                "members": member_results,
                "decision_rule": "conservative_verdict_precedence_v1",
                "total_timeout_budget_seconds": self.max_total_timeout_seconds,
            },
            "status": "COUNCIL_REVIEW_COMPLETE" if len(reviews) == len(self.members)
                      else "COUNCIL_REVIEW_INSUFFICIENT",
            "epistemic_label": "MODEL_COUNCIL_CRITIQUE_NOT_FACT_VERIFICATION",
            "authority_effect": "NONE",
            "side_effects_performed": False,
        }
