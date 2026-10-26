"""Local file-backed RootStore and append-only EvidenceSink for HG.

This module is inert on import. Callers choose the data directory explicitly.
It uses the existing native-authority record contract and Python stdlib only.
"""
from __future__ import annotations

from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from maep.native_authority import AuthorityError, TrustRootRecord, load_json_strict


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_new_atomic(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Create a new file atomically; never replace an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise AuthorityError("refusing to overwrite existing authority/evidence file")
    fd, temp_name = tempfile.mkstemp(prefix=".hg-write-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic no-replace publication via exclusive destination creation.
        # Write to the destination only after O_EXCL succeeds.
        dest_fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(dest_fd, "wb") as destination:
                with open(temp_name, "rb") as source:
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise
        os.unlink(temp_name)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class LocalRootStore:
    """Persist exactly one active TrustRootRecord beneath an explicitly chosen directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().absolute()
        self.root_path = self.directory / "active-root.json"

    def load_active(self) -> TrustRootRecord | None:
        if not self.root_path.exists() and not self.root_path.is_symlink():
            return None
        try:
            info = self.root_path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise AuthorityError("root record must be a regular non-symlink file")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise AuthorityError("root record permissions must exclude group/other access")
            raw = load_json_strict(self.root_path)
            expected = set(TrustRootRecord.__dataclass_fields__)
            if set(raw) != expected:
                raise AuthorityError("root record fields do not match TrustRootRecord")
            record = TrustRootRecord(**raw)
            if not record.verify_integrity():
                raise AuthorityError("stored trust-root integrity check failed")
            return record
        except AuthorityError:
            raise
        except Exception as exc:
            raise AuthorityError("stored trust-root record is invalid") from exc

    def store_active(self, record: TrustRootRecord) -> None:
        if not isinstance(record, TrustRootRecord) or not record.verify_integrity():
            raise AuthorityError("refusing to store invalid trust-root record")
        _write_new_atomic(self.root_path, _canonical(asdict(record)))


class LocalEvidenceSink:
    """Append-only JSONL evidence with sequential IDs and per-event payload digests."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser().absolute()
        self.ledger_path = self.directory / "evidence.jsonl"
        self.head_path = self.directory / "evidence-head.json"

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists() and not self.ledger_path.is_symlink():
            return []
        info = self.ledger_path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AuthorityError("evidence ledger must be a regular non-symlink file")
        events = []
        try:
            with self.ledger_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.endswith("\n"):
                        raise AuthorityError("evidence ledger has an incomplete final line")
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise AuthorityError("evidence event must be an object")
                    events.append(item)
        except AuthorityError:
            raise
        except Exception as exc:
            raise AuthorityError("evidence ledger is unreadable or malformed") from exc
        for index, event in enumerate(events, 1):
            if event.get("sequence") != index:
                raise AuthorityError("evidence sequence integrity check failed")
            body = {key: value for key, value in event.items()
                    if key != "event_digest"}
            from hashlib import sha256
            digest = "sha256:" + sha256(_canonical(body)).hexdigest()
            if event.get("event_digest") != digest:
                raise AuthorityError("evidence event integrity check failed")
        return events

    def append(self, event: dict[str, Any]) -> str:
        if not isinstance(event, dict) or not event:
            raise AuthorityError("evidence event must be a non-empty object")
        self.directory.mkdir(parents=True, exist_ok=True)
        # Use O_APPEND, one write, and fsync; never truncate or rewrite previous lines.
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(str(self.ledger_path), flags, 0o600)
        except OSError as exc:
            raise AuthorityError("evidence ledger must be a regular non-symlink file") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise AuthorityError("evidence target is not a regular file")
            # Serialize read-validate-append-head across threads and processes
            # (runtime.http_server is threaded and every decision appends evidence).
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                events = self._read_events()
                # A head file is supplemental read-back evidence; the ledger sequence remains canonical.
                head = {"last_sequence": len(events), "last_event_digest":
                        events[-1]["event_digest"] if events else None}
                if self.head_path.exists() or self.head_path.is_symlink():
                    stored_head = load_json_strict(self.head_path)
                    if stored_head != head:
                        raise AuthorityError("evidence head does not match ledger; refusing append")
                elif events:
                    raise AuthorityError("evidence head missing for non-empty ledger")
                from hashlib import sha256
                body = dict(event)
                body["sequence"] = len(events) + 1
                body["event_digest"] = ""
                body["event_digest"] = "sha256:" + sha256(_canonical({
                    key: value for key, value in body.items() if key != "event_digest"
                })).hexdigest()
                line = _canonical(body) + b"\n"
                written = os.write(fd, line)
                if written != len(line):
                    raise AuthorityError("short evidence append")
                os.fsync(fd)
                new_head = {"last_sequence": body["sequence"],
                            "last_event_digest": body["event_digest"]}
                # Head replacement is atomic but the evidence ledger itself is append-only.
                temp_fd, temp_name = tempfile.mkstemp(prefix=".hg-head-", dir=str(self.directory))
                try:
                    os.fchmod(temp_fd, 0o600)
                    with os.fdopen(temp_fd, "wb") as handle:
                        handle.write(_canonical(new_head))
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, self.head_path)
                finally:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        return "hg-local-evidence:" + str(body["sequence"]) + ":" + body["event_digest"]

    def verify_integrity(self) -> bool:
        events = self._read_events()
        expected = {"last_sequence": len(events),
                    "last_event_digest": events[-1]["event_digest"] if events else None}
        if not self.head_path.exists() and not self.head_path.is_symlink():
            return not events
        info = self.head_path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AuthorityError("evidence head must be a regular non-symlink file")
        if load_json_strict(self.head_path) != expected:
            raise AuthorityError("evidence head integrity check failed")
        return True

    def find_decision(self, decision_digest: str) -> dict[str, Any] | None:
        """Return the one ALLOW decision record with this digest from an intact ledger.

        Reads under a shared lock (appends hold it exclusively), verifies the whole
        ledger and its head first, and raises on any integrity problem or ambiguity.
        Only `authorization.decision` events (ALLOW) are considered.
        """
        if (not isinstance(decision_digest, str) or len(decision_digest) != 71
                or not decision_digest.startswith("sha256:")
                or any(ch not in "0123456789abcdef" for ch in decision_digest[7:])):
            raise AuthorityError("decision digest is malformed")
        if not self.ledger_path.exists() and not self.ledger_path.is_symlink():
            return None
        flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
        try:
            fd = os.open(str(self.ledger_path), flags)
        except OSError as exc:
            raise AuthorityError("evidence ledger must be a regular non-symlink file") from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            try:
                if self.verify_integrity() is not True:
                    raise AuthorityError("evidence ledger integrity unverified")
                events = self._read_events()
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        matches = [event["payload"] for event in events
                   if event.get("event_type") == "authorization.decision"
                   and isinstance(event.get("payload"), dict)
                   and event["payload"].get("decision_digest") == decision_digest]
        if len(matches) > 1:
            raise AuthorityError("decision digest is not unique in the evidence ledger")
        return dict(matches[0]) if matches else None
