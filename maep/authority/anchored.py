"""RT-06 AnchoredPolicyEvaluator: a PolicyEvaluator whose ALLOW also needs the trust root.

PolicyEvaluator checks a per-task grant (principal, action, resource, scope, task,
policy version, validity window). That grant comes from whoever built the evaluator, so
on its own it is not anchored (RUNTIME_ENFORCEMENT_PLAN_V1 Q-5). This wrapper adds a
second, independent requirement: a single live grant in the canonical owner manifest
must permit the same principal, action and resource. Either check failing -- or the
manifest being unavailable, malformed or revoked -- is DENY.

It has the same `evaluate(request, *, now=None)` interface, so TaskStore and
ActionGateway use it unchanged; every authority check on the HG runtime path
(AUTHORIZED, RUNNING, BLOCKED -> ASSESSED, preflight, before each effect) goes through it.
"""
import copy

from maep.authority.trust_anchor import TrustAnchorError, action_name, authorize


class AnchoredPolicyEvaluator:
    def __init__(self, evaluator, manifest):
        if not callable(getattr(evaluator, "evaluate", None)):
            raise TrustAnchorError("inner evaluator must provide evaluate()")
        if not callable(getattr(manifest, "current", None)):
            raise TrustAnchorError("manifest source must provide current()")
        self._inner = evaluator
        self._manifest = manifest

    def evaluate(self, request, *, now=None):
        decision = self._inner.evaluate(request, now=now)
        if decision.get("decision") != "ALLOW":
            return decision
        try:
            doc, provenance = self._manifest.current()
            authorize(doc, principal=request["principal"], action=action_name(request["action"]),
                      resource=request["resource"], policy_version=request["policy_version"], now=now)
        except Exception as exc:  # any failure to establish authority is a denial (MAEP-005)
            reason = str(exc) if isinstance(exc, TrustAnchorError) else f"{type(exc).__name__}: {exc}"
            return dict(decision, decision="DENY", reason=f"trust anchor: {reason}")
        anchored = copy.deepcopy(decision)
        anchored["anchor"] = {"commit": provenance.get("commit"), "fingerprint": provenance.get("fingerprint")}
        return anchored
