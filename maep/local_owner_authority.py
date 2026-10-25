"""Local owner-controlled bootstrap source for HG (Python standard library only).

Reads HG's own local owner decision file. It never creates a trust root,
changes policy, starts a runtime, or writes evidence as an import side effect.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


class LocalOwnerAuthorityError(RuntimeError):
    """The local owner authority source is missing or invalid."""


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def payload_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class LocalOwnerApprovalSource:
    """Verify approval for one exact initial-root payload.

    The source is local-only. Owner/mode checks reduce accidental exposure,
    but cannot protect against a compromised process running as the same user.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else (
            Path.home() / ".config/hg/authority/owner-bootstrap.json"
        )

    @staticmethod
    def _no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise LocalOwnerAuthorityError("duplicate JSON key")
            result[key] = value
        return result

    def load(self) -> dict[str, Any]:
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise LocalOwnerAuthorityError("local owner authority source unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise LocalOwnerAuthorityError("authority source must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise LocalOwnerAuthorityError("authority source is not owned by current local user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise LocalOwnerAuthorityError("authority source permissions must exclude group/other access")
        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8"),
                object_pairs_hook=self._no_duplicate_keys,
            )
        except LocalOwnerAuthorityError:
            raise
        except Exception as exc:
            raise LocalOwnerAuthorityError("authority source is invalid JSON") from exc
        if not isinstance(data, dict):
            raise LocalOwnerAuthorityError("authority source must be a JSON object")
        return data

    def validate_owner_approval(self, canonical_payload: bytes, approval: Any) -> bool:
        if not isinstance(approval, dict):
            return False
        try:
            source = self.load()
            payload = json.loads(
                canonical_payload.decode("utf-8"),
                object_pairs_hook=self._no_duplicate_keys,
            )
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        if source.get("schema_version") != "hg.local-owner-bootstrap-source.v1":
            return False
        if source.get("repository") != "OAI-GIANG/HG":
            return False
        if source.get("device_scope") != "this-phone-local-only":
            return False
        if source.get("decision") != "APPROVE":
            return False
        if source.get("action") != "bootstrap_initial_trust_root":
            return False
        if source.get("activation_status") != "SOURCE_CREATED_ROOT_NOT_PROVISIONED":
            return False
        if source.get("root_payload") != payload:
            return False
        if approval != source:
            return False
        return True
