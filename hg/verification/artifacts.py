"""Content-addressed, immutable evidence payload storage for the HG runtime.

Metadata remains owned by MAEP TaskStore's tasks.jsonl ledger. This store contains
payload bytes only; callers persist the returned reference in MAEP evidence metadata.
Writes publish a complete blob atomically before the ledger reference is appended.
A crash may leave an unreferenced blob, which is reported as an orphan and never
silently deleted. This is a same-UID integrity mechanism, not a tamper-proof vault.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

from maep.admission import require_writer_session
from maep.core import MAEPError


class EvidenceArtifactError(MAEPError):
    """An evidence payload is invalid, unsafe, missing or does not match its digest."""


_HEX = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024


class EvidenceArtifactStore:
    def __init__(self, root, *, writer_session=None, read_only=False, max_bytes=4 * 1024 * 1024):
        self.root = Path(root).absolute()
        if not isinstance(read_only, bool):
            raise EvidenceArtifactError("read_only must be a boolean")
        self.read_only = read_only
        self.max_bytes = self._validate_limit(max_bytes)
        if not self.root.is_absolute() or self.root.resolve() != self.root:
            raise EvidenceArtifactError("evidence root must be absolute and contain no symlinked parents")
        if not self.read_only:
            require_writer_session(self.root / "sha256" / "00" / "placeholder", writer_session)
        self._validate_existing_root()

    @staticmethod
    def _validate_limit(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise EvidenceArtifactError("max_bytes must be a positive integer")
        return value

    @staticmethod
    def _assert_private_directory(path, label):
        try:
            st = Path(path).lstat()
        except OSError as exc:
            raise EvidenceArtifactError(f"{label} is unavailable") from exc
        if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
                or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077):
            raise EvidenceArtifactError(f"{label} must be an owner-owned private real directory")
        return st

    def _validate_existing_root(self):
        if self.root.exists() or self.root.is_symlink():
            self._assert_private_directory(self.root, "evidence root")
        elif self.read_only:
            raise EvidenceArtifactError("read-only evidence root does not exist")

    def _assert_payload_namespace(self, digest):
        self._assert_private_directory(self.root, "evidence root")
        self._assert_private_directory(self.root / "sha256", "evidence namespace")
        self._assert_private_directory(self.root / "sha256" / digest[:2], "evidence digest directory")

    @staticmethod
    def _ensure_dir(path):
        try:
            path.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise EvidenceArtifactError("cannot create evidence storage directory") from exc
        st = path.lstat()
        if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
                or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077):
            raise EvidenceArtifactError("evidence storage directory is not private and owner-controlled")

    def _ensure_layout(self, prefix):
        self._ensure_dir(self.root)
        self._ensure_dir(self.root / "sha256")
        self._ensure_dir(self.root / "sha256" / prefix)

    def _blob_path(self, digest):
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise EvidenceArtifactError("invalid SHA-256 digest")
        return self.root / "sha256" / digest[:2] / digest

    @staticmethod
    def _fsync_directory(path):
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _read_path(self, path, *, expected_digest, max_bytes):
        # O_NONBLOCK: opening a FIFO planted at a blob path must fail the type check
        # below instead of blocking until a writer appears. It has no effect on reads
        # of regular files.
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise EvidenceArtifactError("evidence payload is missing or cannot be opened safely") from exc
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > max_bytes):
                raise EvidenceArtifactError("evidence payload type, owner, permissions or size is invalid")
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, min(_CHUNK, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise EvidenceArtifactError("evidence payload exceeds the read limit")
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(fd)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_digest:
            raise EvidenceArtifactError("evidence payload SHA-256 mismatch")
        return data

    def put(self, payload, *, max_bytes=None):
        if self.read_only:
            raise EvidenceArtifactError("read-only evidence store refuses writes")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise EvidenceArtifactError("payload must be bytes-like")
        data = bytes(payload)
        limit = self.max_bytes if max_bytes is None else max_bytes
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or len(data) > limit:
            raise EvidenceArtifactError("payload exceeds the configured evidence size limit")
        digest = hashlib.sha256(data).hexdigest()
        final = self._blob_path(digest)
        self._ensure_layout(digest[:2])
        if final.exists() or final.is_symlink():
            existing = self._read_path(final, expected_digest=digest, max_bytes=limit)
            if existing != data:
                raise EvidenceArtifactError("content-addressed evidence collision")
        else:
            temp = final.parent / (".tmp-" + uuid.uuid4().hex)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(temp, flags, 0o600)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view[:_CHUNK])
                    if written <= 0:
                        raise OSError("short evidence write")
                    view = view[written:]
                os.fsync(fd)
            except Exception:
                os.close(fd)
                try:
                    temp.unlink()
                except OSError:
                    pass
                raise
            else:
                os.close(fd)
            try:
                # Atomic publication of a complete, fsynced blob. A same-digest
                # concurrent writer can only publish the same content-addressed bytes.
                os.replace(temp, final)
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
            self._fsync_directory(final.parent)
        return {
            "payload_ref": "sha256:" + digest,
            "sha256": digest,
            "payload_bytes": len(data),
            "payload_store": "content-addressed-filesystem-v1",
        }

    def get(self, payload_ref, *, max_bytes=None):
        if not isinstance(payload_ref, str) or not payload_ref.startswith("sha256:"):
            raise EvidenceArtifactError("payload_ref must use sha256:<digest>")
        digest = payload_ref[7:]
        blob = self._blob_path(digest)
        self._assert_payload_namespace(digest)
        limit = self.max_bytes if max_bytes is None else self._validate_limit(max_bytes)
        return self._read_path(blob, expected_digest=digest, max_bytes=limit)

    def verify_metadata(self, integrity_metadata):
        if not isinstance(integrity_metadata, dict):
            raise EvidenceArtifactError("integrity_metadata must be an object")
        ref = integrity_metadata.get("payload_ref")
        expected = integrity_metadata.get("sha256")
        size = integrity_metadata.get("payload_bytes")
        if not isinstance(expected, str) or not _HEX.fullmatch(expected) or ref != "sha256:" + expected:
            raise EvidenceArtifactError("evidence metadata digest/reference mismatch")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > self.max_bytes:
            raise EvidenceArtifactError("evidence metadata payload_bytes is invalid")
        payload = self.get(ref)
        if len(payload) != size:
            raise EvidenceArtifactError("evidence metadata size mismatch")
        return {"status": "PASS", "sha256": expected, "payload_bytes": size, "payload_ref": ref}

    def find_temporary_artifacts(self):
        """List unpublished temporary files left by interrupted writes; never deletes them."""
        base = self.root / "sha256"
        if not (self.root.exists() or self.root.is_symlink()):
            return []
        self._assert_private_directory(self.root, "evidence root")
        if not (base.exists() or base.is_symlink()):
            return []
        self._assert_private_directory(base, "evidence namespace")
        found = []
        for prefix in sorted(base.iterdir()):
            self._assert_private_directory(prefix, "evidence digest directory")
            for item in sorted(prefix.iterdir()):
                if item.name.startswith(".tmp-"):
                    st = item.lstat()
                    if (stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode)
                            or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077):
                        raise EvidenceArtifactError("temporary evidence entry is not an owner-owned regular file")
                    found.append(item.relative_to(self.root).as_posix())
        return found

    def find_orphans(self, referenced_payload_refs):
        """List unreferenced published blobs; never deletes or rewrites evidence."""
        if referenced_payload_refs is None:
            referenced = set()
        else:
            if isinstance(referenced_payload_refs, (str, bytes)):
                raise EvidenceArtifactError("referenced payloads must be a collection of refs")
            try:
                referenced = set(referenced_payload_refs)
            except TypeError as exc:
                raise EvidenceArtifactError("referenced payloads must be hashable references") from exc
        base = self.root / "sha256"
        if not (self.root.exists() or self.root.is_symlink()):
            return []
        self._assert_private_directory(self.root, "evidence root")
        if not (base.exists() or base.is_symlink()):
            return []
        self._assert_private_directory(base, "evidence namespace")
        orphans = []
        for prefix in sorted(base.iterdir()):
            self._assert_private_directory(prefix, "evidence digest directory")
            for blob in sorted(prefix.iterdir()):
                if blob.is_symlink() or not blob.is_file():
                    raise EvidenceArtifactError("unexpected evidence payload entry")
                blob_stat = blob.lstat()
                if blob_stat.st_uid != os.getuid() or stat.S_IMODE(blob_stat.st_mode) & 0o077:
                    raise EvidenceArtifactError("evidence payload is not owner-owned and private")
                if blob.name.startswith(".tmp-"):
                    continue
                digest = blob.name
                if prefix.name != digest[:2] or not _HEX.fullmatch(digest):
                    raise EvidenceArtifactError("malformed evidence payload path")
                ref = "sha256:" + digest
                if ref not in referenced:
                    orphans.append(ref)
        return orphans
