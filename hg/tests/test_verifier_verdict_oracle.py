"""WS-04 verifier verdict oracle: the parent reads the worker's answer with one meaning.

`IndependentVerifier` runs the pinned worker in a separate process and turns its stdout into
the verification result that can close a task. Here the pinned worker is a stand-in that
prints exact bytes and exits with a chosen code; for every ambiguous or unbound answer the
result must not be PASS, and the call must return promptly:
  - a repeated key ("status" FAIL then PASS) is not read last-value-wins;
  - a PASS for another check, or without a candidate digest/size, does not attest this candidate;
  - NaN/Infinity tokens and non-UTF-8 bytes are refused, not read one way;
  - a worker flooding stdout or stderr is cut off at the output limit, not buffered until exit.
Controls: the canonical answer of each operation still passes; a FAIL stays FAIL.
"""
import hashlib
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from hg.verification.independent import IndependentVerifier

DIGEST = hashlib.sha256(b"x = 1\n").hexdigest()


def _worker_source(stdout=b"", stderr=b"", code=0, sleep=0.0, flood=None):
    lines = ["import sys, time", "sys.stdin.buffer.read()"]
    if flood is not None:
        stream, total = flood
        lines += [f"chunk = b'x' * 65536", f"for _ in range({total // 65536}):",
                  f"    sys.{stream}.buffer.write(chunk)", f"    sys.{stream}.buffer.flush()"]
    lines += [f"sys.stdout.buffer.write({stdout!r})", f"sys.stderr.buffer.write({stderr!r})",
              "sys.stdout.flush()", "sys.stderr.flush()"]
    if sleep:
        lines.append(f"time.sleep({sleep})")
    lines.append(f"raise SystemExit({code})")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _answer(**fields):
    """Members of a worker answer as JSON text; each keyword value is the raw JSON value text."""
    body = {"check": '"PYTHON_SYNTAX"', "status": '"PASS"', "sha256": f'"{DIGEST}"', "bytes": "6",
            "reason": '"ok"'}
    body.update(fields)
    return ",".join(f'"{key}":{value}' for key, value in body.items())


class VerifierVerdictOracleTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.root = self.base / "root"
        self.root.mkdir()
        (self.root / "good.py").write_bytes(b"x = 1\n")

    def _verify(self, source, *, operation="python_syntax", expected=None, timeout_s=5.0, limit=16 * 1024):
        worker = self.base / f"worker-{time.monotonic_ns()}.py"
        worker.write_bytes(source)
        verifier = IndependentVerifier(worker_path=worker, timeout_s=timeout_s, max_output_bytes=limit)
        method = getattr(verifier, "verify_" + operation)
        started = time.monotonic()
        report = method(self.root, "good.py", candidate_ref="candidate-O", expected_sha256=expected)
        return report, time.monotonic() - started

    def _not_pass(self, raw, code=0, **kw):
        report, elapsed = self._verify(_worker_source(stdout=raw, code=code), **kw)
        self.assertNotEqual(report["status"], "PASS", report)
        self.assertLess(elapsed, 5.0)
        return report

    def test_controls_canonical_answers_pass_and_fail_stays_fail(self):
        report, _ = self._verify(_worker_source(stdout=("{" + _answer() + "}").encode()))
        self.assertEqual(report["status"], "PASS", report)
        sqlite = ("{" + _answer(check='"SQLITE_INTEGRITY"') + "}").encode()
        report, _ = self._verify(_worker_source(stdout=sqlite), operation="sqlite_integrity")
        self.assertEqual(report["status"], "PASS", report)
        report, _ = self._verify(_worker_source(stdout=("{" + _answer() + "}\n").encode()), expected=DIGEST)
        self.assertEqual(report["status"], "PASS", report)
        report, _ = self._verify(_worker_source(stdout=("{" + _answer(status='"FAIL"') + "}").encode(), code=1))
        self.assertEqual(report["status"], "FAIL", report)
        # The real pinned worker still passes a valid candidate end to end.
        real = IndependentVerifier(timeout_s=10).verify_python_syntax(
            self.root, "good.py", candidate_ref="candidate-R", expected_sha256=DIGEST)
        self.assertEqual(real["status"], "PASS", real)

    def test_repeated_key_is_not_read_last_value_wins(self):
        cases = {
            "status": '{"status":"FAIL",' + _answer() + "}",
            "check": '{"check":"WORKER",' + _answer()[len('"check":"PYTHON_SYNTAX",'):] + ',"check":"PYTHON_SYNTAX"}',
            "sha256": "{" + _answer() + ',"sha256":"' + DIGEST + '"}',
            "nested": "{" + _answer() + ',"detail":{"a":1,"a":2}}',
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                self._not_pass(raw.encode())

    def test_pass_must_attest_this_operation_and_candidate(self):
        cases = {
            "other_check": "{" + _answer(check='"SQLITE_INTEGRITY"') + "}",
            "no_check": "{" + _answer().replace('"check":"PYTHON_SYNTAX",', "") + "}",
            "no_sha256": "{" + _answer().replace(f'"sha256":"{DIGEST}",', "") + "}",
            "short_sha256": "{" + _answer(sha256='"abc"') + "}",
            "upper_sha256": "{" + _answer(sha256=f'"{DIGEST.upper()}"') + "}",
            "list_sha256": "{" + _answer(sha256=f'["{DIGEST}"]') + "}",
            "no_bytes": "{" + _answer().replace('"bytes":6,', "") + "}",
            "negative_bytes": "{" + _answer(bytes="-1") + "}",
            "bool_bytes": "{" + _answer(bytes="true") + "}",
            "float_bytes": "{" + _answer(bytes="6.0") + "}",
            "list_status": "{" + _answer(status='["PASS"]') + "}",
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                self._not_pass(raw.encode())

    def test_non_standard_numbers_and_bytes_are_refused(self):
        cases = {
            "nan": "{" + _answer(bytes="NaN") + "}",
            "infinity": "{" + _answer(extra="Infinity") + "}",
            "neg_infinity": "{" + _answer(extra="-Infinity") + "}",
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                self._not_pass(raw.encode())
        with self.subTest(name="latin1_byte"):
            self._not_pass(("{" + _answer() + "}").encode().replace(b'"ok"', b'"o\xff"'))
        with self.subTest(name="bom"):
            self._not_pass(b"\xef\xbb\xbf{" + _answer().encode() + b"}")
        with self.subTest(name="trailing_document"):
            self._not_pass(("{" + _answer() + "}{" + _answer() + "}").encode())

    def test_flooding_worker_is_cut_off_at_the_limit(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                source = _worker_source(stdout=("{" + _answer() + "}").encode(),
                                        flood=(stream, 64 * 1024 * 1024), sleep=4.0)
                report, elapsed = self._verify(source, timeout_s=8.0)
                self.assertNotEqual(report["status"], "PASS", report)
                self.assertLess(elapsed, 3.0, f"output was buffered until the worker exited ({elapsed:.1f} s)")


if __name__ == "__main__":
    unittest.main()
