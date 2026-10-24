"""Service preflight and local secret/lock contracts fail closed."""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maep.authority.canonical_source import CanonicalManifest
from maep.tests.test_canonical_source import FakeGitHub
from hg.release import ReleaseError
from hg.service import (
    CONFIG_SCHEMA, BLOCKED_EXIT, ServiceConfigError, _open_writer_lock,
    load_config, read_token, run, verify_config,
)
from hg.tests.release_helpers import make_tiny_release


class ServiceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-service-test-")
        self.root = Path(self.temp.name)
        self.release = make_tiny_release(self.root / "release")
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.token_file = self.root / "service.token"
        self.token_file.write_text("a-very-long-test-token-that-is-not-a-secret\n", encoding="ascii")
        self.token_file.chmod(0o600)
        self.config_file = self.root / "service.json"
        self.config = {
            "schema": CONFIG_SCHEMA, "host": "127.0.0.1", "port": 18765,
            "state_dir": str(self.state), "token_file": str(self.token_file),
            "release_root": str(self.release["root"]), "release_manifest": str(self.release["manifest"]),
            "release_id": self.release["doc"]["release_id"], "max_body_bytes": 65536,
        }
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self):
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        self.config_file.chmod(0o600)

    def test_strict_config_and_release_preflight_pass(self):
        config = load_config(self.config_file)
        self.assertEqual(config["schema"], CONFIG_SCHEMA)
        report = verify_config(config)
        self.assertEqual(report["release"]["result"], "VERIFIED")
        self.assertGreaterEqual(report["token_bytes"], 32)

    def test_config_duplicate_keys_and_unknown_keys_are_rejected(self):
        self.config_file.write_text('{"schema":"hg-runtime-service-config-v1","schema":"bad"}')
        self.config_file.chmod(0o600)
        with self.assertRaisesRegex(ServiceConfigError, "strict UTF-8 JSON"):
            load_config(self.config_file)
        self.config["unexpected"] = True
        self.write_config()
        with self.assertRaisesRegex(ServiceConfigError, "keys must match"):
            load_config(self.config_file)

    def test_config_file_must_be_private_and_owned(self):
        self.config_file.chmod(0o644)
        with self.assertRaisesRegex(ServiceConfigError, "group/other"):
            load_config(self.config_file)

    def test_token_file_must_be_exactly_mode_600(self):
        self.token_file.chmod(0o644)
        with self.assertRaisesRegex(ServiceConfigError, "mode 600"):
            read_token(self.token_file)
        self.token_file.chmod(0o600)
        self.token_file.write_text("short\n")
        with self.assertRaisesRegex(ServiceConfigError, "at least 32"):
            read_token(self.token_file)

    def test_state_directory_must_not_be_shared(self):
        self.state.chmod(0o755)
        with self.assertRaisesRegex(ServiceConfigError, "group/other"):
            verify_config(load_config(self.config_file))
        self.state.chmod(0o700)

    def test_single_writer_lock_rejects_second_owner(self):
        first = _open_writer_lock(self.state)
        try:
            with self.assertRaisesRegex(ServiceConfigError, "another HG service"):
                _open_writer_lock(self.state)
        finally:
            os.close(first)
        second = _open_writer_lock(self.state)
        os.close(second)

    def test_wrong_release_id_fails_closed(self):
        self.config["release_id"] = "0" * 64
        self.write_config()
        with self.assertRaisesRegex(ReleaseError, "configured release_id"):
            verify_config(load_config(self.config_file))

    def test_release_root_symlink_is_rejected(self):
        link = self.root / "release-root-link"
        link.symlink_to(self.release["root"], target_is_directory=True)
        self.config["release_root"] = str(link)
        self.write_config()
        with self.assertRaisesRegex(ServiceConfigError, "real owner-owned"):
            verify_config(load_config(self.config_file))

    def test_read_only_preflight_loads_live_main_anchor_without_binding_port(self):
        gh = FakeGitHub()
        authority = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0)
        stdout = io.StringIO()
        with patch.object(CanonicalManifest, "from_github", return_value=authority):
            with contextlib.redirect_stdout(stdout):
                result = run(self.config_file, check=True)
        self.assertEqual(result, 0)
        self.assertIn("PREFLIGHT_PASS", stdout.getvalue())
        self.assertEqual(len(gh.urls), 2)
        self.assertFalse((self.state / ".writer.lock").exists())

    def test_unavailable_trust_root_blocks_preflight(self):
        gh = FakeGitHub(files={})
        authority = CanonicalManifest.from_github(http_get=gh.get, max_age_s=0)
        stderr = io.StringIO()
        with patch.object(CanonicalManifest, "from_github", return_value=authority):
            with contextlib.redirect_stderr(stderr):
                result = run(self.config_file, check=True)
        self.assertEqual(result, BLOCKED_EXIT)
        self.assertIn("HG_BLOCKED", stderr.getvalue())
        self.assertNotIn("Bearer", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
