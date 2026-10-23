"""RT-06 canonical trust anchor provider (fail-closed).

Trust root is the manifest stored on the CANONICAL branch of the canonical repository.
A manifest found on a feature branch is NEVER accepted as trust root.
No caller-supplied permission boolean is accepted: authority comes only from the manifest.
"""
import hashlib
import json
from datetime import datetime, timezone

CANONICAL_REPO = "OAI-GIANG/HG"
CANONICAL_BRANCH = "main"
MANIFEST_PATH = "maep/authority/owner-grants.json"
SUPPORTED_POLICY = "MAEP-1.1.0"
REQUIRED_MANIFEST_KEYS = ("trust_root", "policy_version", "grants")
REQUIRED_GRANT_KEYS = ("principal", "actions", "scope", "issued_at", "expires_at")


class TrustAnchorError(Exception):
    """Raised on every unverifiable / ambiguous / expired authority condition."""


def _parse_ts(value, field):
    if not isinstance(value, str) or not value:
        raise TrustAnchorError(f"{field} must be a non-empty ISO-8601 string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrustAnchorError(f"{field} is not valid ISO-8601: {exc}")


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
        doc = json.loads(body)
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
        if not isinstance(g, dict):
            raise TrustAnchorError("grant entry must be an object")
        miss = [k for k in REQUIRED_GRANT_KEYS if k not in g]
        if miss:
            raise TrustAnchorError("grant missing keys: " + ", ".join(sorted(miss)))
        if not isinstance(g["actions"], list) or not g["actions"]:
            raise TrustAnchorError("grant.actions must be a non-empty list")
        if not all(isinstance(a, str) and a for a in g["actions"]):
            raise TrustAnchorError("grant.actions must be non-empty strings")
        if not isinstance(g["scope"], list) or not g["scope"]:
            raise TrustAnchorError("grant.scope must be a non-empty list")
        _parse_ts(g["issued_at"], "grant.issued_at")
        _parse_ts(g["expires_at"], "grant.expires_at")
    return doc


def authorize(doc, *, principal, action, resource, policy_version, now=None):
    """Raise TrustAnchorError unless a single unambiguous live grant allows it."""
    now = now or datetime.now(timezone.utc)
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
        if now < issued:
            raise TrustAnchorError("grant not yet valid")
        if now >= expires:
            continue
        matched.append(g)
    if not matched:
        raise TrustAnchorError("no live grant permits this principal/action/resource")
    if len(matched) > 1:
        raise TrustAnchorError("ambiguous authority: multiple matching grants")
    return matched[0]


def fingerprint(doc):
    """Stable digest of the canonical manifest, for evidence binding."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
