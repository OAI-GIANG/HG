"""Independent-process deterministic verification for local HG artifacts.

The worker runs as a separate Python process with isolated interpreter flags, but the
same Android UID. Results are candidate-bound observations, not a security sandbox or
proof against a hostile process with the same filesystem privileges.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


class IndependentVerificationError(RuntimeError):
    pass


# The pinned worker source is passed to the interpreter as one argv string (``-c``),
# so it must fit well under Linux MAX_ARG_STRLEN (128 KiB) and contain no NUL.
MAX_WORKER_BYTES = 64 * 1024


class IndependentVerifier:
    def __init__(self, *, python=sys.executable, worker_path=None, timeout_s=7.0, max_output_bytes=16 * 1024):
        if not isinstance(python, str) or not python:
            raise IndependentVerificationError("python executable must be a non-empty path")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise IndependentVerificationError("timeout_s must be positive")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes < 256:
            raise IndependentVerificationError("max_output_bytes is invalid")
        self.python = python
        self.worker_path = Path(worker_path or Path(__file__).with_name("worker.py")).resolve(strict=True)
        self.timeout_s = float(timeout_s)
        self.max_output_bytes = max_output_bytes
        raw = self.worker_path.read_bytes()
        if len(raw) > MAX_WORKER_BYTES:
            raise IndependentVerificationError("verification worker is too large to pin")
        if b"\0" in raw:
            raise IndependentVerificationError("verification worker contains a NUL byte")
        try:
            # Run exactly these bytes: executing worker_path would re-read the file
            # after the digest check, so a swap in between would run unpinned code.
            self._worker_source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IndependentVerificationError("verification worker is not UTF-8") from exc
        self.worker_sha256 = hashlib.sha256(raw).hexdigest()

    def _run(self, operation, root, relative_path, *, candidate_ref, expected_sha256=None):
        if not isinstance(candidate_ref, str) or not candidate_ref.strip():
            raise IndependentVerificationError("candidate_ref is required")
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise IndependentVerificationError("verification root must be a directory")
        try:
            current_worker = self.worker_path.read_bytes()
        except OSError:
            current_worker = b""
        if hashlib.sha256(current_worker).hexdigest() != self.worker_sha256:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker changed after it was pinned", "worker_sha256": self.worker_sha256}
        request = {"operation": operation, "root": str(root), "path": relative_path}
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "LANG": "C"}
        try:
            completed = subprocess.run(
                [self.python, "-I", "-B", "-c", self._worker_source],
                input=json.dumps(request, separators=(",", ":")),
                text=True, encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(root), env=env, timeout=self.timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker timed out", "worker_sha256": self.worker_sha256}
        except OSError as exc:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": f"verification worker unavailable: {type(exc).__name__}",
                    "worker_sha256": self.worker_sha256}
        stdout = completed.stdout or ""
        if len(stdout.encode("utf-8", errors="replace")) > self.max_output_bytes:
            return {"check": operation.upper(), "status": "FAIL", "candidate_ref": candidate_ref,
                    "reason": "verification worker output exceeded limit", "worker_sha256": self.worker_sha256}
        try:
            result = json.loads(stdout)
        except (TypeError, ValueError):
            stderr = (completed.stderr or "")[:240]
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker returned invalid output " + stderr,
                    "worker_exit": completed.returncode, "worker_sha256": self.worker_sha256}
        if not isinstance(result, dict) or result.get("status") not in {"PASS", "FAIL", "BLOCKED"}:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker response schema is invalid",
                    "worker_exit": completed.returncode, "worker_sha256": self.worker_sha256}
        if result.get("status") == "PASS" and completed.returncode != 0:
            result["status"] = "INCONCLUSIVE"
            result["reason"] = "worker reported PASS with a non-zero exit code"
        if expected_sha256 is not None:
            observed = result.get("sha256")
            if observed != expected_sha256:
                result["status"] = "FAIL"
                result["reason"] = "candidate content hash does not match the expected digest"
        result.update({
            "candidate_ref": candidate_ref,
            "worker_sha256": self.worker_sha256,
            "verification_boundary": "separate-process-same-uid-not-an-os-sandbox",
            "worker_exit": completed.returncode,
        })
        return result

    def verify_python_syntax(self, root, relative_path, *, candidate_ref, expected_sha256=None):
        return self._run("python_syntax", root, relative_path, candidate_ref=candidate_ref,
                         expected_sha256=expected_sha256)

    def verify_sqlite_integrity(self, root, relative_path, *, candidate_ref, expected_sha256=None):
        # Without expected_sha256 the result attests structure only: integrity_check
        # does not detect altered row content or appended bytes.
        return self._run("sqlite_integrity", root, relative_path, candidate_ref=candidate_ref,
                         expected_sha256=expected_sha256)


def python_syntax_verifier(root, relative_path, expected_sha256, *, verifier=None):
    """Build an Orchestrator-compatible verifier for one exact source artifact."""
    engine = verifier or IndependentVerifier()
    def check(snapshot):
        result = (snapshot.get("result") or {})
        candidate_ref = result.get("candidate_ref")
        report = engine.verify_python_syntax(
            root, relative_path, candidate_ref=candidate_ref,
            expected_sha256=expected_sha256,
        )
        return report
    check.__name__ = "independent_process_python_syntax"
    check.__hg_verification_boundary__ = "separate-process-same-uid-not-an-os-sandbox"
    return check
