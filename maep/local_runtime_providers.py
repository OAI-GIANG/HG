"""Explicit local-runtime adapters for HG; Python standard library only.

These providers supply durable local mechanics, not production trust by themselves.
Callers must separately establish the authenticated principal and trusted policy /
provenance sources. Importing this module has no filesystem or process side effects.
"""
from __future__ import annotations

import hashlib
import json
import os
import fcntl
from datetime import datetime, timezone
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any

from maep.native_authority import AuthorityError, TrustRootRecord, load_json_strict
from maep.trust_source_contracts import require_trust_source_contract


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _read_private_json(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AuthorityError("local provider source unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AuthorityError("local provider source must be regular and non-symlink")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise AuthorityError("local provider source permissions must exclude group/other access")
    raw = load_json_strict(path)
    if not isinstance(raw, dict):
        raise AuthorityError("local provider source must be a JSON object")
    return raw


def _write_new_json(path: Path, body: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        raise AuthorityError("refusing to overwrite existing local provider record")
    fd, tmp = tempfile.mkstemp(prefix=".hg-provider-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(body) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        link = getattr(os, "link", None)
        if callable(link):
            # Hard link publishes the completed inode without replacing an existing file.
            link(tmp, path, follow_symlinks=False)
            os.unlink(tmp)
        else:
            # Android/Termux Python has no os.link. Reserve the name exclusively (fails if
            # anything, including a symlink, exists), then atomically replace only that
            # reservation with the completed file. A reader racing the replace sees an
            # empty file, which strict JSON loading rejects (fail closed).
            try:
                reserved = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                   | getattr(os, "O_NOFOLLOW", 0), mode)
            except FileExistsError:
                raise AuthorityError("refusing to overwrite existing local provider record") from None
            os.close(reserved)
            os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


class LocalPolicyProvider:
    """Read an explicitly supplied policy file bound to the given root generation.

    `provenance_verified` is not inferred from the JSON value: an injected verifier
    must validate policy origin/approval evidence. Without it, load_active blocks.
    """
    def __init__(self, path: str | Path, provenance_verifier: Any):
        require_trust_source_contract(provenance_verifier, "verify_policy_source",
                                      source_name="approved-policy-source-verifier")
        self.path = Path(path).expanduser().absolute()
        self.provenance_verifier = provenance_verifier

    def load_active(self, root: TrustRootRecord) -> dict[str, Any] | None:
        if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
            raise AuthorityError("cannot load policy against invalid root")
        raw = _read_private_json(self.path)
        policy = raw.get("policy")
        claimed = raw.get("policy_digest")
        if not isinstance(policy, dict) or claimed != _digest(policy):
            raise AuthorityError("local policy digest mismatch")
        try:
            provenance_ok = self.provenance_verifier.verify_policy_source(
                raw, root=root, policy=policy)
        except Exception as exc:
            raise AuthorityError("policy source provenance validation failed") from exc
        if provenance_ok is not True:
            raise AuthorityError("policy source provenance is not verified")
        version = policy.get("version")
        generation = policy.get("root_generation")
        approval_refs = policy.get("approval_evidence_refs")
        if (policy.get("status") != "ACTIVE"
                or not isinstance(generation, int) or isinstance(generation, bool)
                or generation != root.generation
                or not isinstance(version, str) or not version.strip()
                or not isinstance(approval_refs, list) or not approval_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in approval_refs)
                or len(approval_refs) != len(set(approval_refs))):
            raise AuthorityError("local policy is not active or does not bind current root")
        resolved = dict(policy)
        resolved["policy_digest"] = claimed
        # This flag is emitted only after the injected verifier returns literal True.
        resolved["provenance_verified"] = True
        return resolved


class LocalPrincipalProvider:
    """Resolve a principal only from an explicitly injected trusted session verifier."""
    def __init__(self, session_verifier: Any):
        require_trust_source_contract(session_verifier, "resolve_authenticated_session",
                                      source_name="authenticated-session-resolver")
        self.session_verifier = session_verifier

    def resolve(self, authenticated_context: Any) -> dict[str, Any] | None:
        try:
            result = self.session_verifier.resolve_authenticated_session(authenticated_context)
        except Exception as exc:
            raise AuthorityError("authenticated session could not be verified") from exc
        if (not isinstance(result, dict) or result.get("status") != "ACTIVE"
                or result.get("verified") is not True or result.get("revoked") is not False
                or not isinstance(result.get("principal_id"), str) or not result["principal_id"].strip()
                or not isinstance(result.get("session_id"), str) or not result["session_id"].strip()
                or not isinstance(result.get("identity_evidence_ref"), str)
                or not result["identity_evidence_ref"].strip()):
            return None
        # Reject incomplete authorization scope at the session boundary rather than
        # passing malformed identity data deeper into the native policy engine.
        for field in ("capabilities", "resource_scopes", "allowed_scopes"):
            values = result.get(field)
            if (not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value.strip() for value in values)
                    or len(values) != len(set(values))):
                return None
        try:
            issued_at = datetime.fromisoformat(result["issued_at"].replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (issued_at.tzinfo is None or expires_at.tzinfo is None
                    or issued_at > now or expires_at <= now or expires_at <= issued_at):
                return None
        except (KeyError, AttributeError, TypeError, ValueError):
            return None
        return dict(result)


class GitCandidateProvider:
    """Observe a checkout with git and compute a content manifest digest.

    This detects local candidate changes; it does not independently authenticate who
    created a commit or protect against an attacker able to rewrite the checkout.
    """
    def __init__(self, checkout: str | Path, *, timeout_seconds: float = 4.0):
        self.checkout = Path(checkout).expanduser().absolute()
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 10.0))

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.checkout), *args],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=self.timeout_seconds, text=True, encoding="utf-8",
        )
        return result.stdout.strip()

    def inspect(self, target: Any = None) -> dict[str, Any] | None:
        if target is not None and Path(str(target)).expanduser().absolute() != self.checkout:
            raise AuthorityError("candidate target does not match configured HG checkout")
        try:
            toplevel = Path(self._git("rev-parse", "--show-toplevel")).resolve()
            remote_urls = self._git("remote", "-v").splitlines()
            head = self._git("rev-parse", "HEAD")
            status = self._git("status", "--porcelain=v1", "--untracked-files=all")
            tracked_manifest = self._git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
            relpaths = [item for item in tracked_manifest.split("\0") if item]
            manifest = []
            for rel in sorted(set(relpaths)):
                path = toplevel / rel
                try:
                    st = path.lstat()
                except FileNotFoundError:
                    manifest.append({"path": rel, "state": "MISSING"})
                    continue
                if stat.S_ISLNK(st.st_mode):
                    target_text = os.readlink(path)
                    content_digest = _digest({"symlink_target": target_text})
                    kind = "SYMLINK"
                elif stat.S_ISREG(st.st_mode):
                    h = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(131072), b""):
                            h.update(chunk)
                    content_digest = "sha256:" + h.hexdigest()
                    kind = "FILE"
                elif stat.S_ISDIR(st.st_mode):
                    kind, content_digest = "DIRECTORY", None
                else:
                    kind, content_digest = "OTHER", None
                manifest.append({"path": rel, "kind": kind, "digest": content_digest})
            remotes_match = any(
                "github.com/OAI-GIANG/HG" in line or "github.com:OAI-GIANG/HG" in line
                for line in remote_urls
            )
            if not remotes_match:
                return None
            source_digest = _digest({"head": head, "status": status, "manifest": manifest})
            candidate_ref = "hg-local:" + head + ":" + source_digest.split(":", 1)[1]
            return {
                "verified": True, "repository": "OAI-GIANG/HG",
                "candidate_ref": candidate_ref, "commit": head,
                "source_manifest_digest": source_digest,
                "working_tree_dirty": bool(status), "working_tree_status": status,
                "checkout_path": str(toplevel),
                "verification_scope": "local_observation_not_independent_provenance",
            }
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None


class LocalLiveStateProvider:
    """Observe the live state Memory checkpoints and resume compare against.

    Returns the task id, the current verified candidate of the configured checkout, the
    version of the active policy (as verified by the injected policy provider against the
    current trust root) and one live resource: the checkout itself, versioned by its
    source manifest digest. It observes; it grants nothing and never repairs drift.
    """
    RESOURCE_ID = "repo:OAI-GIANG/HG"

    def __init__(self, *, candidate_provider: Any, checkout: str | Path, policy_provider: Any, root_store: Any):
        if not callable(getattr(candidate_provider, "inspect", None)):
            raise AuthorityError("live-state provider requires a candidate provider")
        if not callable(getattr(policy_provider, "load_active", None)) or not callable(getattr(root_store, "load_active", None)):
            raise AuthorityError("live-state provider requires policy provider and root store")
        self.candidate_provider = candidate_provider
        self.checkout = str(Path(checkout).expanduser().absolute())
        self.policy_provider = policy_provider
        self.root_store = root_store

    def __call__(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise AuthorityError("live-state observation requires a task id")
        root = self.root_store.load_active()
        if not isinstance(root, TrustRootRecord) or not root.verify_integrity():
            raise AuthorityError("live-state observation blocked: trust root unavailable")
        policy = self.policy_provider.load_active(root)
        if not isinstance(policy, dict) or policy.get("provenance_verified") is not True:
            raise AuthorityError("live-state observation blocked: active policy unverified")
        candidate = self.candidate_provider.inspect(self.checkout)
        if (not isinstance(candidate, dict) or candidate.get("verified") is not True
                or not isinstance(candidate.get("candidate_ref"), str)
                or not isinstance(candidate.get("source_manifest_digest"), str)):
            raise AuthorityError("live-state observation blocked: candidate unverified")
        return {
            "task_id": task_id,
            "candidate_ref": candidate["candidate_ref"],
            "policy_version": policy.get("version"),
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "resources": [{"resource_id": self.RESOURCE_ID, "version": candidate["source_manifest_digest"]}],
        }


class SQLiteIdempotencyLedger:
    """Durable idempotency ledger with transactional duplicate/conflict handling."""
    def __init__(self, path: str | Path):
        import sqlite3
        self.path = Path(path).expanduser().absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
            raise AuthorityError("idempotency database must be a regular non-symlink file")
        if self.path.exists() and stat.S_IMODE(self.path.stat().st_mode) & 0o077:
            raise AuthorityError("idempotency database permissions must exclude group/other access")
        self._sqlite3 = sqlite3
        self._connect(init=True).close()

    def _connect(self, *, init: bool = False):
        conn = self._sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        if init:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, request_digest TEXT NOT NULL, decision_digest TEXT NOT NULL, status TEXT NOT NULL, outcome TEXT, receipt_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        os.chmod(self.path, 0o600)
        return conn

    def claim(self, *, idempotency_key: str, request_digest: str, decision_digest: str) -> dict[str, Any]:
        if not all(isinstance(v, str) and v.strip() for v in (idempotency_key, request_digest, decision_digest)):
            raise AuthorityError("idempotency key and digests must be non-empty")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT request_digest, decision_digest, status FROM idempotency WHERE key=?", (idempotency_key,)).fetchone()
            if row is not None:
                conn.rollback()
                if row[0] != request_digest or row[1] != decision_digest:
                    return {"status": "CONFLICT"}
                return {"status": "DUPLICATE" if row[2] == "RESERVED" or row[2] in {"SUCCESS", "FAILURE", "UNKNOWN"} else "UNRESOLVED"}
            conn.execute("INSERT INTO idempotency(key,request_digest,decision_digest,status) VALUES(?,?,?,'RESERVED')", (idempotency_key, request_digest, decision_digest))
            conn.commit()
            return {"status": "RESERVED"}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_outcome(self, *, idempotency_key: str, request_digest: str,
                       outcome: str, receipt: dict[str, Any]) -> None:
        if outcome not in {"SUCCESS", "FAILURE", "UNKNOWN"}:
            raise AuthorityError("unsupported idempotency outcome")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT request_digest,status FROM idempotency WHERE key=?", (idempotency_key,)).fetchone()
            if row is None or row[0] != request_digest or row[1] != "RESERVED":
                raise AuthorityError("idempotency reservation is missing, conflicting, or already finalized")
            conn.execute("UPDATE idempotency SET status=?,outcome=?,receipt_json=?,updated_at=CURRENT_TIMESTAMP WHERE key=?", (outcome, outcome, _canonical(receipt).decode("utf-8"), idempotency_key))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def inspect(self, idempotency_key: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT key,request_digest,decision_digest,status,outcome,receipt_json FROM idempotency WHERE key=?", (idempotency_key,)).fetchone()
            if row is None:
                return None
            return {"idempotency_key": row[0], "request_digest": row[1],
                    "decision_digest": row[2], "status": row[3], "outcome": row[4],
                    "receipt": json.loads(row[5]) if row[5] else None}
        finally:
            conn.close()


class LocalReceiptSink:
    """Append-only local receipt JSONL; readback verifies event digest chain."""
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().absolute()
        self.path = self.directory / "receipts.jsonl"

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists() and not self.path.is_symlink():
            return []
        info = self.path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AuthorityError("receipt ledger must be a regular non-symlink file")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise AuthorityError("receipt ledger permissions must exclude group/other access")
        rows = []
        previous_digest = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.endswith("\n"):
                    raise AuthorityError("receipt ledger has an incomplete final line")
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise AuthorityError("receipt must be an object")
                claimed = row.pop("event_digest", None)
                if (row.get("sequence") != len(rows) + 1
                        or row.get("prev_digest") != previous_digest
                        or claimed != _digest(row)):
                    raise AuthorityError("receipt ledger integrity check failed")
                row["event_digest"] = claimed
                rows.append(row)
                previous_digest = claimed
        return rows

    def append(self, event: dict[str, Any]) -> str:
        if not isinstance(event, dict) or not event:
            raise AuthorityError("receipt event must be non-empty")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(self.path), flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise AuthorityError("receipt target must be a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            prior = self._read()
            body = dict(event)
            body["sequence"] = len(prior) + 1
            body["prev_digest"] = prior[-1]["event_digest"] if prior else None
            body["event_digest"] = _digest(body)
            line = _canonical(body) + b"\n"
            if os.write(fd, line) != len(line):
                raise AuthorityError("short receipt append")
            os.fsync(fd)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        return "hg-local-receipt:" + str(body["sequence"]) + ":" + body["event_digest"]

    def verify_integrity(self) -> bool:
        self._read()
        return True

    def read_all(self) -> list[dict[str, Any]]:
        return self._read()
