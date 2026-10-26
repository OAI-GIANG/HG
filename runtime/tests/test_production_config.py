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
            "policy_approval_path": str(self.base / "authority" / "policy-approval.json"),
            "file_write_roots": {"sandbox": str(self.base / "write-root")},
            "evidence_dir": str(self.base / "evidence"),
            "memory_db": str(self.base / "memory" / "hg.sqlite3"),
            "idempotency_db": str(self.base / "idempotency.sqlite3"),
            "receipts_dir": str(self.base / "receipts"),
            "session_record": str(self.base / "session" / "session.json"),
            "session_revocations": str(self.base / "session" / "revocations.json"),
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
        self.assertIn("could not be constructed", message)
        # No Memory database, ledger, evidence or receipt state is created.
        self.assertEqual(self.snapshot(), before)

    def test_registered_bindings_that_break_their_contracts_still_block(self):
        self.provision_test_root()
        path = self.write(self.config)
        before = self.snapshot()
        builders = {name: (lambda config: object()) for name, _reason in pc.REQUIRED_BINDINGS}
        with patch.dict(pc.APPROVED_BINDINGS, builders), \
                patch.dict(os.environ, {pc.CONFIG_ENV: path}, clear=True):
            with self.assertRaisesRegex(service.RuntimeStartupError, "contract is invalid|not callable"):
                pc.create_service()
        self.assertEqual(self.snapshot(), before)          # no ledger/state created

    def test_failing_binding_builder_blocks_with_its_name(self):
        self.provision_test_root()
        path = self.write(self.config)

        def broken(config):
            raise ValueError("secret-looking detail must not leak")
        builders = {name: (lambda config: object()) for name, _reason in pc.REQUIRED_BINDINGS}
        builders["authenticated-session-resolver"] = broken
        with patch.dict(pc.APPROVED_BINDINGS, builders), \
                patch.dict(os.environ, {pc.CONFIG_ENV: path}, clear=True):
            with self.assertRaises(service.RuntimeStartupError) as ctx:
                pc.create_service()
        self.assertIn("authenticated-session-resolver could not be constructed (ValueError)", str(ctx.exception))
        self.assertNotIn("secret-looking", str(ctx.exception))

    def test_only_reviewed_bindings_are_registered_in_production_code(self):
        # Exactly the reviewed set; anything else registered here is a defect.
        from memory import AuthorityEvidenceReader
        from runtime.session_auth import TokenSessionSource, issue_session
        self.assertEqual(set(pc.APPROVED_BINDINGS), {
            "maep022-record-reader", "approved-policy-source-verifier",
            "approved-memory-record-verifier", "tool-adapter-registry", "acceptance-provider",
            "authenticated-session-resolver", "request-authenticator", "authenticated-context-provider"})
        reader = pc.APPROVED_BINDINGS["maep022-record-reader"](self.config)
        self.assertIsInstance(reader, AuthorityEvidenceReader)
        self.assertEqual(reader.path, Path(self.config["memory_db"]))
        issue_session(session_path=self.config["session_record"], token_path=self.base / "session" / "token",
                      revocation_path=self.config["session_revocations"], principal_id="STT", valid_days=1,
                      capabilities=["READ"], resource_scopes=["r"], allowed_scopes=["s"])
        source = pc.APPROVED_BINDINGS["authenticated-session-resolver"](self.config)
        self.assertIsInstance(source, TokenSessionSource)
        self.assertEqual(pc.APPROVED_BINDINGS["authenticated-context-provider"](self.config)(),
                         source.authenticated_context())
        self.assertTrue(callable(pc.APPROVED_BINDINGS["request-authenticator"](self.config)))
        missing = pc.missing_bindings()
        self.assertEqual(missing, [])

    def test_service_entrypoint_reports_blocker_and_exits_78(self):
        self.provision_test_root()
        path = self.write(self.config)
        stderr, stdout = io.StringIO(), io.StringIO()
        env = {service.FACTORY_ENV: "runtime.production_config:create_service", pc.CONFIG_ENV: path}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(stderr), \
                contextlib.redirect_stdout(stdout):
            result = service.main()
        self.assertEqual(result, service.BLOCKED_EXIT)
        self.assertIn("HG_BLOCKED: production binding", stderr.getvalue())
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
