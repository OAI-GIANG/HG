"""Fail-closed tests for runtime.production_config (no production paths, no network)."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maep.local_authority_store import LocalRootStore
from maep.native_authority import TrustRootRecord
from runtime import production_config as pc
from runtime import service


class ProductionConfigTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="hg-production-config-")
        self.base = Path(self._temp.name)
        (self.base / "checkout").mkdir()
        self.config = {
            "schema": pc.CONFIG_SCHEMA, "host": "127.0.0.1", "port": 18765,
            "checkout": str(self.base / "checkout"),
            "authority_dir": str(self.base / "authority"),
            "policy_path": str(self.base / "policy.json"),
            "evidence_dir": str(self.base / "evidence"),
            "memory_db": str(self.base / "memory" / "hg.sqlite3"),
            "idempotency_db": str(self.base / "idempotency.sqlite3"),
            "receipts_dir": str(self.base / "receipts"),
        }

    def tearDown(self):
        self._temp.cleanup()

    def write(self, value, *, mode=0o600, raw=None):
        path = self.base / "config.json"
        path.write_text(raw if raw is not None else json.dumps(value), encoding="utf-8")
        path.chmod(mode)
        return str(path)

    def snapshot(self):
        return sorted(str(p.relative_to(self.base)) for p in self.base.rglob("*"))

    def provision_test_root(self):
        # Test-only root in an isolated directory; never a production trust source.
        LocalRootStore(self.config["authority_dir"]).store_active(TrustRootRecord.create(
            root_id="test-root", generation=1, created_at="2026-10-25T00:00:00Z",
            bootstrap_authorization_ref="test:owner", verification_method="test-only",
            verification_material_ref="test://material", policy_change_rule_ref="test://policy",
            evidence_ref="test://evidence"))

    def assert_blocked(self, path, message):
        with patch.dict(os.environ, {pc.CONFIG_ENV: path} if path is not None else {}, clear=True):
            with self.assertRaisesRegex(service.RuntimeStartupError, message):
                pc.create_service()

    def test_missing_or_relative_config_path_blocks(self):
        self.assert_blocked(None, "HG_RUNTIME_CONFIG is required")
        self.assert_blocked("relative/config.json", "absolute path")
        self.assert_blocked(str(self.base / "absent.json"), "unavailable")

    def test_symlink_and_permissive_modes_block(self):
        real = self.write(self.config)
        link = self.base / "link.json"
        link.symlink_to(real)
        self.assert_blocked(str(link), "regular non-symlink")
        self.assert_blocked(self.write(self.config, mode=0o640), "exclude group/other")

    def test_non_strict_json_blocks(self):
        self.assert_blocked(self.write(None, raw='{"schema": 1, "schema": 2}'), "strict JSON")
        self.assert_blocked(self.write(None, raw='{"port": NaN}'), "strict JSON")
        self.assert_blocked(self.write(None, raw="[]"), "keys do not match")

    def test_schema_and_field_validation_blocks(self):
        cases = [
            ({**self.config, "extra": 1}, "keys do not match"),
            ({k: v for k, v in self.config.items() if k != "receipts_dir"}, "keys do not match"),
            ({**self.config, "schema": "other"}, "schema is not supported"),
            ({**self.config, "host": "0.0.0.0"}, "loopback"),
            ({**self.config, "port": True}, "port"),
            ({**self.config, "port": 80}, "port"),
            ({**self.config, "evidence_dir": "relative"}, "evidence_dir must be an absolute path"),
            ({**self.config, "checkout": str(self.base / "missing")}, "checkout is not a directory"),
        ]
        for value, message in cases:
            with self.subTest(message=message):
                self.assert_blocked(self.write(value), message)

    def test_missing_trust_root_blocks_without_creating_state(self):
        path = self.write(self.config)
        before = self.snapshot()
        self.assert_blocked(path, "no active trust root is provisioned")
        self.assertEqual(self.snapshot(), before)

    def test_tampered_trust_root_blocks(self):
        self.provision_test_root()
        root_file = Path(self.config["authority_dir"]) / "active-root.json"
        data = json.loads(root_file.read_text(encoding="utf-8"))
        data["generation"] = 2
        root_file.chmod(0o600)
        root_file.write_text(json.dumps(data), encoding="utf-8")
        self.assert_blocked(self.write(self.config), "trust root is invalid")

    def test_unprovisioned_bindings_block_and_are_all_reported(self):
        self.provision_test_root()
        path = self.write(self.config)
        before = self.snapshot()
        with patch.dict(os.environ, {pc.CONFIG_ENV: path}, clear=True):
            with self.assertRaises(service.RuntimeStartupError) as ctx:
                pc.create_service()
        message = str(ctx.exception)
        for name, _reason in pc.REQUIRED_BINDINGS:
            if name in pc.APPROVED_BINDINGS:
                self.assertNotIn(name, message)
            else:
                self.assertIn(name, message)
        # No Memory database, ledger, evidence or receipt state is created.
        self.assertEqual(self.snapshot(), before)

    def test_registered_bindings_without_composition_still_block(self):
        self.provision_test_root()
        path = self.write(self.config)
        sentinels = {name: object() for name, _reason in pc.REQUIRED_BINDINGS}
        with patch.dict(pc.APPROVED_BINDINGS, sentinels), \
                patch.dict(os.environ, {pc.CONFIG_ENV: path}, clear=True):
            with self.assertRaisesRegex(service.RuntimeStartupError, "composition is not implemented"):
                pc.create_service()

    def test_only_reviewed_bindings_are_registered_in_production_code(self):
        # Exactly the reviewed set; anything else registered here is a defect.
        from memory import AuthorityEvidenceReader
        self.assertEqual(pc.APPROVED_BINDINGS, {"maep022-record-reader": AuthorityEvidenceReader})
        missing = pc.missing_bindings()
        self.assertEqual(len(missing), len(pc.REQUIRED_BINDINGS) - 1)
        self.assertFalse(any(item.startswith("maep022-record-reader") for item in missing))
        for owner_seam in ("approved-policy-source-verifier", "authenticated-session-resolver",
                           "request-authenticator", "authenticated-context-provider",
                           "approved-memory-record-verifier"):
            self.assertTrue(any(item.startswith(owner_seam) for item in missing), owner_seam)

    def test_service_entrypoint_reports_blocker_and_exits_78(self):
        self.provision_test_root()
        path = self.write(self.config)
        stderr, stdout = io.StringIO(), io.StringIO()
        env = {service.FACTORY_ENV: "runtime.production_config:create_service", pc.CONFIG_ENV: path}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(stderr), \
                contextlib.redirect_stdout(stdout):
            result = service.main()
        self.assertEqual(result, service.BLOCKED_EXIT)
        self.assertIn("HG_BLOCKED: production bindings not provisioned", stderr.getvalue())
        self.assertNotIn("HG_RUNTIME_READY", stdout.getvalue())

    def test_real_process_python_m_runtime_service_reports_blocker(self):
        # As `python -m runtime.service` the entry module is __main__; the factory imports
        # runtime modules separately, so the blocker type must be shared to keep its message.
        import subprocess
        import sys
        repo_root = str(Path(pc.__file__).resolve().parents[1])
        path = self.write(self.config)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": repo_root,
               "PYTHONDONTWRITEBYTECODE": "1",
               service.FACTORY_ENV: "runtime.production_config:create_service",
               pc.CONFIG_ENV: path}
        result = subprocess.run([sys.executable, "-u", "-m", "runtime.service"], cwd=repo_root,
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, service.BLOCKED_EXIT)
        self.assertIn("HG_BLOCKED: no active trust root is provisioned", result.stderr)
        self.assertNotIn("HG_RUNTIME_READY", result.stdout)


if __name__ == "__main__":
    unittest.main()
