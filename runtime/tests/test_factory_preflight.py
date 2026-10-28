"""runtime.factory_preflight: read-only, reports every production input, fails closed.

Fixture state comes from e2e_fixture_factory inside a temporary directory only; nothing here
is production authority.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import e2e_fixture_factory as fixture
from runtime import factory_preflight
from runtime.owner_approvals import approve_policy
from runtime.session_auth import revoke_session


def _status(report):
    return {item["check"]: item["status"] for item in report["checks"]}


def _tree(base):
    return sorted(str(p) for p in Path(base).rglob("*") if "/.git/" not in str(p))


class FactoryPreflightTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _config_file(self, config, name="runtime-factory.json"):
        path = self.base / name
        path.write_text(json.dumps(config), encoding="utf-8")
        os.chmod(path, 0o600)
        return str(path)

    def _provisioned(self):
        fx = fixture.provision(self.base / "state", port=fixture.free_port())
        config = fx["config"]
        approve_policy(policy_path=config["policy_path"], authority_dir=config["authority_dir"],
                       approval_path=config["policy_approval_path"], approval_ref="fixture:policy-approval")
        return config

    def test_missing_config_blocks_without_further_checks(self):
        report = factory_preflight.preflight(str(self.base / "absent.json"))
        self.assertFalse(report["ready"])
        self.assertEqual(_status(report), {"config": "BLOCKED"})

    def test_reports_every_missing_owner_input_and_writes_nothing(self):
        checkout = self.base / "checkout"
        checkout.mkdir()
        b = str(self.base)
        config = {"schema": "hg-runtime-factory-config-v2", "host": "127.0.0.1", "port": 18799,
                  "checkout": str(checkout), "authority_dir": b + "/authority", "policy_path": b + "/policy.json",
                  "policy_approval_path": b + "/approval.json", "evidence_dir": b + "/evidence",
                  "memory_db": b + "/memory.sqlite3", "idempotency_db": b + "/state/idem.sqlite3",
                  "receipts_dir": b + "/receipts", "session_record": b + "/session.json",
                  "session_revocations": b + "/revocations.json", "file_write_roots": {"w": b + "/w"}}
        path = self._config_file(config)
        before = _tree(self.base)
        report = factory_preflight.preflight(path)
        self.assertEqual(_tree(self.base), before, "preflight must not create anything")
        status = _status(report)
        self.assertFalse(report["ready"])
        self.assertEqual((status["config"], status["bindings"]), ("PASS", "PASS"))
        for name in ("trust-root", "policy-approval", "active-policy", "session", "memory-db",
                     "file-write-roots", "state-dirs", "checkout-readiness"):
            self.assertEqual(status[name], "BLOCKED", name)
        self.assertNotIn("policy-change-rule-ref", status)

    def test_ready_when_every_input_is_provisioned(self):
        config = self._provisioned()
        path = self._config_file(config)
        before = _tree(self.base)
        report = factory_preflight.preflight(path)
        self.assertEqual(_tree(self.base), before)
        self.assertTrue(report["ready"], report)
        status = _status(report)
        self.assertEqual(status["policy-change-rule-ref"], "NOTICE")
        self.assertTrue(all(value in ("PASS", "NOTICE") for value in status.values()), status)

    def test_approval_bound_to_another_policy_version_blocks_the_policy(self):
        config = self._provisioned()
        approval = Path(config["policy_approval_path"])
        record = json.loads(approval.read_text(encoding="utf-8"))
        record["policy_version"] = "not-the-approved-version"
        approval.unlink()
        fd = os.open(approval, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        status = _status(factory_preflight.preflight(self._config_file(config)))
        self.assertEqual(status["policy-approval"], "PASS")
        self.assertEqual(status["active-policy"], "BLOCKED")

    def test_missing_approval_blocks_approval_and_policy(self):
        config = self._provisioned()
        Path(config["policy_approval_path"]).unlink()
        report = factory_preflight.preflight(self._config_file(config))
        status = _status(report)
        self.assertFalse(report["ready"])
        self.assertEqual((status["policy-approval"], status["active-policy"]), ("BLOCKED", "BLOCKED"))

    def test_revoked_session_blocks(self):
        config = self._provisioned()
        session_id = json.loads(Path(config["session_record"]).read_text(encoding="utf-8"))["session_id"]
        revoke_session(revocation_path=config["session_revocations"], session_id=session_id)
        status = _status(factory_preflight.preflight(self._config_file(config)))
        self.assertEqual(status["session"], "BLOCKED")

    def test_cli_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            blocked = factory_preflight.main(["--config", str(self.base / "absent.json")])
        self.assertEqual(blocked, factory_preflight.EXIT_BLOCKED)
        self.assertFalse(json.loads(out.getvalue())["ready"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ready = factory_preflight.main(["--config", self._config_file(self._provisioned())])
        self.assertEqual(ready, 0)


if __name__ == "__main__":
    unittest.main()
