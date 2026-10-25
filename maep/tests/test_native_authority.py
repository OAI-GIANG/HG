import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from maep.native_authority import (
    Applicability, AuthorityError, BootstrapState, Decision, NativePolicyEngine,
    RecoveryManager, TrustRootManager, TrustRootRecord,
)


class MemoryRootStore:
    def __init__(self):
        self.root = None

    def load_active(self):
        return self.root

    def store_active(self, record):
        self.root = record


class ApprovalVerifier:
    def __init__(self, accepted=True):
        self.accepted = accepted

    def validate_owner_approval(self, canonical_payload, approval):
        return self.accepted and approval == "owner-approved"


class Sink:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def append(self, event):
        if self.fail:
            raise OSError("durable sink unavailable")
        self.events.append(event)
        return "ledger:" + str(len(self.events))


class Principal:
    def resolve(self, context):
        if context != "authenticated-session":
            return None
        return {"principal_id": "owner-1", "status": "ACTIVE", "verified": True, "identity_evidence_ref": "identity:test",
                "capabilities": ["WRITE"], "resource_scopes": ["hg://repo/file"], "allowed_scopes": ["file"]}


class Candidate:
    def inspect(self, target):
        if target != "known-candidate":
            return None
        return {"verified": True, "repository": "OAI-GIANG/HG", "source_manifest_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "candidate_ref": "candidate:abc"}


class Policy:
    def load_active(self, root):
        return {"status": "ACTIVE", "version": "policy:1", "root_generation": root.generation, "provenance_verified": True, "policy_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "approval_evidence_refs": ["approval:test"], "grant_ttl_seconds": 60,
                "rules": [{"action": "WRITE", "resource": "hg://repo/file", "effect": "ALLOW", "scope": ["file"]}]}


class ApplicabilityProvider:
    def __init__(self, classification=Applicability.NOT_REQUIRED.value):
        self.classification = classification

    def classify(self, request, candidate):
        return {"verified": True, "classification": self.classification,
                "candidate_ref": candidate["candidate_ref"], "action": request.get("action"),
                "resource": request.get("resource"), "applicability_id": "app:1", "rule_version": "app-rules:1", "facts_used": ["action", "resource"], "evidence_refs": ["app-evidence:1"]}


class Gate:
    def __init__(self, status="PASS", include_canonical_record=True):
        self.status = status
        self.include_canonical_record = include_canonical_record

    def evaluate(self, request, candidate, policy):
        result = {"status": self.status, "verified": True, "evidence_verified": True,
                  "evidence_refs": ["gate-evidence:1"], "candidate_ref": candidate["candidate_ref"],
                  "policy_version": policy["version"], "gate_id": "gate:1"}
        if self.include_canonical_record:
            refs = ["INV-1", "CMP-1", "IMPACT-1", "REGRESSION-1"]
            result["record"] = {
                "decision_id": "MAEP022-test", "candidate_ref": candidate["candidate_ref"],
                "policy_version": policy["version"], "scope": "test scope", "capability": "test capability",
                "inventory_status": "COMPLETE", "inventory_evidence_refs": [refs[0]],
                "overlap_detected": True, "comparison_evidence_refs": [refs[1]],
                "decision": "EXISTING_REUSE", "selected_implementation": "existing implementation",
                "rationale": "Test evidence supports reuse", "impact_analysis_refs": [refs[2]],
                "regression_test_refs": [refs[3]], "gate_status": "PASS",
                "superiority_basis": {key: "evidence-backed test rationale" for key in (
                    "correctness", "security", "reliability", "functional_coverage",
                    "compatibility", "performance_resource_cost", "maintainability_operational_burden")},
            }
            result["evidence_by_id"] = {
                ref: {"evidence_id": ref, "evidence_type": "TEST_RESULT",
                      "source_ref": "test://" + ref, "candidate_ref": candidate["candidate_ref"],
                      "collected_at": "2026-10-22T10:00:00Z", "collector": "unit-test",
                      "method": "unittest", "result": "PASS", "limitations": []}
                for ref in refs
            }
        return result


def active_root():
    return TrustRootRecord.create(
        root_id="root:1", generation=1, created_at="2026-10-22T10:00:00Z",
        bootstrap_authorization_ref="approval:1", verification_method="test-verifier",
        verification_material_ref="test-material-ref", policy_change_rule_ref="policy-change:1",
        evidence_ref="ledger:bootstrap",
    )


class TrustRootTests(unittest.TestCase):
    def test_no_implicit_bootstrap(self):
        store = MemoryRootStore()
        self.assertIsNone(store.load_active())

    def test_bootstrap_requires_owner_controlled_approval(self):
        store = MemoryRootStore()
        manager = TrustRootManager(store, ApprovalVerifier(accepted=False), Sink())
        payload = {
            "root_id": "root:1", "generation": 1, "created_at": "2026-10-22T10:00:00Z",
            "bootstrap_authorization_ref": "approval:1", "verification_method": "test-verifier",
            "verification_material_ref": "test-material-ref", "policy_change_rule_ref": "policy-change:1",
            "previous_root_digest": None,
        }
        with self.assertRaisesRegex(AuthorityError, "owner approval not verified"):
            manager.bootstrap(payload, "owner-approved")
        self.assertIsNone(store.load_active())

    def test_bootstrap_evidence_failure_keeps_root_uninitialized(self):
        store = MemoryRootStore()
        manager = TrustRootManager(store, ApprovalVerifier(), Sink(fail=True))
        payload = {
            "root_id": "root:1", "generation": 1, "created_at": "2026-10-22T10:00:00Z",
            "bootstrap_authorization_ref": "approval:1", "verification_method": "test-verifier",
            "verification_material_ref": "test-material-ref", "policy_change_rule_ref": "policy-change:1",
            "previous_root_digest": None,
        }
        with self.assertRaisesRegex(AuthorityError, "evidence was not durably recorded"):
            manager.bootstrap(payload, "owner-approved")
        self.assertIsNone(store.load_active())

    def test_approved_bootstrap_and_readback(self):
        store = MemoryRootStore()
        manager = TrustRootManager(store, ApprovalVerifier(), Sink())
        payload = {
            "root_id": "root:1", "generation": 1, "created_at": "2026-10-22T10:00:00Z",
            "bootstrap_authorization_ref": "approval:1", "verification_method": "test-verifier",
            "verification_material_ref": "test-material-ref", "policy_change_rule_ref": "policy-change:1",
            "previous_root_digest": None,
        }
        root = manager.bootstrap(payload, "owner-approved")
        self.assertTrue(root.verify_integrity())
        self.assertEqual(root.generation, 1)

    def test_active_root_cannot_be_bootstrapped_again(self):
        store = MemoryRootStore()
        store.root = active_root()
        manager = TrustRootManager(store, ApprovalVerifier(), Sink())
        with self.assertRaisesRegex(AuthorityError, "already exists"):
            manager.bootstrap({}, "owner-approved")

    def test_tampered_root_fails_integrity(self):
        from dataclasses import replace
        root = active_root()
        self.assertFalse(replace(root, generation=2).verify_integrity())


class NativePolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.root_store = MemoryRootStore()
        self.root_store.root = active_root()
        self.sink = Sink()
        self.engine = NativePolicyEngine(
            root_store=self.root_store, principal_provider=Principal(),
            candidate_provider=Candidate(), policy_provider=Policy(),
            applicability_provider=ApplicabilityProvider(), gate_provider=Gate(),
            evidence_sink=self.sink,
        )
        self.request = {"action": "WRITE", "resource": "hg://repo/file",
                        "task_ref": "task:1", "scope": ["file"]}

    def authorize(self, **kwargs):
        defaults = {"authenticated_context": "authenticated-session",
                    "candidate_target": "known-candidate",
                    "now": datetime(2026, 10, 22, 10, tzinfo=timezone.utc)}
        defaults.update(kwargs)
        return self.engine.authorize(self.request, **defaults)

    def test_missing_root_blocks(self):
        self.root_store.root = None
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("MISSING_OR_INVALID_TRUST_ROOT",))

    def test_forged_identity_blocks(self):
        result = self.authorize(authenticated_context="caller-says-owner")
        self.assertEqual(result.decision, Decision.BLOCKED)

    def test_unverified_candidate_blocks(self):
        result = self.authorize(candidate_target="untrusted")
        self.assertEqual(result.decision, Decision.BLOCKED)

    def test_valid_low_risk_request_allows_and_records_evidence(self):
        result = self.authorize()
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertEqual(result.candidate_ref, "candidate:abc")
        self.assertTrue(self.sink.events)
        self.assertEqual(self.sink.events[-1]["event_type"], "authorization.decision")

    def test_caller_cannot_self_assert_applicability_and_unknown_skips_gate(self):
        self.request["capability_affecting"] = False
        self.request["trusted_policy_allow"] = True
        self.request["trusted_applicability"] = {"verified": True}
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.UNKNOWN.value)
        class GateMustNotRun:
            calls = 0
            def evaluate(inner_self, request, candidate, policy):
                inner_self.calls += 1
                raise AssertionError("MAEP-022 gate must not run for UNKNOWN applicability")
        gate = GateMustNotRun()
        self.engine.gate_provider = gate
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("APPLICABILITY_UNKNOWN",))
        self.assertEqual(gate.calls, 0)

    def test_required_gate_must_pass(self):
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.REQUIRED.value)
        self.engine.gate_provider = Gate(status="BLOCKED")
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("MAEP022_GATE_NOT_PASSED",))

    def test_required_gate_uses_canonical_maep_validator_and_returns_attestation(self):
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.REQUIRED.value)
        self.engine.gate_provider = Gate(status="PASS", include_canonical_record=True)
        result = self.authorize()
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertTrue(result.gate_verified)
        self.assertEqual(result.gate_ref, "gate:1")
        self.assertTrue(result.gate_evidence_refs)

    def test_provider_pass_boolean_without_canonical_record_is_blocked(self):
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.REQUIRED.value)
        self.engine.gate_provider = Gate(status="PASS", include_canonical_record=False)
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("MAEP022_CANONICAL_RECORD_MISSING",))

    def test_stale_gate_blocks(self):
        class StaleGate:
            def evaluate(self, request, candidate, policy):
                return {"status": "PASS", "candidate_ref": "old-candidate",
                        "policy_version": policy["version"], "gate_id": "gate:stale"}
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.REQUIRED.value)
        self.engine.gate_provider = StaleGate()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)

    def test_policy_denial_is_deny(self):
        class DenyPolicy:
            def load_active(self, root):
                return {"status": "ACTIVE", "version": "policy:1", "root_generation": root.generation, "provenance_verified": True, "policy_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000", "approval_evidence_refs": ["approval:test"], "grant_ttl_seconds": 60, "rules": []}
        self.engine.policy_provider = DenyPolicy()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.DENY)

    def test_explicit_deny_overrides_overlapping_allow(self):
        class OverlapPolicy(Policy):
            def load_active(self, root):
                policy = super().load_active(root)
                policy["rules"].append({
                    "action": "WRITE", "resource": "hg://repo/file",
                    "effect": "DENY", "scope": ["file"],
                })
                return policy
        self.engine.policy_provider = OverlapPolicy()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason_codes, ("POLICY_DENIED",))

    def test_scope_escalation_is_denied(self):
        self.request["scope"] = ["file", "secrets"]
        result = self.authorize()
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason_codes, ("PRINCIPAL_SCOPE_DENIED",))

    def test_revoked_principal_is_blocked(self):
        class RevokedPrincipal:
            def resolve(self, context):
                return {"principal_id": "owner-1", "status": "ACTIVE", "verified": True,
                        "identity_evidence_ref": "identity:test", "revoked": True,
                        "capabilities": ["WRITE"], "resource_scopes": ["hg://repo/file"],
                        "allowed_scopes": ["file"]}
        self.engine.principal_provider = RevokedPrincipal()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("PRINCIPAL_REVOKED",))

    def test_policy_must_bind_to_current_root_generation(self):
        class StalePolicy:
            def load_active(self, root):
                return {"status": "ACTIVE", "version": "policy:1", "root_generation": root.generation + 1,
                        "provenance_verified": True, "policy_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                        "approval_evidence_refs": ["approval:test"], "grant_ttl_seconds": 60,
                        "rules": [{"action": "WRITE", "resource": "hg://repo/file", "effect": "ALLOW", "scope": ["file"]}]}
        self.engine.policy_provider = StalePolicy()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("POLICY_ROOT_GENERATION_MISMATCH",))

    def test_pass_gate_without_resolved_evidence_is_blocked(self):
        class EmptyEvidenceGate:
            def evaluate(self, request, candidate, policy):
                return {"status": "PASS", "verified": True, "evidence_verified": True,
                        "evidence_refs": [], "candidate_ref": candidate["candidate_ref"],
                        "policy_version": policy["version"], "gate_id": "gate:empty"}
        self.engine.applicability_provider = ApplicabilityProvider(Applicability.REQUIRED.value)
        self.engine.gate_provider = EmptyEvidenceGate()
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)
        self.assertEqual(result.reason_codes, ("MAEP022_GATE_NOT_PASSED",))

    def test_expired_authorization_cannot_cross_effect_boundary(self):
        result = self.authorize()
        with self.assertRaisesRegex(AuthorityError, "expired"):
            self.engine.recheck_before_effect(
                result, request=self.request, current_candidate_ref="candidate:abc",
                current_root_generation=1, current_root_digest=active_root().record_digest, current_policy_version="policy:1", current_policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                now=datetime(2026, 10, 22, 10, 2, 0, tzinfo=timezone.utc))

    def test_evidence_sink_failure_blocks_allow(self):
        self.sink.fail = True
        result = self.authorize()
        self.assertEqual(result.decision, Decision.BLOCKED)

    def test_pre_effect_recheck_detects_candidate_and_policy_changes(self):
        result = self.authorize()
        self.assertEqual(result.decision, Decision.ALLOW)
        self.assertTrue(self.engine.recheck_before_effect(
            result, request=self.request, current_candidate_ref="candidate:abc",
            current_root_generation=1, current_root_digest=active_root().record_digest, current_policy_version="policy:1", current_policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            now=datetime(2026, 10, 22, 10, 0, 10, tzinfo=timezone.utc)))
        with self.assertRaisesRegex(AuthorityError, "candidate changed"):
            self.engine.recheck_before_effect(
                result, request=self.request, current_candidate_ref="candidate:new",
                current_root_generation=1, current_root_digest=active_root().record_digest, current_policy_version="policy:1", current_policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                now=datetime(2026, 10, 22, 10, 0, 10, tzinfo=timezone.utc))
        with self.assertRaisesRegex(AuthorityError, "policy changed"):
            self.engine.recheck_before_effect(
                result, request=self.request, current_candidate_ref="candidate:abc",
                current_root_generation=1, current_root_digest=active_root().record_digest, current_policy_version="policy:2", current_policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                now=datetime(2026, 10, 22, 10, 0, 10, tzinfo=timezone.utc))

    def test_request_change_detected_before_effect(self):
        result = self.authorize()
        changed = dict(self.request, resource="hg://repo/other")
        with self.assertRaisesRegex(AuthorityError, "request changed"):
            self.engine.recheck_before_effect(
                result, request=changed, current_candidate_ref="candidate:abc",
                current_root_generation=1, current_root_digest=active_root().record_digest, current_policy_version="policy:1", current_policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                now=datetime(2026, 10, 22, 10, 0, 10, tzinfo=timezone.utc))


class AuthorizeReentrancyTests(unittest.TestCase):
    """authorize() must not evaluate a decision from inside another decision."""

    def setUp(self):
        self.root_store = MemoryRootStore()
        self.root_store.root = active_root()
        self.sink = Sink()
        self.request = {"action": "WRITE", "resource": "hg://repo/file",
                        "task_ref": "task:1", "scope": ["file"]}
        self.now = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)

    def engine(self, applicability):
        return NativePolicyEngine(
            root_store=self.root_store, principal_provider=Principal(),
            candidate_provider=Candidate(), policy_provider=Policy(),
            applicability_provider=applicability, gate_provider=Gate(),
            evidence_sink=self.sink,
        )

    def call(self, engine):
        return engine.authorize(self.request, authenticated_context="authenticated-session",
                                candidate_target="known-candidate", now=self.now)

    def test_nested_authorize_from_a_provider_is_blocked_and_outer_fails_closed(self):
        test = self
        nested = []

        class ReentrantApplicability(ApplicabilityProvider):
            def classify(inner_self, request, candidate):
                nested.append(test.call(engine))      # provider asks authority again
                return super().classify(request, candidate)

        engine = self.engine(ReentrantApplicability())
        outer = self.call(engine)
        self.assertEqual([r.reason_codes for r in nested], [("AUTHORITY_REENTRANT_EVALUATION",)])
        self.assertEqual(nested[0].decision, Decision.BLOCKED)
        # This provider ignores the nested result; the outer decision is evaluated on
        # its own verified inputs. A provider that depends on the nested result fails
        # closed (see runtime/tests/test_authority_memory_read_path.py).
        self.assertEqual(outer.decision, Decision.ALLOW)
        self.assertEqual([e["event_type"] for e in self.sink.events],
                         ["authorization.blocked", "authorization.decision"])

    def test_sequential_valid_requests_are_unaffected(self):
        engine = self.engine(ApplicabilityProvider())
        results = [self.call(engine) for _ in range(3)]
        self.assertEqual([r.decision for r in results], [Decision.ALLOW] * 3)
        self.assertTrue(all(r.reason_codes == ("AUTHORIZED",) for r in results))

    def test_guard_is_released_after_provider_exception(self):
        class FailingApplicability(ApplicabilityProvider):
            def classify(inner_self, request, candidate):
                raise RuntimeError("provider failure")

        failing = self.call(self.engine(FailingApplicability()))
        self.assertEqual(failing.reason_codes, ("AUTHORITY_PROVIDER_OR_EVIDENCE_FAILURE",))
        self.assertEqual(self.call(self.engine(ApplicabilityProvider())).decision, Decision.ALLOW)

    def test_concurrent_threads_do_not_block_each_other(self):
        import threading
        started, release = threading.Event(), threading.Event()

        class SlowApplicability(ApplicabilityProvider):
            def classify(inner_self, request, candidate):
                started.set()
                release.wait(10)
                return super().classify(request, candidate)

        engine = self.engine(SlowApplicability())
        results = {}
        worker = threading.Thread(target=lambda: results.setdefault("slow", self.call(engine)))
        worker.start()
        self.assertTrue(started.wait(10))
        # While another thread is inside authorize(), this thread is not "nested".
        other = self.engine(ApplicabilityProvider())
        results["other"] = self.call(other)
        release.set()
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results["other"].decision, Decision.ALLOW)
        self.assertEqual(results["slow"].decision, Decision.ALLOW)

    def test_non_dict_request_while_active_still_blocks_without_error(self):
        test = self
        nested = []

        class ReentrantApplicability(ApplicabilityProvider):
            def classify(inner_self, request, candidate):
                nested.append(engine.authorize("not-a-dict", authenticated_context=None,
                                               candidate_target=None, now=test.now))
                return super().classify(request, candidate)

        engine = self.engine(ReentrantApplicability())
        self.call(engine)
        self.assertEqual(nested[0].reason_codes, ("AUTHORITY_REENTRANT_EVALUATION",))


class RecoveryTests(unittest.TestCase):
    def test_unknown_outcome_requires_reconciliation(self):
        self.assertEqual(RecoveryManager.classify_outcome(
            outcome="UNKNOWN", action_idempotent=False, live_state_reconciled=False),
            "RECONCILIATION_REQUIRED")

    def test_unknown_outcome_after_reconciliation_requires_fresh_authority(self):
        self.assertEqual(RecoveryManager.classify_outcome(
            outcome="UNKNOWN", action_idempotent=True, live_state_reconciled=True),
            "FRESH_AUTHORIZATION_REQUIRED")

    def test_unknown_outcome_label_rejected(self):
        with self.assertRaises(AuthorityError):
            RecoveryManager.classify_outcome(
                outcome="MAYBE", action_idempotent=False, live_state_reconciled=False)


if __name__ == "__main__":
    unittest.main()
