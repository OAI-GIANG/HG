"""WS-04 false-accept oracle: AC-READBACK compares the exact bytes on disk.

`planned_write_readback_verifier` is the acceptance verifier of the production service
(`hg serve`, AC-READBACK). The fs.write adapter writes `content.encode("utf-8")` byte for
byte, so the independent read-back must compare those bytes. Reading in text mode applies
universal-newline translation: a file holding CRLF or a lone CR then reads back as LF.

Cases run through the HG runtime path (orchestrator -> gateway -> adapter -> AcceptanceGate):
- a file whose bytes differ from the plan only in line endings is never accepted;
- a correct write of content containing CR closes CLOSED_VERIFIED (it used to fail);
and directly against the verifier for bounded reads and malformed planned content.
"""
import os
from pathlib import Path
import time
import unittest

from hg.http_api import planned_write_readback_verifier
from hg.tests.support import TempDirMixin, grant, make_task, write_step

DEADLINE_S = 5.0


def snapshot(path, content):
    return {"plan": [{"tool": "fs.write", "action": "WRITE", "params": {"path": path, "content": content}}]}


class ReadbackBytesRuntimeOracle(TempDirMixin):
    def run_task(self, content, *, tamper=None):
        real = planned_write_readback_verifier(self.root)

        def verifier(snap):
            if tamper is not None:            # a writer between the effect and the read-back
                (self.root / "out/hello.txt").write_bytes(tamper)
            return real(snap)

        rt = self.build([grant()], verifiers={"AC-READBACK": verifier})
        started = time.monotonic()
        final = rt.orch.execute_task(make_task(criteria=("AC-READBACK",)), [write_step(content=content)])
        self.assertLess(time.monotonic() - started, DEADLINE_S)
        return final["task"]["state"]

    def test_line_ending_rewrite_is_never_accepted(self):
        cases = {
            "LF planned, CRLF on disk": ("a\nb\n", b"a\r\nb\r\n"),
            "LF planned, CR on disk": ("a\nb", b"a\rb"),
            "CRLF planned, LF on disk": ("a\r\nb", b"a\nb"),
            "CR planned, LF on disk": ("a\rb", b"a\nb"),
            "trailing CR appended": ("line", b"line\r"),
        }
        for name, (planned, on_disk) in cases.items():
            with self.subTest(name):
                self._tmp.cleanup()
                os.makedirs(self.tmp)
                self.assertNotEqual(self.run_task(planned, tamper=on_disk), "CLOSED_VERIFIED")

    def test_exact_write_with_carriage_returns_is_accepted(self):
        for name, content in {"CR": "a\rb", "CRLF": "a\r\nb\r\n", "mixed": "x\ry\nz\r\n", "LF": "a\nb"}.items():
            with self.subTest(name):
                self._tmp.cleanup()
                os.makedirs(self.tmp)
                self.assertEqual(self.run_task(content), "CLOSED_VERIFIED")
                self.assertEqual((self.root / "out/hello.txt").read_bytes(), content.encode("utf-8"))


class ReadbackBytesDirectOracle(TempDirMixin):
    def setUp(self):
        super().setUp()
        (self.root / "out").mkdir(parents=True)
        self.target = self.root / "out/a.txt"
        self.verify = planned_write_readback_verifier(self.root)

    def test_longer_file_with_planned_prefix_fails(self):
        self.target.write_bytes(b"expected" + b"x" * (1 << 20))
        ok, reason = self.verify(snapshot("out/a.txt", "expected"))
        self.assertFalse(ok)
        self.assertIn("differs", reason)

    def test_non_string_planned_content_fails(self):
        self.target.write_bytes(b"1")
        for content in (None, 1, b"1", ["1"]):
            with self.subTest(content=content):
                ok, _ = self.verify(snapshot("out/a.txt", content))
                self.assertFalse(ok)

    def test_lone_surrogate_planned_content_fails_without_raising(self):
        self.target.write_bytes(b"x")
        ok, _ = self.verify(snapshot("out/a.txt", "\ud800"))
        self.assertFalse(ok)

    def test_fifo_target_fails_without_blocking(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs on this platform")
        os.mkfifo(self.target)
        started = time.monotonic()
        ok, _ = self.verify(snapshot("out/a.txt", "x"))
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - started, DEADLINE_S)

    def test_exact_bytes_control(self):
        self.target.write_bytes("xin chào\r\n".encode("utf-8"))
        ok, reason = self.verify(snapshot("out/a.txt", "xin chào\r\n"))
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
