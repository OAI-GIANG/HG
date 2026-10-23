"""Trusted policy evaluation boundary for MAEP authorization (MAEP-003, 004, 005, 019).

authorize_action() believes whatever its caller passes as trusted_policy_allow and
satisfied_conditions. PolicyEvaluator takes both out of the request path: grants come
from the store fixed at construction, condition facts from the injected provider. A
request only names a grant by authorization_id; it cannot carry authority.

Not a trust root: whoever constructs the evaluator decides which grants and which
condition provider are trusted, and the request principal is not authenticated here.
"""
import copy
from datetime import datetime, timezone
from .core import (
    MAEPError, POLICY_VERSION, REQUIRED_AUTH_FIELDS, _nonempty_string,
    _parse_aware_datetime, authorize_action
)

REQUEST_FIELDS = {"authorization_id", "principal", "action", "resource", "scope", "task_id", "policy_version"}
GRANT_DECISIONS = {"ALLOW", "DENY", "BLOCKED"}
GRANT_ACTIONS = {"READ", "WRITE", "COMMIT", "PUSH", "MERGE", "DEPLOY", "MIGRATE", "DELETE", "EXECUTE", "OTHER"}


class PolicyEvaluator:
    """Evaluate action requests against a fixed grant store; anything unverifiable is DENY."""

    def __init__(self, grants, condition_provider, *, policy_version=POLICY_VERSION, allow_non_expiring=False):
        if not callable(condition_provider):
            raise MAEPError("condition provider must be callable")
        if not _nonempty_string(policy_version):
            raise MAEPError("policy version must be non-empty")
        self._policy_version = policy_version
        self._condition_provider = condition_provider
        self._grants = {}
        for grant in grants:
            self._check_grant(grant, allow_non_expiring)
            if grant["authorization_id"] in self._grants:
                raise MAEPError("duplicate authorization_id in policy")
            # Copy so later changes to the caller's objects cannot widen a stored grant.
            self._grants[grant["authorization_id"]] = copy.deepcopy(grant)

    def _check_grant(self, grant, allow_non_expiring):
        if not isinstance(grant, dict):
            raise MAEPError("grant must be an object")
        missing = REQUIRED_AUTH_FIELDS - grant.keys()
        if missing:
            raise MAEPError("grant missing fields: " + ", ".join(sorted(missing)))
        for field in ("authorization_id", "principal", "resource", "task_id"):
            if not _nonempty_string(grant[field]):
                raise MAEPError(f"grant {field} must be a non-empty string")
        if grant["decision"] not in GRANT_DECISIONS:
            raise MAEPError("unknown grant decision")
        if grant["action"] not in GRANT_ACTIONS:
            raise MAEPError("unknown grant action")
        if grant["policy_version"] != self._policy_version:
            raise MAEPError("grant policy version does not match evaluator policy")
        for field in ("scope", "conditions"):
            if not isinstance(grant[field], list) or not all(_nonempty_string(v) for v in grant[field]):
                raise MAEPError(f"grant {field} must be a list of non-empty strings")
        if not grant["scope"]:
            raise MAEPError("grant scope must be non-empty")
        _parse_aware_datetime(grant["issued_at"], "grant issue time")
        if grant["expires_at"] is None:
            if allow_non_expiring is not True:
                raise MAEPError("non-expiring grant not permitted by evaluator configuration")
        else:
            _parse_aware_datetime(grant["expires_at"], "grant expiry")

    def evaluate(self, request, *, now=None):
        """Return an ALLOW or DENY decision record for one action request."""
        now = now or datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise MAEPError("evaluation time must be a timezone-aware datetime")
        authorization_id = request.get("authorization_id") if isinstance(request, dict) else None
        try:
            grant = self._resolve(request)
            unmet = [c for c in grant["conditions"] if not self._condition_holds(c, request)]
            if unmet:
                raise MAEPError("conditions not verified by provider: " + ", ".join(unmet))
            verified = dict(request, satisfied_conditions=list(grant["conditions"]))
            authorize_action(grant, verified, trusted_policy_allow=True, now=now)
        except MAEPError as exc:
            return self._decision("DENY", authorization_id, now, str(exc))
        return self._decision("ALLOW", authorization_id, now, "grant matched and all conditions verified")

    def _resolve(self, request):
        if not isinstance(request, dict):
            raise MAEPError("request must be an object")
        extra = request.keys() - REQUEST_FIELDS
        if extra:
            raise MAEPError("request carries fields outside the request contract: " + ", ".join(sorted(extra)))
        missing = REQUEST_FIELDS - request.keys()
        if missing:
            raise MAEPError("request missing fields: " + ", ".join(sorted(missing)))
        if request["policy_version"] != self._policy_version:
            raise MAEPError("request policy version does not match evaluator policy")
        if not _nonempty_string(request["authorization_id"]) or request["authorization_id"] not in self._grants:
            raise MAEPError("unknown authorization_id")
        grant = copy.deepcopy(self._grants[request["authorization_id"]])
        if grant["decision"] != "ALLOW":
            raise MAEPError("authorization record is not ALLOW")
        return grant

    def _condition_holds(self, condition, request):
        try:
            return self._condition_provider(condition, copy.deepcopy(request)) is True
        except Exception:
            # A fact source that cannot answer has not verified the condition.
            return False

    def _decision(self, decision, authorization_id, now, reason):
        return {
            "decision": decision,
            "authorization_id": authorization_id if _nonempty_string(authorization_id) else None,
            "policy_version": self._policy_version,
            "evaluated_at": now.isoformat(),
            "reason": reason,
        }
