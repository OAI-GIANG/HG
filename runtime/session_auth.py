"""Candidate D3 session source for runtime.service -- NOT registered as a production binding.

ADR-012 leaves the authenticated-session source an owner decision. This module implements
the option recommended to the owner (a dedicated token for runtime.service, the same
Bearer mechanism hg serve uses under ADR-011) so that, if approved, registering it is a
reviewed one-line change in runtime/production_config.py. Until then nothing imports it
in production code.

Model (single owner session, matching HGHTTPServer's runtime-bound context check):
- A session record (owner-controlled JSON, mode 600, owned by this user, no symlink)
  binds a session id and principal to the SHA-256 of a bearer token, a validity window
  and explicit capabilities / resource scopes / allowed scopes issued by the owner.
- A revocation file (same protection) lists revoked session ids; it must exist.
- Every call re-reads both files, so expiry and revocation apply immediately.
- The token itself is never stored here, logged, or returned; requests are matched by
  comparing fixed-length digests with hmac.compare_digest.

The three seams runtime.service needs come from one object:
  request_authenticator          -> TokenSessionSource.authenticate_request(headers)
  authenticated-context-provider -> TokenSessionSource.authenticated_context
  authenticated-session-resolver -> TokenSessionSource (resolve_authenticated_session),
                                    consumed by maep.local_runtime_providers.LocalPrincipalProvider
Standard library only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from typing import Any

from maep.local_runtime_providers import _read_private_json, _write_new_json
from maep.native_authority import AuthorityError

SESSION_SCHEMA = "hg-runtime-session-v1"
REVOCATION_SCHEMA = "hg-runtime-session-revocations-v1"
SESSION_KEYS = frozenset({
    "schema", "session_id", "principal_id", "token_sha256", "issued_at", "expires_at",
    "capabilities", "resource_scopes", "allowed_scopes",
})
REVOCATION_KEYS = frozenset({"schema", "revoked_session_ids"})
MAX_RECORD_BYTES = 65536
MAX_SESSION_DAYS = 366
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass(frozen=True)
class SessionContext:
    """Authenticated context: which session and principal a request acts as."""
    session_id: str
    principal_id: str


def _token_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("ascii")).hexdigest()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthorityError("session timestamp missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AuthorityError("session timestamp invalid") from None
    if parsed.tzinfo is None:
        raise AuthorityError("session timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _unique_strings(value: Any, label: str) -> list[str]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise AuthorityError(f"session {label} must be a non-empty list of unique strings")
    return list(value)


def _private_owned_record(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AuthorityError("session source unavailable") from exc
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise AuthorityError("session source must be owned by the runtime user")
    if info.st_size > MAX_RECORD_BYTES:
        raise AuthorityError("session source too large")
    return _read_private_json(path)   # regular, non-symlink, no group/other bits, strict JSON


def _absolute(path: Any, label: str) -> Path:
    if not isinstance(path, (str, Path)) or not str(path) or not Path(path).is_absolute():
        raise AuthorityError(f"{label} must be an absolute path")
    return Path(path)


class TokenSessionSource:
    """Owner-issued single-session source; fails closed on any anomaly."""

    def __init__(self, *, session_path: str | Path, revocation_path: str | Path):
        self.session_path = _absolute(session_path, "session_path")
        self.revocation_path = _absolute(revocation_path, "revocation_path")
        # Validate both files now: a broken source blocks startup, not the first request.
        self._revoked(self._load()["session_id"])

    def __repr__(self):
        return f"TokenSessionSource(session_path={str(self.session_path)!r})"

    # -- records -------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        record = _private_owned_record(self.session_path)
        if set(record) != SESSION_KEYS or record.get("schema") != SESSION_SCHEMA:
            raise AuthorityError("session record does not match the schema")
        for key in ("session_id", "principal_id"):
            if not isinstance(record[key], str) or not _IDENT.fullmatch(record[key]):
                raise AuthorityError(f"session {key} is invalid")
        if not isinstance(record["token_sha256"], str) or not _DIGEST.fullmatch(record["token_sha256"]):
            raise AuthorityError("session token digest is invalid")
        issued, expires = _parse_time(record["issued_at"]), _parse_time(record["expires_at"])
        if expires <= issued or expires - issued > timedelta(days=MAX_SESSION_DAYS):
            raise AuthorityError("session validity window is invalid")
        for key in ("capabilities", "resource_scopes", "allowed_scopes"):
            _unique_strings(record[key], key)
        return record

    def _revoked(self, session_id: str) -> bool:
        doc = _private_owned_record(self.revocation_path)
        if set(doc) != REVOCATION_KEYS or doc.get("schema") != REVOCATION_SCHEMA:
            raise AuthorityError("session revocation list does not match the schema")
        revoked = doc["revoked_session_ids"]
        if not isinstance(revoked, list) or any(not isinstance(item, str) for item in revoked):
            raise AuthorityError("session revocation list is malformed")
        return session_id in revoked

    def _active(self, record: dict[str, Any], now: datetime) -> bool:
        return (_parse_time(record["issued_at"]) <= now < _parse_time(record["expires_at"])
                and not self._revoked(record["session_id"]))

    # -- seams ---------------------------------------------------------------------
    def authenticate_request(self, headers: Any, *, now: datetime | None = None) -> SessionContext:
        """request-authenticator: exactly one 'Authorization: Bearer <token>' for the active session."""
        if hasattr(headers, "get_all"):
            values = headers.get_all("Authorization") or []
        else:
            value = headers.get("Authorization") if hasattr(headers, "get") else None
            values = [] if value is None else [value]
        if len(values) != 1 or not isinstance(values[0], str) or not values[0].startswith("Bearer "):
            raise AuthorityError("request is not authenticated")
        token = values[0][len("Bearer "):]
        if not 32 <= len(token) <= 512 or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
            raise AuthorityError("request is not authenticated")
        record = self._load()
        if not hmac.compare_digest(_token_digest(token), record["token_sha256"]):
            raise AuthorityError("request is not authenticated")
        if not self._active(record, (now or datetime.now(timezone.utc)).astimezone(timezone.utc)):
            raise AuthorityError("session is expired, not yet valid or revoked")
        return SessionContext(record["session_id"], record["principal_id"])

    def authenticated_context(self, *, now: datetime | None = None) -> SessionContext:
        """authenticated-context-provider: the session the runtime acts under."""
        record = self._load()
        if not self._active(record, (now or datetime.now(timezone.utc)).astimezone(timezone.utc)):
            raise AuthorityError("runtime session is expired, not yet valid or revoked")
        return SessionContext(record["session_id"], record["principal_id"])

    def resolve_authenticated_session(self, authenticated_context: Any) -> dict[str, Any] | None:
        """authenticated-session-resolver contract used by LocalPrincipalProvider."""
        if not isinstance(authenticated_context, SessionContext):
            return None
        record = self._load()
        if (authenticated_context.session_id != record["session_id"]
                or authenticated_context.principal_id != record["principal_id"]):
            return None
        revoked = self._revoked(record["session_id"])
        now = datetime.now(timezone.utc)
        in_window = _parse_time(record["issued_at"]) <= now < _parse_time(record["expires_at"])
        record_digest = "sha256:" + hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "status": "ACTIVE" if in_window and not revoked else ("REVOKED" if revoked else "EXPIRED"),
            "verified": True, "revoked": revoked,
            "principal_id": record["principal_id"], "session_id": record["session_id"],
            "identity_evidence_ref": "hg-session-record:" + record_digest,
            "capabilities": list(record["capabilities"]),
            "resource_scopes": list(record["resource_scopes"]),
            "allowed_scopes": list(record["allowed_scopes"]),
            "issued_at": record["issued_at"], "expires_at": record["expires_at"],
        }


# -- owner tooling (explicit command; never called by the runtime) -----------------
def issue_session(*, session_path: str | Path, token_path: str | Path, revocation_path: str | Path,
                  principal_id: str, valid_days: int, capabilities: list[str],
                  resource_scopes: list[str], allowed_scopes: list[str],
                  now: datetime | None = None) -> dict[str, str]:
    """Create a token file and a session record; never overwrites. Returns no secret."""
    session_path = _absolute(session_path, "session_path")
    token_path = _absolute(token_path, "token_path")
    revocation_path = _absolute(revocation_path, "revocation_path")
    if not isinstance(principal_id, str) or not _IDENT.fullmatch(principal_id):
        raise AuthorityError("principal_id is invalid")
    if isinstance(valid_days, bool) or not isinstance(valid_days, int) or not 1 <= valid_days <= MAX_SESSION_DAYS:
        raise AuthorityError("valid_days must be in 1..366")
    for label, values in (("capabilities", capabilities), ("resource_scopes", resource_scopes),
                          ("allowed_scopes", allowed_scopes)):
        _unique_strings(values, label)
    for path in (session_path, token_path):
        if path.exists() or path.is_symlink():
            raise AuthorityError(f"refusing to overwrite {path.name}")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    token = secrets.token_urlsafe(48)                       # 64 printable ASCII characters
    session_id = "hg-session-" + secrets.token_hex(8)
    record = {
        "schema": SESSION_SCHEMA, "session_id": session_id, "principal_id": principal_id,
        "token_sha256": _token_digest(token),
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=valid_days)).isoformat().replace("+00:00", "Z"),
        "capabilities": list(capabilities), "resource_scopes": list(resource_scopes),
        "allowed_scopes": list(allowed_scopes),
    }
    token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    created = [token_path]
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not revocation_path.exists():
            _write_new_json(revocation_path, {"schema": REVOCATION_SCHEMA, "revoked_session_ids": []})
            created.append(revocation_path)
        # The session record is written last: until it exists the token authenticates
        # nothing, and a failure before this point removes everything created here.
        _write_new_json(session_path, record)
    except BaseException:
        for path in created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    return {"session_id": session_id, "expires_at": record["expires_at"]}


def revoke_session(*, revocation_path: str | Path, session_id: str) -> None:
    """Add a session id to the revocation list (atomic replace, mode 600)."""
    revocation_path = _absolute(revocation_path, "revocation_path")
    if not isinstance(session_id, str) or not _IDENT.fullmatch(session_id):
        raise AuthorityError("session_id is invalid")
    doc = _private_owned_record(revocation_path)
    if set(doc) != REVOCATION_KEYS or doc.get("schema") != REVOCATION_SCHEMA:
        raise AuthorityError("session revocation list does not match the schema")
    revoked = list(doc["revoked_session_ids"])
    if session_id not in revoked:
        revoked.append(session_id)
    fd, tmp = tempfile.mkstemp(prefix=".hg-revocations-", dir=str(revocation_path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema": REVOCATION_SCHEMA, "revoked_session_ids": revoked}, handle,
                      sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, revocation_path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime.session_auth",
                                     description="Owner tooling for the candidate runtime.service session source.")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--session-file", required=True)
    issue.add_argument("--token-file", required=True)
    issue.add_argument("--revocation-file", required=True)
    issue.add_argument("--principal", required=True)
    issue.add_argument("--days", type=int, required=True)
    issue.add_argument("--capability", action="append", required=True)
    issue.add_argument("--resource-scope", action="append", required=True)
    issue.add_argument("--allowed-scope", action="append", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--revocation-file", required=True)
    revoke.add_argument("--session-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "issue":
            result = issue_session(
                session_path=args.session_file, token_path=args.token_file,
                revocation_path=args.revocation_file, principal_id=args.principal,
                valid_days=args.days, capabilities=args.capability,
                resource_scopes=args.resource_scope, allowed_scopes=args.allowed_scope)
            print(json.dumps({"result": "ISSUED", **result}, sort_keys=True))
        else:
            revoke_session(revocation_path=args.revocation_file, session_id=args.session_id)
            print(json.dumps({"result": "REVOKED", "session_id": args.session_id}, sort_keys=True))
    except AuthorityError as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
