"""RT-06 canonical manifest source: the only production route to the trust root.

`load_manifest(fetch)` validates whatever bytes its caller's `fetch` returns, so on its
own it cannot know where they came from (finding P8). This module removes that choice:
the repository, ref and path are constants, and the manifest is read through GitHub's
REST API in two steps -- resolve the current commit of `main`, then read the manifest
at exactly that commit -- so the bytes and the recorded provenance refer to the same
snapshot. `main` is protected server-side by ruleset `main-maep` (PR only, no force push,
no deletion, required CI).

Limits (application level): code in the same process can still construct a document or
an evaluator of its own; this module guarantees only that HG's runtime path, when given
a CanonicalManifest built by `from_github`, reads `main`. Whoever can merge to `main`
controls the trust root -- see maep/spec/RT06_VALIDATION_RECORD_V1.md, finding T-1.
"""
import base64
import binascii
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from maep.authority.trust_anchor import (
    CANONICAL_BRANCH, CANONICAL_REPO, MANIFEST_PATH, TrustAnchorError, fingerprint, load_manifest,
)

API_ROOT = "https://api.github.com"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HTTP_TIMEOUT_S = 10


def _utc_now():
    return datetime.now(timezone.utc)


def urllib_get(url):
    """GET a GitHub API URL; returns (status, text). Honours HTTPS_PROXY. Never logs the token."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "HG-RT06-trust-anchor",
        "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def _get_json(http_get, url, what):
    try:
        status, body = http_get(url)
    except Exception as exc:
        raise TrustAnchorError(f"transport failure reading {what}: {type(exc).__name__}: {exc}")
    if status != 200:
        raise TrustAnchorError(f"{what} unavailable (status={status})")
    try:
        data = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise TrustAnchorError(f"{what} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise TrustAnchorError(f"{what} response must be an object")
    return data


def load_canonical_manifest(http_get=urllib_get):
    """Read the manifest from main of the canonical repository. Returns (doc, provenance).

    Every failure -- transport, missing file, wrong object type, bad encoding, invalid
    manifest -- raises TrustAnchorError, so callers deny.
    """
    commit = _get_json(http_get, f"{API_ROOT}/repos/{CANONICAL_REPO}/commits/{CANONICAL_BRANCH}",
                       f"commit of {CANONICAL_BRANCH}")
    sha = commit.get("sha")
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise TrustAnchorError("canonical branch did not resolve to a commit SHA")
    contents = _get_json(http_get, f"{API_ROOT}/repos/{CANONICAL_REPO}/contents/{MANIFEST_PATH}?ref={sha}",
                         f"{MANIFEST_PATH} at {sha[:12]}")
    if contents.get("type") != "file" or contents.get("path") != MANIFEST_PATH:
        raise TrustAnchorError("manifest path does not name a file")
    if contents.get("encoding") != "base64" or not isinstance(contents.get("content"), str):
        raise TrustAnchorError("manifest content is not base64-encoded text")
    try:
        text = base64.b64decode(contents["content"], validate=False).decode("utf-8")
    except (binascii.Error, ValueError) as exc:
        raise TrustAnchorError(f"manifest content cannot be decoded: {exc}")
    doc = load_manifest(lambda _path: (200, text), repo=CANONICAL_REPO, branch=CANONICAL_BRANCH,
                        path=MANIFEST_PATH)
    provenance = {"repo": CANONICAL_REPO, "ref": CANONICAL_BRANCH, "commit": sha,
                  "blob": contents.get("sha"), "path": MANIFEST_PATH, "fingerprint": fingerprint(doc)}
    return doc, provenance


class CanonicalManifest:
    """The current canonical manifest, reloaded when older than `max_age_s`.

    A failed reload never falls back to the previous document: revocation or loss of the
    source denies (fail closed). `max_age_s` bounds how long a revoked grant can still be
    honoured (time-of-check/time-of-use window).
    """

    def __init__(self, loader, *, max_age_s=300, clock=None):
        if not callable(loader):
            raise TrustAnchorError("manifest loader must be callable")
        if isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float)) or max_age_s < 0:
            raise TrustAnchorError("max_age_s must be a non-negative number")
        self._loader = loader
        self._max_age_s = max_age_s
        self._clock = clock or _utc_now
        self._lock = threading.Lock()
        self._doc = None
        self._provenance = None
        self._loaded_at = None

    @classmethod
    def from_github(cls, *, max_age_s=300, clock=None, http_get=urllib_get):
        """Production constructor: the trust root is main of OAI-GIANG/HG, nothing else."""
        return cls(lambda: load_canonical_manifest(http_get), max_age_s=max_age_s, clock=clock)

    def current(self):
        """Return (doc, provenance); raises TrustAnchorError if it cannot be (re)loaded."""
        with self._lock:
            now = self._clock()
            fresh = (self._loaded_at is not None
                     and (now - self._loaded_at).total_seconds() < self._max_age_s)
            if not fresh:
                self._doc = self._provenance = self._loaded_at = None
                try:
                    result = self._loader()
                except TrustAnchorError:
                    raise
                except Exception as exc:
                    raise TrustAnchorError(f"manifest loader failed: {type(exc).__name__}: {exc}")
                if not (isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], dict)):
                    raise TrustAnchorError("manifest loader returned an unexpected value")
                self._doc, self._provenance = result
                self._loaded_at = now
            return self._doc, dict(self._provenance or {})
