"""Per-task grants derived from the canonical owner manifest (RT-06 follow-up, MIID C-13).

In autonomous operation nobody hand-writes per-task grants. TaskGrantIssuer issues them
for a recorded plan, and only when the live manifest on `main` already permits the same
principal, action and resource for every step. Each issued grant binds one step's
authorization_id, principal, action, resource, scope, task and policy version
(MAEP-004), and expires at the earlier of `now + ttl` and the manifest grant's expiry
(MAEP_OWNER_DELEGATION_V1 Q-1). If any step is not permitted, nothing is issued.

The issued grants live in an IssuedGrantEvaluator, which accepts grants only from the
single issuer that claimed it. It is meant to be wrapped by AnchoredPolicyEvaluator, so
every later decision re-checks the manifest anyway (revocation still denies).
"""
import copy
from datetime import datetime, timedelta, timezone

from maep.authority.trust_anchor import TrustAnchorError, _parse_ts, action_name, authorize
from maep.core import MAEPError, POLICY_VERSION, _nonempty_string
from maep.policy import PolicyEvaluator


def _utc_now():
    return datetime.now(timezone.utc)


class IssuedGrantEvaluator:
    """A PolicyEvaluator whose grant store only the claimed issuer can extend."""

    def __init__(self, *, condition_provider=None, policy_version=POLICY_VERSION):
        self._condition_provider = condition_provider or (lambda _condition, _request: False)
        self._policy_version = policy_version
        self._grants = {}
        self._issuer_key = None
        self._inner = PolicyEvaluator([], self._condition_provider, policy_version=policy_version)

    def claim_issuer(self):
        if self._issuer_key is not None:
            raise MAEPError("grant issuer already claimed")
        self._issuer_key = object()
        return self._issuer_key

    def _add(self, key, grants):
        if key is None or key is not self._issuer_key:
            raise MAEPError("only the claimed issuer can add grants")
        updated = dict(self._grants)
        for grant in grants:
            existing = updated.get(grant["authorization_id"])
            if existing is not None and existing["task_id"] != grant["task_id"]:
                raise MAEPError("authorization_id already bound to another task")
            updated[grant["authorization_id"]] = copy.deepcopy(grant)
        # Validates every grant (shape, decision, action, version, expiry) before swapping in.
        self._inner = PolicyEvaluator(list(updated.values()), self._condition_provider,
                                      policy_version=self._policy_version)
        self._grants = updated

    def evaluate(self, request, *, now=None):
        return self._inner.evaluate(request, now=now)


class TaskGrantIssuer:
    def __init__(self, manifest, evaluator, *, principal, ttl_s=3600, clock=None):
        if not callable(getattr(manifest, "current", None)):
            raise MAEPError("manifest source must provide current()")
        if not isinstance(evaluator, IssuedGrantEvaluator):
            raise MAEPError("issuer requires an IssuedGrantEvaluator")
        if not _nonempty_string(principal):
            raise MAEPError("issuer principal must be non-empty")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, int) or not 60 <= ttl_s <= 86400:
            raise MAEPError("ttl_s must be an integer between 60 and 86400")
        self._manifest = manifest
        self._evaluator = evaluator
        self._key = evaluator.claim_issuer()
        self._principal = principal
        self._ttl = timedelta(seconds=ttl_s)
        self._clock = clock or _utc_now

    def issue_for_plan(self, task_id, plan):
        """Issue one grant per step, or none at all. Returns (grants, provenance)."""
        if not _nonempty_string(task_id) or not isinstance(plan, list) or not plan:
            raise MAEPError("issue_for_plan needs a task_id and a non-empty plan")
        now = self._clock()
        try:
            doc, provenance = self._manifest.current()
        except TrustAnchorError as exc:
            raise MAEPError(f"trust root unavailable, no grants issued: {exc}")
        grants = []
        for step in plan:
            try:
                manifest_grant = authorize(doc, principal=self._principal, action=action_name(step["action"]),
                                           resource=step["resource"], policy_version=POLICY_VERSION, now=now)
            except TrustAnchorError as exc:
                raise MAEPError(f"step {step.get('step_id')} not permitted by the owner manifest: {exc}")
            expires = min(now + self._ttl, _parse_ts(manifest_grant["expires_at"], "grant.expires_at"))
            grants.append({
                "authorization_id": step["authorization_id"], "principal": self._principal,
                "action": step["action"], "resource": step["resource"], "scope": list(step["scope"]),
                "conditions": [], "task_id": task_id, "policy_version": POLICY_VERSION, "decision": "ALLOW",
                "issued_at": now.isoformat(), "expires_at": expires.isoformat(),
            })
        self._evaluator._add(self._key, grants)
        return copy.deepcopy(grants), dict(provenance)
