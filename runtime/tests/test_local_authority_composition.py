"""Isolated composition tests using the local root/evidence adapters.

No production path, runtime service, or external side effect is touched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maep.local_authority_store import LocalEvidenceSink, LocalRootStore
from maep.local_runtime_providers import LocalReceiptSink, SQLiteIdempotencyLedger
from maep.native_authority import AuthorityError, TrustRootRecord
from maep.trusted_providers import TrustedApplicabilityProvider, TrustedGateEvidenceProvider
from runtime.composition import build_runtime


class PolicyFixture:
    def load_active(self, root):
        return {
            "status": "ACTIVE", "version": "policy-fixture-v1",
            "root_generation": root.generation, "provenance_verified": True,
            "policy_digest": "sha256:" + "a" * 64,
            "approval_evidence_refs": ["fixture:policy-approval"],
            "grant_ttl_seconds": 30, "rules": [],
        }


class ResolverFixture:
    def resolve_applicability(self, request, candidate):
        return None

    def resolve_gate(self, request, candidate, policy):
        return None

    def resolve_evidence(self, evidence_ref):
        return None


class ProvenanceFixture:
    def validate_record_provenance(self, record, *, record_type, root, policy):
        return False


class LedgerFixture:
    def claim(self, **kwargs):
        return {"status": "RESERVED"}

    def record_outcome(self, **kwargs):
        return None


class ReceiptFixture:
    def append(self, event):
        return "fixture:receipt"

    def read_all(self):
        return []


class LocalRuntimeCompositionTests(unittest.TestCase):
    def test_composition_reopens_local_root_and_evidence_without_production_writes(self):
        with tempfile.TemporaryDirectory(prefix="hg-runtime-composition-") as temp:
            root_dir = Path(temp) / "root"
            evidence_dir = Path(temp) / "evidence"
            memory_path = Path(temp) / "memory" / "hg-test.sqlite"
            memory_path.parent.mkdir()

            # Fixture-only root and evidence; no owner source or production path is used.
            sink_before_restart = LocalEvidenceSink(evidence_dir)
            evidence_ref = sink_before_restart.append({
                "event_type": "fixture.root.provisioned",
                "payload": {"scope": "isolated-test"},
            })
            root = TrustRootRecord.create(
                root_id="hg-test-root", generation=1,
                created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="fixture:owner-approval",
                verification_method="fixture-only",
                verification_material_ref="fixture://material",
                policy_change_rule_ref="fixture://policy-rule",
                evidence_ref=evidence_ref,
            )
            LocalRootStore(root_dir).store_active(root)

            # Re-open both adapters, simulating a process restart.
            root_store = LocalRootStore(root_dir)
            evidence_sink = LocalEvidenceSink(evidence_dir)
            reloaded = root_store.load_active()
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.record_digest, root.record_digest)
            self.assertTrue(evidence_sink.verify_integrity())
            self.assertEqual(len(evidence_sink._read_events()), 1)

            policy = PolicyFixture()
            resolver = ResolverFixture()
            verifier = ProvenanceFixture()
            applicability = TrustedApplicabilityProvider(
                root_store=root_store, policy_provider=policy,
                resolver=resolver, verifier=verifier,
            )
            gate = TrustedGateEvidenceProvider(
                root_store=root_store, policy_provider=policy,
                resolver=resolver, verifier=verifier,
            )

            class CandidateFixture:
                def inspect(self, target):
                    return {"verified": True, "repository": "OAI-GIANG/HG",
                            "candidate_ref": "candidate:fixture"}

            class PrincipalFixture:
                def resolve(self, context):
                    return None

            durable_idempotency = SQLiteIdempotencyLedger(Path(temp) / "idempotency.sqlite3")
            durable_receipts = LocalReceiptSink(Path(temp) / "receipts")
            runtime = build_runtime(
                root_store=root_store,
                principal_provider=PrincipalFixture(),
                candidate_provider=CandidateFixture(),
                policy_provider=policy,
                applicability_provider=applicability,
                gate_provider=gate,
                evidence_sink=evidence_sink,
                authenticated_context_provider=lambda: None,
                candidate_target_provider=lambda: "fixture-target",
                memory_principal_provider=lambda: None,
                memory_candidate_ref_provider=lambda task_id: "candidate:fixture",
                memory_db_path=memory_path,
                live_state_provider=lambda task_id: None,
                acceptance_provider=lambda task_id, target: None,
                adapter_registry={"fixture": type("AdapterFixture", (), {
                    "execute": lambda self, **kwargs: {"outcome": "SUCCEEDED"}
                })()},
                idempotency_ledger=durable_idempotency,
                receipt_sink=durable_receipts,
            )

            self.assertIs(runtime.authority.root_store, root_store)
            self.assertIs(runtime.authority.evidence_sink, evidence_sink)
            self.assertEqual(runtime.authority.root_store.load_active().record_digest,
                             root.record_digest)
            self.assertTrue(evidence_sink.verify_integrity())
            self.assertIs(runtime.brain.idempotency_ledger, durable_idempotency)
            self.assertIs(runtime.brain.receipt_sink, durable_receipts)
            claim = durable_idempotency.claim(idempotency_key="composition-fixture", request_digest="req:1", decision_digest="dec:1")
            self.assertEqual(claim["status"], "RESERVED")
            durable_idempotency.record_outcome(idempotency_key="composition-fixture", request_digest="req:1", outcome="UNKNOWN", receipt={"status": "UNKNOWN"})
            reopened_ledger = SQLiteIdempotencyLedger(Path(temp) / "idempotency.sqlite3")
            self.assertEqual(reopened_ledger.inspect("composition-fixture")["status"], "UNKNOWN")
            durable_receipts.append({"event_type": "composition.fixture", "payload": {"status": "UNKNOWN"}})
            self.assertTrue(LocalReceiptSink(Path(temp) / "receipts").verify_integrity())
            # build_runtime composes dependencies but does not initialize Memory or start services.
            self.assertFalse(memory_path.exists())

    def test_concurrent_authority_decisions_keep_durable_evidence_intact(self):
        # The threaded HTTP boundary lets authority decisions run concurrently; each
        # BLOCKED decision appends evidence and append failures are swallowed by the
        # engine, so ledger integrity is the observable that must hold.
        import threading
        with tempfile.TemporaryDirectory(prefix="hg-runtime-concurrency-") as temp:
            evidence_dir = Path(temp) / "evidence"
            memory_path = Path(temp) / "memory" / "hg-test.sqlite"
            memory_path.parent.mkdir()
            evidence_sink = LocalEvidenceSink(evidence_dir)
            root = TrustRootRecord.create(
                root_id="hg-test-root", generation=1, created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="fixture:owner-approval",
                verification_method="fixture-only",
                verification_material_ref="fixture://material",
                policy_change_rule_ref="fixture://policy-rule",
                evidence_ref=evidence_sink.append({"event_type": "fixture.root.provisioned",
                                                   "payload": {"scope": "isolated-test"}}),
            )
            root_store = LocalRootStore(Path(temp) / "root")
            root_store.store_active(root)
            policy, resolver, verifier = PolicyFixture(), ResolverFixture(), ProvenanceFixture()

            class CandidateFixture:
                def inspect(self, target):
                    return {"verified": True, "repository": "OAI-GIANG/HG",
                            "candidate_ref": "candidate:fixture"}

            class PrincipalFixture:
                def resolve(self, context):
                    return None

            runtime = build_runtime(
                root_store=root_store, principal_provider=PrincipalFixture(),
                candidate_provider=CandidateFixture(), policy_provider=policy,
                applicability_provider=TrustedApplicabilityProvider(
                    root_store=root_store, policy_provider=policy, resolver=resolver, verifier=verifier),
                gate_provider=TrustedGateEvidenceProvider(
                    root_store=root_store, policy_provider=policy, resolver=resolver, verifier=verifier),
                evidence_sink=evidence_sink,
                authenticated_context_provider=lambda: None,
                candidate_target_provider=lambda: "fixture-target",
                memory_principal_provider=lambda: None,
                memory_candidate_ref_provider=lambda task_id: "candidate:fixture",
                memory_db_path=memory_path,
                live_state_provider=lambda task_id: None,
                acceptance_provider=lambda task_id, target: None,
                adapter_registry={"fixture": type("AdapterFixture", (), {
                    "execute": lambda self, **kwargs: {"outcome": "SUCCEEDED"}})()},
                idempotency_ledger=LedgerFixture(), receipt_sink=ReceiptFixture(),
            )
            workers, per_worker = 8, 12
            barrier = threading.Barrier(workers)
            decisions, guard = [], threading.Lock()

            def worker(index):
                barrier.wait()
                for step in range(per_worker):
                    result = runtime.authority.authorize(
                        {"action": "memory.read", "resource": f"task:{index}:{step}",
                         "task_ref": f"task:{index}"},
                        authenticated_context=None, candidate_target="fixture-target")
                    with guard:
                        decisions.append(result)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(len(decisions), workers * per_worker)
            self.assertTrue(all(result.decision.value == "BLOCKED" for result in decisions))
            self.assertTrue(all(result.reason_codes == ("IDENTITY_UNVERIFIED",) for result in decisions))
            reopened = LocalEvidenceSink(evidence_dir)
            self.assertTrue(reopened.verify_integrity())
            events = reopened._read_events()
            self.assertEqual(len(events), 1 + workers * per_worker)
            self.assertEqual(sum(1 for e in events if e["event_type"] == "authorization.blocked"),
                             workers * per_worker)
            self.assertFalse(memory_path.exists())

    def test_missing_active_root_is_absent_without_creating_state(self):
        with tempfile.TemporaryDirectory(prefix="hg-runtime-no-root-") as temp:
            root_store = LocalRootStore(Path(temp) / "root")
            self.assertIsNone(root_store.load_active())
            self.assertFalse(root_store.root_path.exists())


if __name__ == "__main__":
    unittest.main()
