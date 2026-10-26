"""Direct tests for hg.http_api.planned_write_readback_verifier (AC-READBACK).

A one-at-a-time mutation run (MAEP-022 gate record of 2026-10-26) showed that removing
the content comparison survived the whole main suite: the HTTP tests only exercise
matching content. These tests pin every refusal of the independent read-back.
"""
import os
from pathlib import Path
import tempfile
import unittest

from hg.http_api import planned_write_readback_verifier


def snapshot(*writes):
    return {"plan": [{"tool": "fs.write", "action": "WRITE", "params": {"path": p, "content": c}}
                     for p, c in writes]}


class ReadbackVerifierTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "a.txt").write_text("expected", encoding="utf-8")
        self.verify = planned_write_readback_verifier(self.root)

    def test_matching_content_passes(self):
        ok, reason = self.verify(snapshot(("docs/a.txt", "expected")))
        self.assertTrue(ok, reason)

    def test_different_content_fails(self):
        ok, reason = self.verify(snapshot(("docs/a.txt", "something else")))
        self.assertFalse(ok)
        self.assertIn("differs", reason)

    def test_one_mismatch_among_several_writes_fails(self):
        (self.root / "docs" / "b.txt").write_text("b", encoding="utf-8")
        ok, _ = self.verify(snapshot(("docs/a.txt", "expected"), ("docs/b.txt", "not b")))
        self.assertFalse(ok)

    def test_missing_target_symlink_and_unnormalized_paths_fail(self):
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("expected", encoding="utf-8")
        os.symlink(outside, self.root / "docs" / "out-link.txt")              # points outside the root
        os.symlink(self.root / "docs" / "a.txt", self.root / "docs" / "in-link.txt")   # inside the root
        for path, expected in (("docs/missing.txt", "missing"), ("docs/in-link.txt", "symlink"),
                               ("docs/out-link.txt", "escaped"),
                               ("../outside.txt", "normalized"), ("/etc/passwd", "normalized")):
            with self.subTest(path=path):
                ok, reason = self.verify(snapshot((path, "expected")))
                self.assertFalse(ok)
                self.assertIn(expected, reason)

    def test_no_write_step_fails(self):
        ok, reason = self.verify({"plan": []})
        self.assertFalse(ok)
        self.assertIn("no fs.write", reason)


if __name__ == "__main__":
    unittest.main()
