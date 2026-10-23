import json
from datetime import datetime, timedelta, timezone
import pytest

from maep.authority.trust_anchor import (
    CANONICAL_BRANCH, MANIFEST_PATH, TrustAnchorError, authorize, fingerprint, load_manifest,
)

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def _doc(**over):
    doc = {
        "trust_root": "main",
        "policy_version": "MAEP-1.1.0",
        "grants": [{
            "principal": "owner",
            "actions": ["maep.commit"],
            "scope": ["repo:OAI-GIANG/HG"],
            "issued_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        }],
    }
    doc.update(over)
    return doc


def _fetch(doc=None, status=200, raw=None):
    body = raw if raw is not None else json.dumps(doc if doc is not None else _doc())
    return lambda path: (status, body)


def test_valid_grant_allows():
    doc = load_manifest(_fetch(), repo="OAI-GIANG/HG", branch=CANONICAL_BRANCH)
    assert authorize(doc, principal="owner", action="maep.commit",
                     resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)


def test_unknown_principal_denied():
    doc = load_manifest(_fetch())
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="agent", action="maep.commit",
                  resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)


def test_wrong_action_denied():
    doc = load_manifest(_fetch())
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="owner", action="repo.delete",
                  resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)


def test_expired_grant_denied():
    d = _doc()
    d["grants"][0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    doc = load_manifest(_fetch(d))
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="owner", action="maep.commit",
                  resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)


def test_scope_mismatch_denied():
    doc = load_manifest(_fetch())
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="owner", action="maep.commit",
                  resource="repo:OTHER/REPO", policy_version="MAEP-1.1.0", now=NOW)


def test_feature_branch_never_trust_root():
    with pytest.raises(TrustAnchorError):
        load_manifest(_fetch(), branch="rt06/trust-anchor-provider-20261023")


def test_missing_manifest_denied():
    with pytest.raises(TrustAnchorError):
        load_manifest(_fetch(status=404, raw=""))


def test_transport_failure_denied():
    def boom(path):
        raise OSError("network down")
    with pytest.raises(TrustAnchorError):
        load_manifest(boom)


def test_ambiguous_grants_denied():
    d = _doc()
    d["grants"].append(dict(d["grants"][0]))
    doc = load_manifest(_fetch(d))
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="owner", action="maep.commit",
                  resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.1.0", now=NOW)


def test_wrong_trust_root_denied():
    doc = _doc(trust_root="rt06/branch")
    with pytest.raises(TrustAnchorError):
        load_manifest(_fetch(doc))


def test_policy_version_mismatch_denied():
    doc = load_manifest(_fetch())
    with pytest.raises(TrustAnchorError):
        authorize(doc, principal="owner", action="maep.commit",
                  resource="repo:OAI-GIANG/HG", policy_version="MAEP-1.0.0", now=NOW)


def test_fingerprint_stable():
    doc = load_manifest(_fetch())
    assert fingerprint(doc) == fingerprint(json.loads(json.dumps(doc)))
