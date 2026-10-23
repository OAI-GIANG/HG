"""RT-06 canonical trust anchor provider (fail-closed).

Trust root is the manifest stored on the CANONICAL branch of the canonical repository.
A manifest found on a feature branch is NEVER accepted as trust root.
No caller-supplied permission boolean is accepted: authority comes only from the manifest.
"""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone

from maep.policy import GRANT_ACTIONS

CANONICAL_REPO = "OAI-GIANG/HG"
CANONICAL_BRANCH = "main"
MANIFEST_PATH = "maep/authority/owner-grants.json"
SUPPORTED_POLICY = "MAEP-1.1.0"
REQUIRED_MANIFEST_KEYS = ("trust_root", "policy_version", "grants")
REQUIRED_GRANT_KEYS = ("principal", "actions", "scope", "issued_at", "expires_at")
# Manifest actions name MAEP action classes ("maep.write" <-> WRITE). OTHER is not grantable
# by standing authority: it names no specific effect.
SUPPORTED_ACTIONS = frozenset("maep." + a.lower() for a in GRANT_ACTIONS if a != "OTHER")
# A scope entry is "<namespace>:<path>" with a non-empty path that is not just "/", so no
# entry can act as a wildcard over another namespace (e.g. "" used to match "/etc/passwd").
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_-]*:(?!/*$)\S+$")


class TrustAnchorError(Exception):
    """Raised on every unverifiable / ambiguous / expired authority condition."""


def action_name(maep_action):
    """Manifest action name for a MAEP action class, e.g. WRITE -> "maep.write"."""
    return "maep." + str(maep_action).lower()


def _parse_ts(value, field):
    if not isinstance(value, str) or not value:
        raise TrustAnchorError(f"{field} must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrustAnchorError(f"{field} is not valid ISO-8601: {exc}")
    if parsed.tzinfo is None:
        raise TrustAnchorError(f"{field} must include a timezone")
    return parsed


def _reject_duplicate_keys(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise TrustAnchorError(f"manifest has a duplicate key: {key!r}")
        seen[key] = value
    return seen


def _validate_grant(g):
    if not isinstance(g, dict):
        raise TrustAnchorError("grant entry must be an object")
    miss = [k for k in REQUIRED_GRANT_KEYS if k not in g]
    if miss:
        raise TrustAnchorError("grant missing keys: " + ", ".join(sorted(miss)))
    if not isinstance(g["principal"], str) or not g["principal"].strip():
        raise TrustAnchorError("grant.principal must be a non-empty string")
    if not isinstance(g["actions"], list) or not g["actions"]:
        raise TrustAnchorError("grant.actions must be a non-empty list")
    if not all(isinstance(a, str) and a for a in g["actions"]):
        raise TrustAnchorError("grant.actions must be non-empty strings")
    unsupported = sorted(set(g["actions"]) - SUPPORTED_ACTIONS)
    if unsupported:
        raise TrustAnchorError("grant has unsupported action(s): " + ", ".join(unsupported))
    if not isinstance(g["scope"], list) or not g["scope"]:
        raise TrustAnchorError("grant.scope must be a non-empty list")
    if not all(isinstance(s, str) and _SCOPE_RE.match(s) for s in g["scope"]):
        raise TrustAnchorError('grant.scope entries must be "<namespace>:<path>" strings')
    issued = _parse_ts(g["issued_at"], "grant.issued_at")
    expires = _parse_ts(g["expires_at"], "grant.expires_at")
    if expires <= issued:
        raise TrustAnchorError("grant.expires_at must be after grant.issued_at")


def load_manifest(fetch, *, repo=CANONICAL_REPO, branch=CANONICAL_BRANCH,
                  path=MANIFEST_PATH, expected_repo=CANONICAL_REPO):
    """fetch(path) -> (status:int, body:str) or raises. Any anomaly denies."""
    if repo != expected_repo:
        raise TrustAnchorError(f"repository mismatch: {repo} != {expected_repo}")
    if branch != CANONICAL_BRANCH:
        raise TrustAnchorError(f"refusing non-canonical branch as trust root: {branch}")
    if path != MANIFEST_PATH:
        raise TrustAnchorError(f"refusing unexpected manifest path: {path}")
    try:
        status, body = fetch(path)
    except Exception as exc:
        raise TrustAnchorError(f"transport failure: {exc}")
    if status != 200:
        raise TrustAnchorError(f"manifest unavailable (status={status})")
    if not isinstance(body, str) or not body.strip():
        raise TrustAnchorError("manifest body is empty or not text")
    try:
        doc = json.loads(body, object_pairs_hook=_reject_duplicate_keys)
    except ValueError as exc:
        raise TrustAnchorError(f"manifest is not valid JSON: {exc}")
    if not isinstance(doc, dict):
        raise TrustAnchorError("manifest root must be an object")
    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in doc]
    if missing:
        raise TrustAnchorError("manifest missing keys: " + ", ".join(sorted(missing)))
    if doc["trust_root"] != CANONICAL_BRANCH:
        raise TrustAnchorError("manifest trust_root is not the canonical branch")
    if doc["policy_version"] != SUPPORTED_POLICY:
        raise TrustAnchorError(f"unsupported policy_version: {doc['policy_version']}")
    if not isinstance(doc["grants"], list) or not doc["grants"]:
        raise TrustAnchorError("manifest grants must be a non-empty list")
    for g in doc["grants"]:
        _validate_grant(g)
    return copy.deepcopy(doc)


def authorize(doc, *, principal, action, resource, policy_version, now=None):
    """Raise TrustAnchorError unless a single unambiguous live grant allows it."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TrustAnchorError("evaluation time must be a timezone-aware datetime")
    if not isinstance(principal, str) or not principal:
        raise TrustAnchorError("principal is required")
    if not isinstance(action, str) or not action:
        raise TrustAnchorError("action is required")
    if not isinstance(resource, str) or not resource:
        raise TrustAnchorError("resource is required")
    if policy_version != doc["policy_version"]:
        raise TrustAnchorError("policy_version mismatch between request and manifest")
    matched = []
    for g in doc["grants"]:
        if g["principal"] != principal:
            continue
        if action not in g["actions"]:
            continue
        if not any(resource == s or resource.startswith(s.rstrip("/") + "/") for s in g["scope"]):
            continue
        issued = _parse_ts(g["issued_at"], "grant.issued_at")
        expires = _parse_ts(g["expires_at"], "grant.expires_at")
        if now < issued or now >= expires:
            continue                     # not live: a future renewal must not block a live grant
        matched.append(g)
    if not matched:
        raise TrustAnchorError("no live grant permits this principal/action/resource")
    if len(matched) > 1:
        raise TrustAnchorError("ambiguous authority: multiple matching grants")
    return copy.deepcopy(matched[0])


def fingerprint(doc):
    """Stable digest of the canonical manifest, for evidence binding."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
