"""Release packaging is deterministic and bound to exact Git tree/blob bytes."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hg.release import ReleaseError, build_release, main, verify_archive, verify_root
from hg.tests.release_helpers import make_tiny_release


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-release-test-")
        self.root = Path(self.temp.name)
        self.fixture = make_tiny_release(self.root / "first")

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
