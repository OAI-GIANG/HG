"""Tests for explicitly configured local-runtime provider mechanics."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from maep.local_runtime_providers import (
    GitCandidateProvider, LocalPrincipalProvider, LocalPolicyProvider,
    LocalReceiptSink, SQLiteIdempotencyLedger,
)
from maep.native_authority import AuthorityError, TrustRootRecord


class PolicyVerifierFixture:
    def verify_policy_source(self, record, *, root, policy):
        return record.get("test_source_marker") == "isolated-test" and root.verify_integrity()


class SessionVerifierFixture:
    def resolve_authenticated_session(self, context):
        if not isinstance(context, str) or context not in {"trusted-session-handle", "expired-session-handle"}:
            return None
        now = datetime.now(timezone.utc)
        issued = now - timedelta(minutes=2)
        expires = now - timedelta(minutes=1) if context == "expired-session-handle" else now + timedelta(minutes=3)
        return {
            "status": "ACTIVE", "verified": True, "revoked": False,
            "principal_id": "fixture-principal", "session_id": "fixture-session-1",
            "identity_evidence_ref": "fixture:identity-evidence",
            "issued_at": issued.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            "capabilities": ["READ"], "resource_scopes": ["fixture://resource"],
            "allowed_scopes": ["fixture"],
        }


class LocalRuntimeProviderTests(unittest.TestCase):
    def _root(self):
        return TrustRootRecord.create(
            root_id="provider-test-root", generation=1,
            created_at="2026-10-23T00:00:00Z",
            bootstrap_authorization_ref="fixture:approval",
            verification_method="fixture", verification_material_ref="fixture://material",
            policy_change_rule_ref="fixture://policy-rule", evidence_ref="fixture://evidence",
        )

    def test_policy_provider_requires_injected_source_provenance(self):
        with tempfile.TemporaryDirectory(prefix="hg-policy-provider-") as temp:
            path = Path(temp) / "policy.json"
            policy = {"status": "ACTIVE", "version": "test-v1", "root_generation": 1,
                      "approval_evidence_refs": ["fixture:approval"]}
            record = {"policy": policy}
            import hashlib
            from maep.local_runtime_providers import _digest
            record["policy_digest"] = _digest(policy)
            record["test_source_marker"] = "isolated-test"
            path.write_text(json.dumps(record), encoding="utf-8")
            path.chmod(0o600)
            provider = LocalPolicyProvider(path, PolicyVerifierFixture())
            resolved = provider.load_active(self._root())
            self.assertEqual(resolved["version"], policy["version"])
            self.assertEqual(resolved["policy_digest"], record["policy_digest"])
            self.assertIs(resolved["provenance_verified"], True)
            with self.assertRaisesRegex(AuthorityError, "approved trust source unavailable"):
                LocalPolicyProvider(path, object())

    def test_trust_source_contracts_reject_missing_and_truthy_non_boolean_verification(self):
        from maep.trust_source_contracts import require_trust_source_contract, require_verified_source_result
        with self.assertRaisesRegex(AuthorityError, "approved trust source unavailable"):
            require_trust_source_contract(None, "verify_policy_source", source_name="test")
        with self.assertRaisesRegex(AuthorityError, "did not verify"):
            require_verified_source_result(1, source_name="test")
        require_verified_source_result(True, source_name="isolated-fixture")

    def test_principal_provider_rejects_caller_claims_and_expired_session(self):
        provider = LocalPrincipalProvider(SessionVerifierFixture())
        self.assertIsNone(provider.resolve({"principal_id": "self-claimed", "verified": True}))
        self.assertIsNone(provider.resolve(None))
        active = provider.resolve("trusted-session-handle")
        self.assertEqual(active["principal_id"], "fixture-principal")
        self.assertIsNone(provider.resolve("expired-session-handle"))

        class MissingRevocationState:
            def resolve_authenticated_session(self, context):
                result = dict(SessionVerifierFixture().resolve_authenticated_session("trusted-session-handle"))
                result.pop("revoked")
                return result

        self.assertIsNone(LocalPrincipalProvider(MissingRevocationState()).resolve("trusted-session-handle"))

        class RevokedSession:
            def resolve_authenticated_session(self, context):
                result = dict(SessionVerifierFixture().resolve_authenticated_session("trusted-session-handle"))
                result["revoked"] = True
                return result

        self.assertIsNone(LocalPrincipalProvider(RevokedSession()).resolve("trusted-session-handle"))

    def test_candidate_provider_observes_current_checkout_and_manifest(self):
        repo = Path(__file__).resolve().parents[2]
        provider = GitCandidateProvider(repo)
        candidate = provider.inspect(repo)
        if candidate is None:
            self.skipTest("local checkout does not declare a GitHub OAI-GIANG/HG remote")
        self.assertEqual(candidate["repository"], "OAI-GIANG/HG")
        self.assertTrue(candidate["candidate_ref"].startswith("hg-local:"))
        self.assertTrue(candidate["source_manifest_digest"].startswith("sha256:"))
        self.assertIn("local_observation_not_independent_provenance", candidate["verification_scope"])

    def test_idempotency_is_durable_and_duplicate_key_never_reserves_twice(self):
        with tempfile.TemporaryDirectory(prefix="hg-idempotency-") as temp:
            path = Path(temp) / "ledger.sqlite3"
            ledger = SQLiteIdempotencyLedger(path)
            first = ledger.claim(idempotency_key="id-1", request_digest="req:1", decision_digest="dec:1")
            self.assertEqual(first["status"], "RESERVED")
            self.assertEqual(ledger.claim(idempotency_key="id-1", request_digest="req:1", decision_digest="dec:1")["status"], "DUPLICATE")
            self.assertEqual(ledger.claim(idempotency_key="id-1", request_digest="req:2", decision_digest="dec:1")["status"], "CONFLICT")
            ledger.record_outcome(idempotency_key="id-1", request_digest="req:1", outcome="SUCCESS", receipt={"receipt_id": "r1"})
            reopened = SQLiteIdempotencyLedger(path)
            self.assertEqual(reopened.inspect("id-1")["outcome"], "SUCCESS")
            self.assertEqual(reopened.claim(idempotency_key="id-1", request_digest="req:1", decision_digest="dec:1")["status"], "DUPLICATE")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_receipt_sink_readback_and_tamper_detection(self):
        with tempfile.TemporaryDirectory(prefix="hg-receipts-") as temp:
            sink = LocalReceiptSink(temp)
            first = sink.append({"event_type": "test.receipt", "payload": {"outcome": "BLOCKED"}})
            self.assertIn("hg-local-receipt:1:", first)
            sink.append({"event_type": "test.receipt", "payload": {"outcome": "UNKNOWN"}})
            self.assertTrue(sink.verify_integrity())
            reopened_rows = LocalReceiptSink(temp).read_all()
            self.assertEqual(len(reopened_rows), 2)
            self.assertEqual(reopened_rows[1]["prev_digest"], reopened_rows[0]["event_digest"])
            rows = sink.path.read_text(encoding="utf-8").splitlines()
            value = json.loads(rows[0])
            value["payload"]["outcome"] = "SUCCESS"
            sink.path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            sink.path.chmod(0o600)
            with self.assertRaises(AuthorityError):
                sink.verify_integrity()


if __name__ == "__main__":
    unittest.main()
