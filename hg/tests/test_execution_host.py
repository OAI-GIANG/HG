"""Execution Host audit-only application boundary tests.

These tests do not claim OS isolation or complete mediation. They verify only
that HG's in-process AUDIT_ONLY assembly fails closed and exposes read actions.
"""
import unittest

from maep.core import MAEPError
from hg.runtime import AUDIT_ONLY_PRINCIPAL, build_runtime
from maep.authority.canonical_source import CanonicalManifest
from hg.tools.gateway import LocalFileReadAdapter, LocalFileWriteAdapter, ToolAdapter
from hg.tests.support import TempDirMixin, content_verifier, grant, make_task


def fake_authority():
    document = {
        "trust_root": "main",
        "policy_version": "MAEP-1.1.0",
        "grants": [{
            "principal": AUDIT_ONLY_PRINCIPAL,
            "actions": ["maep.read"],
            "scope": ["repo:OAI-GIANG/HG", "file:out/"],
            "issued_at": "2026-10-23T00:00:00Z",
            "expires_at": "2027-01-21T00:00:00Z",
        }],
    }
    return CanonicalManifest(
        lambda: (document, {"commit": "fixture-commit", "fingerprint": "fixture-fingerprint"}),
        max_age_s=0,
    )


class MisdeclaredReadAdapter(ToolAdapter):
    name = "fake.read-but-mutates"
    version = "test"
    action = "READ"
    params_schema = {}

    def resource_for(self, params):
        return "file:out/side-effect.txt"

    def in_scope(self, params, scope):
        return True

    def intent(self, params):
        return {}

    def _perform(self, params):
        raise AssertionError("this adapter must never be invoked")


class AuditOnlyRuntimeTests(TempDirMixin):
    def build_audit(self, **kwargs):
        grants = kwargs.pop("grants", [])
        return build_runtime(
            self.workdir, grants, principal=AUDIT_ONLY_PRINCIPAL, mode="AUDIT_ONLY",
            authority=fake_authority(), clock=self.clock, **kwargs
        )

    def test_audit_only_requires_fixed_principal(self):
        with self.assertRaisesRegex(MAEPError, "HG_AUDIT"):
            build_runtime(self.workdir, [], principal="STT", mode="AUDIT_ONLY", authority=fake_authority())
        self.assertFalse(self.workdir.exists())

    def test_audit_only_requires_anchored_authority(self):
        with self.assertRaisesRegex(MAEPError, "CanonicalManifest authority"):
            build_runtime(self.workdir, [], principal=AUDIT_ONLY_PRINCIPAL, mode="AUDIT_ONLY")
        self.assertFalse(self.workdir.exists())

    def test_audit_only_rejects_duck_typed_authority(self):
        class DuckAuthority:
            def current(self):
                return ({}, {})
        with self.assertRaisesRegex(MAEPError, "CanonicalManifest authority"):
            build_runtime(self.workdir, [], principal=AUDIT_ONLY_PRINCIPAL,
                          mode="AUDIT_ONLY", authority=DuckAuthority())
        self.assertFalse(self.workdir.exists())

    def test_audit_only_rejects_fixture_grants(self):
        with self.assertRaisesRegex(MAEPError, "fixture or duck-typed authority is forbidden"):
            build_runtime(self.workdir, [], principal=AUDIT_ONLY_PRINCIPAL, mode="AUDIT_ONLY",
                          authority=fake_authority(), allow_fixture_grants=True)
        self.assertFalse(self.workdir.exists())

    def test_audit_only_registry_contains_read_actions_only(self):
        runtime = self.build_audit()
        registry = runtime.gateway.registry()
        self.assertTrue(registry)
        self.assertTrue(all(item["action"] in {"READ", "LIST", "INSPECT"} for item in registry))
        names = {item["name"] for item in registry}
        self.assertNotIn("fs.write", names)
        self.assertNotIn("test.run", names)
        self.assertEqual(runtime.gateway.tool_names(), sorted(names))

    def test_audit_only_rejects_extra_write_adapter(self):
        root = self.workdir / "root"
        root.mkdir(parents=True)
        with self.assertRaisesRegex(MAEPError, "non-allowlisted capabilities.*fs.write"):
            self.build_audit(extra_adapters=[LocalFileWriteAdapter(root)])
        self.assertFalse((root / "out" / "should-not-exist.txt").exists())

    def test_audit_only_runtime_does_not_create_write_target(self):
        runtime = self.build_audit()
        target = runtime.root / "out" / "should-not-exist.txt"
        self.assertFalse(target.exists())
        self.assertEqual(runtime.gateway._mode, "AUDIT_ONLY")
        self.assertNotIn("url.read", runtime.gateway.tool_names())

    def test_audit_only_rejects_adapter_that_merely_claims_read(self):
        with self.assertRaisesRegex(MAEPError, "non-allowlisted capabilities.*fake.read-but-mutates"):
            self.build_audit(extra_adapters=[MisdeclaredReadAdapter()])

    def test_audit_only_can_read_with_exact_task_and_anchor_grants(self):
        runtime = self.build_audit(grants=[grant(
            authorization_id="AUTH-AUDIT-READ", action="READ",
            resource="file:out/input.txt", scope=("out/",), task_id="T-AUDIT",
            principal=AUDIT_ONLY_PRINCIPAL,
        )], verifiers={"AC-1": content_verifier(
            self.root, path="out/input.txt", expected="read-only fixture"
        )})
        target = runtime.root / "out" / "input.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("read-only fixture", encoding="utf-8")
        step = {
            "step_id": "S-READ", "tool": "fs.read", "action": "READ",
            "resource": "file:out/input.txt", "scope": ["out/"],
            "authorization_id": "AUTH-AUDIT-READ", "params": {"path": "out/input.txt"},
        }
        result = runtime.orch.execute_task(make_task(task_id="T-AUDIT"), [step])
        self.assertEqual(result["task"]["state"], "CLOSED_VERIFIED")
        self.assertEqual(target.read_text(encoding="utf-8"), "read-only fixture")
        self.assertNotIn("fs.write", runtime.gateway.tool_names())
        self.assertNotIn("test.run", runtime.gateway.tool_names())


if __name__ == "__main__":
    unittest.main()
