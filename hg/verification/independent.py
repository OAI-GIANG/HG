"""Independent-process deterministic verification for local HG artifacts.

The worker runs as a separate Python process with isolated interpreter flags, but the
same Android UID. Results are candidate-bound observations, not a security sandbox or
proof against a hostile process with the same filesystem privileges.
"""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
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
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        try:
            outcome, stdout, stderr, returncode = _run_bounded(
                [self.python, "-I", "-B", "-c", self._worker_source], payload, cwd=str(root), env=env,
                timeout_s=self.timeout_s, limit=self.max_output_bytes)
        except OSError as exc:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": f"verification worker unavailable: {type(exc).__name__}",
                    "worker_sha256": self.worker_sha256}
        if outcome == "TIMEOUT":
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker timed out", "worker_sha256": self.worker_sha256}
        if outcome == "OVERFLOW":
            return {"check": operation.upper(), "status": "FAIL", "candidate_ref": candidate_ref,
                    "reason": "verification worker output exceeded limit", "worker_sha256": self.worker_sha256}
        try:
            result = _read_answer(stdout)
        except ValueError as exc:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": f"verification worker returned invalid output: {exc} "
                              + stderr[:240].decode("utf-8", errors="replace"),
                    "worker_exit": returncode, "worker_sha256": self.worker_sha256}
        if not isinstance(result.get("status"), str) or result["status"] not in {"PASS", "FAIL", "BLOCKED"}:
            return {"check": operation.upper(), "status": "INCONCLUSIVE", "candidate_ref": candidate_ref,
                    "reason": "verification worker response schema is invalid",
                    "worker_exit": returncode, "worker_sha256": self.worker_sha256}
        if result["status"] == "PASS":
            # A PASS attests this operation on one exact candidate: the right check name,
            # its digest and its size. Anything less is not evidence about this candidate.
            problem = _pass_problem(result, operation.upper())
            if problem:
                result["status"] = "INCONCLUSIVE"
                result["reason"] = problem
        if result.get("status") == "PASS" and returncode != 0:
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
            "worker_exit": returncode,
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


_SHA256_HEX = frozenset("0123456789abcdef")


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"repeated key {key!r}")
        obj[key] = value
    return obj


def _no_constant(token):
    raise ValueError(f"non-standard number {token}")


def _read_answer(raw):
    """One reading of the worker's stdout: strict UTF-8, one JSON object, no repeated key, no NaN."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("output is not UTF-8") from exc
    try:
        result = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_no_constant)
    except json.JSONDecodeError as exc:
        raise ValueError("output is not one JSON document") from exc
    if not isinstance(result, dict):
        raise ValueError("output is not a JSON object")
    return result


def _pass_problem(result, check):
    if result.get("check") != check:
        return "worker PASS names another check"
    digest = result.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or not set(digest) <= _SHA256_HEX:
        return "worker PASS lacks the candidate SHA-256"
    size = result.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return "worker PASS lacks the candidate size"
    return None


def _run_bounded(argv, payload, *, cwd, env, timeout_s, limit):
    """Run argv; return (outcome, stdout, stderr, returncode) with outcome OK, TIMEOUT or OVERFLOW.

    stdout and stderr together are read only up to ``limit`` bytes and only until the deadline;
    past either the worker is killed, so a flooding or stalled worker costs neither memory nor
    time beyond the bounds (subprocess.run would buffer everything until the worker exits).
    """
    deadline = time.monotonic() + timeout_s
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, env=env)
    out, err, total = bytearray(), bytearray(), 0
    outcome = "OK"
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, out)
            selector.register(proc.stderr, selectors.EVENT_READ, err)
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    outcome = "TIMEOUT"
                    break
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > limit:
                        outcome = "OVERFLOW"
                        break
                    key.data.extend(chunk)
                if outcome != "OK":
                    break
        if outcome == "OK":
            try:
                proc.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                outcome = "TIMEOUT"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
    return outcome, bytes(out), bytes(err), proc.returncode


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
