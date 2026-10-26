"""fs.write for runtime.service: rooted, authorization-bound, read-back verified.

MAEP-022 decision EXTEND_EXISTING (gate record:
docs/architecture/MAEP022_GATE_RECORD_FS_WRITE_ACCEPTANCE_20261026.md). The effect
semantics are those of the deployed `hg serve` adapter (`hg/tools/gateway.py`
LocalFileWriteAdapter on main): relative POSIX paths confined to one root, no `..`,
atomic temp-file + fsync + replace, SHA-256 of the content as the effect identity,
idempotent replace, reconcile() against live state. They are expressed in the branch
contract (`tools_automation.contracts.ToolAdapter`) and checked again at the point
of effect, independently of BrainOrchestrator:

* the authorization must be a NativePolicyEngine ALLOW for exactly this action,
  resource and task, unexpired, whose request digest equals the digest of the very
  request handed to the adapter (so path and content are bound to the decision);
* the resource must be `file:<relative path>` of the requested path, inside one of
  the request's `file:` scope prefixes;
* invalid input is reported as FAILURE with no effect attempted; anything that can
  fail after the write started is left to the coordinator as UNKNOWN, and a written
  file whose read-back digest differs is reported UNKNOWN, never SUCCESS.

Standard library only. The adapter holds no credentials and touches nothing outside
its root.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any

from maep.native_authority import AuthorizationResult, Decision, _digest
from tools_automation.contracts import AdapterOutcome

MAX_CONTENT_BYTES = 1 << 20
FILE_PREFIX = "file:"


class AdapterInputError(ValueError):
    """The request cannot be executed; nothing was attempted."""


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class RootedFileWriteAdapter:
    name = "fs.write"
    action = "WRITE"
    idempotent = True          # atomic replace with the same content yields the same state
    timeout_s = 10.0           # coordinator stops waiting after this; the outcome is then UNKNOWN

    def __init__(self, root: str | Path):
        root_path = Path(root).expanduser()
        if not root_path.is_absolute() or not root_path.is_dir() or root_path.is_symlink():
            raise AdapterInputError("adapter root must be an existing absolute, non-symlink directory")
        self.root = root_path.resolve()

    def __repr__(self):
        return f"RootedFileWriteAdapter(root={str(self.root)!r})"

    # -- path confinement (same rules as main's _RootedFileAdapter) --------------------
    def relative(self, raw: Any) -> tuple[str, Path]:
        if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
            raise AdapterInputError("path must be a non-empty relative POSIX path")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
            raise AdapterInputError("path must be relative, inside the root, without '..'")
        cursor = self.root
        for part in path.parts:            # no symlink anywhere on the path (as main's read-back)
            cursor = cursor / part
            if cursor.is_symlink():
                raise AdapterInputError("path contains a symlink")
        full = (self.root / path).resolve()
        if full == self.root or self.root not in full.parents:
            raise AdapterInputError("path escapes the adapter root")
        return path.as_posix(), full

    def _check(self, request: Any, authorization: Any) -> tuple[str, Path, bytes]:
        if not isinstance(request, dict):
            raise AdapterInputError("request must be an object")
        params = request.get("params")
        if not isinstance(params, dict) or set(params) != {"path", "content"} or not isinstance(params["content"], str):
            raise AdapterInputError("params must be exactly {path, content} with string content")
        data = params["content"].encode("utf-8")
        if len(data) > MAX_CONTENT_BYTES:
            raise AdapterInputError("content exceeds the adapter size limit")
        rel, full = self.relative(params["path"])
        if request.get("action") != self.action or request.get("resource") != FILE_PREFIX + rel:
            raise AdapterInputError("request action/resource does not match the planned file write")
        scope = request.get("scope")
        if not isinstance(scope, list) or not any(
                isinstance(item, str) and item.startswith(FILE_PREFIX)
                and (rel == item[len(FILE_PREFIX):].rstrip("/")
                     or rel.startswith(item[len(FILE_PREFIX):].rstrip("/") + "/"))
                for item in scope):
            raise AdapterInputError("path is outside the requested file scope")
        if (not isinstance(authorization, AuthorizationResult) or authorization.decision is not Decision.ALLOW
                or authorization.action != self.action or authorization.resource != request["resource"]
                or authorization.task_ref != request.get("task_ref")
                or authorization.request_digest != _digest(request)):
            raise AdapterInputError("authorization does not bind this exact request")
        try:
            expires = datetime.fromisoformat(str(authorization.expires_at).replace("Z", "+00:00"))
        except ValueError:
            raise AdapterInputError("authorization expiry is invalid") from None
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise AdapterInputError("authorization has expired")
        return rel, full, data

    def execute(self, *, request: dict[str, Any], authorization: Any, idempotency_key: str) -> dict[str, Any]:
        try:
            rel, full, data = self._check(request, authorization)
        except AdapterInputError as exc:
            return {"outcome": AdapterOutcome.FAILURE.value, "effect": "NONE", "reason": str(exc)}
        # From here on an exception may leave an effect behind: the coordinator records UNKNOWN.
        full.parent.mkdir(parents=True, exist_ok=True)
        if full.parent.resolve() != full.parent or (self.root not in full.parent.parents and full.parent != self.root):
            raise RuntimeError("parent directory resolved outside the root after creation")
        fd, tmp = tempfile.mkstemp(dir=str(full.parent), prefix=".hg-fswrite-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, full)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        digest = _sha256(data)
        observed = _sha256(full.read_bytes())
        if observed != digest:
            return {"outcome": AdapterOutcome.UNKNOWN.value, "idempotent": True,
                    "reason": "read-back digest differs from the written content", "path": rel}
        return {"outcome": AdapterOutcome.SUCCESS.value, "idempotent": True, "provider_ref": digest,
                "task_ref": request["task_ref"], "path": rel, "bytes": len(data)}

    def intent(self, request: dict[str, Any]) -> dict[str, Any]:
        params = request["params"]
        return {"path": self.relative(params["path"])[0], "sha256": _sha256(params["content"].encode("utf-8"))}

    def reconcile(self, intent: dict[str, Any]) -> str:
        """Live-state check for an UNKNOWN outcome: APPLIED, NOT_APPLIED or UNKNOWN."""
        try:
            _rel, full = self.relative(intent["path"])
            expected = intent["sha256"]
        except (AdapterInputError, KeyError, TypeError):
            return "UNKNOWN"
        try:
            return "APPLIED" if full.is_file() and _sha256(full.read_bytes()) == expected else "NOT_APPLIED"
        except OSError:
            return "UNKNOWN"
