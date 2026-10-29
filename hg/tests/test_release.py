"""Release packaging is deterministic and bound to exact Git tree/blob bytes."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.release import ReleaseError, build_release, main, seal_root, verify_archive, verify_root
from hg.tests.release_helpers import make_tiny_release


def _restore_write_access(path):
    path = Path(path)
    if not path.exists():
        return
    for p in [path, *path.rglob("*")]:
        if not p.is_symlink():
            p.chmod(p.stat().st_mode | 0o200)


def _env_without_bytecode_guard():
    return {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-release-test-")
        self.root = Path(self.temp.name)
        self.fixture = make_tiny_release(self.root / "first")

    def tearDown(self):
        _restore_write_access(self.root)
        self.temp.cleanup()

    def test_release_is_deterministic_for_same_commit(self):
        second = build_release(
            self.fixture["repo"], self.fixture["commit"],
            self.root / "second.tar.gz", self.root / "second-manifest.json")
        self.assertEqual((self.root / "second.tar.gz").read_bytes(), self.fixture["archive"].read_bytes())
        self.assertEqual(second["release_id"], self.fixture["doc"]["release_id"])
        self.assertEqual(second["tree"], self.fixture["doc"]["tree"])

    def test_archive_verifies_against_git_and_installed_root(self):
        report = verify_archive(self.fixture["repo"], self.fixture["archive"], self.fixture["manifest"])
        self.assertEqual(report["result"], "VERIFIED")
        self.assertEqual(report["commit"], self.fixture["commit"])
        self.assertEqual(report["files_checked"], len(self.fixture["doc"]["files"]))
        installed = verify_root(self.fixture["root"], self.fixture["manifest"], self.fixture["doc"]["release_id"])
        self.assertEqual(installed["result"], "VERIFIED")
        self.assertTrue((self.fixture["root"] / "bin/check").stat().st_mode & 0o111)

    def test_archive_tampering_is_detected(self):
        target = self.root / "tampered.tar.gz"
        target.write_bytes(self.fixture["archive"].read_bytes() + b"tamper")
        with self.assertRaisesRegex(ReleaseError, "archive SHA-256 mismatch"):
            verify_archive(self.fixture["repo"], target, self.fixture["manifest"])

    def test_installed_source_tampering_and_extra_file_are_detected(self):
        target = self.fixture["root"] / "README.md"
        original = target.read_text()
        target.write_text(original + "altered\n")
        with self.assertRaisesRegex(ReleaseError, "file integrity mismatch"):
            verify_root(self.fixture["root"], self.fixture["manifest"], self.fixture["doc"]["release_id"])
        target.write_text(original)
        (self.fixture["root"] / "unexpected.py").write_text("pass\n")
        with self.assertRaisesRegex(ReleaseError, "file set does not match"):
            verify_root(self.fixture["root"], self.fixture["manifest"], self.fixture["doc"]["release_id"])

    def test_manifest_digest_is_checked(self):
        doc = json.loads(self.fixture["manifest"].read_text())
        doc["commit"] = "0" * 40
        bad = self.root / "bad-manifest.json"
        bad.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ReleaseError, "manifest digest mismatch"):
            verify_root(self.fixture["root"], bad, self.fixture["doc"]["release_id"])

    def test_duplicate_manifest_keys_are_rejected(self):
        bad = self.root / "duplicate.json"
        bad.write_text('{"schema":"x","schema":"y"}')
        with self.assertRaisesRegex(ReleaseError, "unreadable or invalid"):
            verify_root(self.fixture["root"], bad, "0" * 64)

    def test_extract_cli_and_verify_root(self):
        target = self.root / "cli-release-root"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["extract", "--archive", str(self.fixture["archive"]),
                         "--destination", str(target)])
        self.assertEqual(code, 0)
        self.assertIn("EXTRACTED", out.getvalue())
        report = verify_root(target, self.fixture["manifest"], self.fixture["doc"]["release_id"])
        self.assertEqual(report["result"], "VERIFIED")

    def test_invalid_commit_reference_is_rejected(self):
        with self.assertRaisesRegex(ReleaseError, "full lowercase 40-character"):
            build_release(self.fixture["repo"], "--help",
                          self.root / "no.tar.gz", self.root / "no.json")

    def test_extract_rejects_symlink_destination(self):
        target = self.root / "target-dir"
        target.mkdir()
        link = self.root / "release-link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ReleaseError, "must not be a symlink"):
            from hg.release import extract_archive
            extract_archive(self.fixture["archive"], link)

    def test_verify_root_rejects_symlink(self):
        link = self.root / "release-root-link"
        link.symlink_to(self.fixture["root"], target_is_directory=True)
        with self.assertRaisesRegex(ReleaseError, "not a symlink"):
            verify_root(link, self.fixture["manifest"], self.fixture["doc"]["release_id"])


class SealedReleaseTests(unittest.TestCase):
    IMPORT = "import sys; sys.path.insert(0, '.'); import hg.runtime"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-seal-test-")
        self.root = Path(self.temp.name)
        self.fixture = make_tiny_release(self.root / "first")
        self.release_root = self.fixture["root"]
        self.manifest = self.fixture["manifest"]
        self.release_id = self.fixture["doc"]["release_id"]

    def tearDown(self):
        _restore_write_access(self.root)
        self.temp.cleanup()

    def _tree(self):
        return sorted(p.relative_to(self.release_root).as_posix() for p in self.release_root.rglob("*"))

    def test_unsealed_import_without_dont_write_bytecode_breaks_verify(self):
        # Reproduces the original failure: a plain import from an installed root writes bytecode.
        subprocess.run([sys.executable, "-c", self.IMPORT], cwd=str(self.release_root),
                       check=True, env=_env_without_bytecode_guard())
        self.assertTrue(any(self.release_root.rglob("*.pyc")))
        with self.assertRaisesRegex(ReleaseError, "file set does not match"):
            verify_root(self.release_root, self.manifest, self.release_id)

    def test_sealed_release_verifies_and_refuses_owner_writes(self):
        report = seal_root(self.release_root)
        self.assertEqual(report["result"], "SEALED")
        self.assertEqual(verify_root(self.release_root, self.manifest, self.release_id)["result"], "VERIFIED")
        if os.geteuid() == 0:
            self.skipTest("root bypasses directory write permissions")
        with self.assertRaises(PermissionError):
            (self.release_root / "hg" / "new.py").write_text("x", encoding="utf-8")
        with self.assertRaises(PermissionError):
            (self.release_root / "README.md").write_text("changed", encoding="utf-8")
        self.assertTrue((self.release_root / "bin/check").stat().st_mode & 0o111)

    def test_sealed_import_without_dont_write_bytecode_leaves_tree_unchanged(self):
        seal_root(self.release_root)
        before = self._tree()
        for _ in range(3):
            subprocess.run([sys.executable, "-c", self.IMPORT], cwd=str(self.release_root),
                           check=True, env=_env_without_bytecode_guard())
        self.assertEqual(self._tree(), before)
        self.assertFalse(list(self.release_root.rglob("*.pyc")))
        self.assertEqual(verify_root(self.release_root, self.manifest, self.release_id)["result"], "VERIFIED")

    def test_verify_still_rejects_injected_bytecode_after_seal(self):
        seal_root(self.release_root)
        _restore_write_access(self.release_root)
        (self.release_root / "hg" / "__pycache__").mkdir()
        (self.release_root / "hg" / "__pycache__" / "runtime.cpython-312.pyc").write_bytes(b"x")
        with self.assertRaisesRegex(ReleaseError, "file set does not match"):
            verify_root(self.release_root, self.manifest, self.release_id)

    def test_seal_rejects_symlink_inside_release_without_changing_modes(self):
        (self.release_root / "link").symlink_to(self.release_root / "README.md")
        before = (self.release_root / "README.md").stat().st_mode
        with self.assertRaisesRegex(ReleaseError, "symlink in installed release"):
            seal_root(self.release_root)
        self.assertEqual((self.release_root / "README.md").stat().st_mode, before)

    def test_seal_rejects_symlink_root(self):
        link = self.root / "root-link"
        link.symlink_to(self.release_root)
        with self.assertRaisesRegex(ReleaseError, "real directory"):
            seal_root(link)


if __name__ == "__main__":
    unittest.main()
