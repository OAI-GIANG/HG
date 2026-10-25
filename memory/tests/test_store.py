"""Conformance tests for the MAEP-bound Memory & Knowledge implementation."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from maep.core import MAEPError, POLICY_VERSION
from memory import MemoryStore


def now_text():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def policy_decision(request):
    """Test-only policy adapter. Production must inject the real trusted evaluator."""
    # Generic Memory data-plane authorization is not a MAEP-022 capability change.
    # If an explicit external action does declare capability impact, this test-only
    # adapter cannot produce gate evidence and must fail closed.
    if "capability_affecting" in request:
        if not isinstance(request.get("capability_affecting"), bool):
            raise MAEPError("test policy requires boolean capability applicability")
        if request["capability_affecting"] is True:
            raise MAEPError("test adapter has no capability-gate evidence resolver; fail closed")
    issued = datetime.now(timezone.utc)
    grant = {
        "authorization_id": "TEST-AUTH-" + str(abs(hash((request["resource"], request["action"], issued.isoformat())))),
        "principal": request["principal"],
        "action": request["action"],
        "resource": request["resource"],
        "scope": list(request["scope"]),
        "conditions": [],
        "task_id": request["task_id"],
        "policy_version": request["policy_version"],
        "decision": "ALLOW",
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(minutes=5)).isoformat(),
    }
    return {
        "grant": grant,
        "trusted_policy_allow": True,
        "satisfied_conditions": [],
    }


def applicability_provider_for_test(request):
    """Trusted only for tests; infer from controlled fixtures, not production data."""
    if not isinstance(request, dict):
        raise MAEPError("test applicability requires a request object")
    return {
        "verified": True,
        "candidate_ref": request.get("candidate_ref"),
        "action": request.get("action"),
        "resource": request.get("resource"),
        "capability_affecting": request.get("capability_affecting") is True,
    }


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "memory.sqlite3"
        self.live_candidate = "candidate-1"
        self.live_resources = [{"resource_id": "repo/OAI-GIANG/HG", "version": "candidate-1"}]
        self.store = MemoryStore(
            self.db,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision,
            live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        self.assertFalse(self.db.exists())
        initialized = self.store.initialize(task_id="T-BOOT")
        self.assertEqual(initialized["status"], "READY")
        self.assertTrue(initialized["created"])
        self.store.create_task(self.task(), candidate_ref="candidate-1")

    def tearDown(self):
        self.temp.cleanup()

    def live_state(self, task_id):
        return {
            "task_id": task_id,
            "candidate_ref": self.live_candidate,
            "policy_version": POLICY_VERSION,
            "observed_at": now_text(),
            "resources": list(self.live_resources),
        }

    @staticmethod
    def task(task_id="T-MK-1"):
        return {
            "task_id": task_id,
            "objective": "Validate Memory persistence and MAEP integration",
            "scope": {"include": ["memory/"], "exclude": ["production data"]},
            "inputs": [],
            "outputs": [{"name": "result", "description": "validated Memory record"}],
            "acceptance_criteria": [{
                "criterion_id": "AC-MK-1",
                "description": "Memory write is durable and authorized",
                "mandatory": True,
                "evidence_types": ["TEST_RESULT"],
            }],
            "evidence_requirements": ["candidate-bound evidence"],
            "risks": [],
            "stop_conditions": ["authority unavailable", "candidate mismatch"],
            "next_action": "validate-memory",
            "state": "DRAFT",
            "policy_version": POLICY_VERSION,
        }

    @staticmethod
    def evidence(evidence_id="EV-1", candidate_ref="candidate-1"):
        return {
            "evidence_id": evidence_id,
            "evidence_type": "OBSERVATION",
            "source_ref": "test://fixture/" + evidence_id,
            "candidate_ref": candidate_ref,
            "collected_at": now_text(),
            "collector": "test-harness",
            "method": "controlled fixture",
            "result": "observed",
            "limitations": ["test fixture; not production evidence"],
        }

    def record_evidence(self, evidence_id="EV-1"):
        return self.store.record_evidence("T-MK-1", self.evidence(evidence_id))

    def test_constructor_has_no_filesystem_side_effect(self):
        path = self.root / "not-created.sqlite3"
        MemoryStore(path, principal_provider=lambda: "x", policy_evaluator=policy_decision)
        self.assertFalse(path.exists())

    def test_missing_trusted_policy_adapter_fails_closed(self):
        path = self.root / "blocked.sqlite3"
        store = MemoryStore(path)
        with self.assertRaisesRegex(MAEPError, "policy evaluator unavailable"):
            store.initialize(task_id="T-BOOT")
        self.assertFalse(path.exists())

    def test_ordinary_memory_data_plane_does_not_require_maep022_provider(self):
        path = self.root / "ordinary-data-plane.sqlite3"
        store = MemoryStore(
            path,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision,
        )
        result = store.initialize(task_id="T-BOOT")
        self.assertEqual(result["status"], "READY")
        self.assertTrue(path.exists())

    def test_initialization_and_task_creation_are_maep_bound(self):
        snapshot = self.store.get_task("T-MK-1")
        self.assertEqual(snapshot["task"]["state"], "DRAFT")
        self.assertEqual(snapshot["row_version"], 1)
        self.assertEqual(snapshot["policy_status"], "CURRENT")
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_canonical_task_index_requires_dedicated_authorization_and_validates_binding(self):
        page = self.store.list_tasks(index_scope_task_id="T-MK-1", limit=10)
        self.assertEqual(page["integrity_status"], "PASS")
        self.assertEqual([item["task"]["task_id"] for item in page["tasks"]], ["T-MK-1"])
        self.assertEqual(page["returned"], 1)
        self.assertFalse(page["has_more"])

        def deny_index(request):
            decision = policy_decision(request)
            if request["resource"].startswith("memory:tasks/index"):
                decision["trusted_policy_allow"] = False
            return decision

        denied = MemoryStore(
            self.db,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=deny_index,
            live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        with self.assertRaisesRegex(MAEPError, "did not allow"):
            denied.list_tasks(index_scope_task_id="T-MK-1")

        with self.assertRaisesRegex(MAEPError, "context"):
            self.store.list_tasks(index_scope_task_id=" ")

        with self.assertRaisesRegex(MAEPError, "pagination"):
            self.store.list_tasks(index_scope_task_id="T-MK-1", limit=True)

    def test_canonical_task_index_rejects_missing_index_authorization_task(self):
        with self.assertRaisesRegex(MAEPError, "task not found"):
            self.store.list_tasks(index_scope_task_id="T-UNKNOWN")

    def test_database_reopen_preserves_task_and_event_history(self):
        reopened = MemoryStore(
            self.db,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision,
            live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        snapshot = reopened.get_task("T-MK-1")
        self.assertEqual(snapshot["task"]["state"], "DRAFT")
        self.assertEqual(reopened.get_events("T-MK-1")[0]["event_type"], "task.created")

    def test_policy_revocation_before_write_blocks_and_rolls_back(self):
        calls = {"evidence_write": 0}

        def revoke_on_recheck(request):
            decision = policy_decision(request)
            if any(":evidence:write" in scope for scope in request.get("scope", [])):
                calls["evidence_write"] += 1
                if calls["evidence_write"] >= 2:
                    decision["trusted_policy_allow"] = False
            return decision

        guarded = MemoryStore(
            self.db,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=revoke_on_recheck,
            live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        with self.assertRaisesRegex(MAEPError, "policy decision did not allow"):
            guarded.record_evidence("T-MK-1", self.evidence("EV-REVOKED"))
        self.assertEqual(calls["evidence_write"], 2)
        self.assertFalse(any(
            event["event_type"] == "evidence.recorded"
            for event in self.store.get_events("T-MK-1")
        ))

    def test_policy_version_mismatch_rejected(self):
        task = self.task("T-OLD")
        task["policy_version"] = "MAEP-1.0.0"
        with self.assertRaisesRegex(MAEPError, "policy version is stale"):
            self.store.create_task(task, candidate_ref="candidate-1")

    def test_store_with_stale_global_policy_metadata_fails_closed(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                "UPDATE memory_metadata SET value='MAEP-1.1.0' WHERE key='policy_version'"
            )
        with self.assertRaisesRegex(MAEPError, "policy-version metadata is stale"):
            self.store.get_task("T-MK-1")

    def test_obvious_secret_value_fields_are_rejected(self):
        task = self.task("T-SECRET")
        task["password"] = "do-not-store"
        with self.assertRaisesRegex(MAEPError, "store a reference"):
            self.store.create_task(task, candidate_ref="candidate-1")
        self.assertNotIn("T-SECRET", [item["task_id"] for item in self.store.get_events("T-MK-1")])

    def test_transition_uses_maep_guard_and_optimistic_version(self):
        snapshot = self.store.transition_task("T-MK-1", "READY", expected_version=1)
        self.assertEqual(snapshot["task"]["state"], "READY")
        self.assertEqual(snapshot["row_version"], 2)
        with self.assertRaisesRegex(MAEPError, "version conflict"):
            self.store.transition_task("T-MK-1", "ASSESSED", expected_version=1)

    def test_memory_cannot_grant_execution_or_claim_acceptance(self):
        for target in ("AUTHORIZED", "RUNNING", "ACCEPTED", "CLOSED_VERIFIED"):
            with self.subTest(target=target):
                with self.assertRaises(MAEPError):
                    self.store.transition_task("T-MK-1", target, expected_version=1)
        self.assertEqual(self.store.get_task("T-MK-1")["task"]["state"], "DRAFT")

    def test_full_maep_task_lifecycle_uses_action_grant_and_acceptance_evidence(self):
        self.record_evidence("EV-LIFECYCLE")
        for state, version in (("READY", 1), ("ASSESSED", 2), ("PLANNED", 3)):
            result = self.store.transition_task("T-MK-1", state, expected_version=version)
            self.assertEqual(result["task"]["state"], state)

        action_request = {
            "principal": "test-runtime-principal",
            "action": "EXECUTE",
            "resource": "tool:test:action",
            "scope": ["tool:test:action"],
            "task_id": "T-MK-1",
            "policy_version": POLICY_VERSION,
            "capability_affecting": False,
            "capability_gate": {"applies": False, "reason": "test-only tool action does not change HG capabilities"},
        }
        authorized = self.store.transition_task(
            "T-MK-1", "AUTHORIZED", expected_version=4, action_request=action_request
        )
        self.assertEqual(authorized["task"]["state"], "AUTHORIZED")
        running = self.store.transition_task(
            "T-MK-1", "RUNNING", expected_version=5, action_request=action_request
        )
        self.assertEqual(running["task"]["state"], "RUNNING")
        verifying = self.store.transition_task("T-MK-1", "VERIFYING", expected_version=6)
        self.assertEqual(verifying["task"]["state"], "VERIFYING")

        def acceptance_provider(task_id, target):
            gate = {
                "gate_id": "G-MK-1",
                "task_id": task_id,
                "candidate_ref": "candidate-1",
                "required": True,
                "status": "PASS",
                "criteria_refs": ["AC-MK-1"],
                "evidence_refs": ["EV-LIFECYCLE"],
            }
            context = {
                "candidate_ref": "candidate-1",
                "policy_version": POLICY_VERSION,
                "mandatory_gates": [gate],
            }
            if target == "CLOSED_VERIFIED":
                context["closure"] = {
                    "closure_id": "CLOSE-MK-1",
                    "task_id": task_id,
                    "final_state": "CLOSED_VERIFIED",
                    "candidate_ref": "candidate-1",
                    "policy_version": POLICY_VERSION,
                    "criteria_results": [{
                        "criterion_id": "AC-MK-1",
                        "status": "PASS",
                        "evidence_refs": ["EV-LIFECYCLE"],
                    }],
                    "gate_refs": ["G-MK-1"],
                    "evidence_refs": ["EV-LIFECYCLE"],
                    "limitations": ["test-only evidence"],
                    "closed_at": now_text(),
                }
            return context

        self.store.acceptance_provider = acceptance_provider
        accepted = self.store.transition_task("T-MK-1", "ACCEPTED", expected_version=7)
        self.assertEqual(accepted["task"]["state"], "ACCEPTED")
        closed = self.store.transition_task("T-MK-1", "CLOSED_VERIFIED", expected_version=8)
        self.assertEqual(closed["task"]["state"], "CLOSED_VERIFIED")
        events = self.store.get_events("T-MK-1", limit=100)
        terminal = [e for e in events if e["event_type"] == "task.transitioned"][-1]
        self.assertEqual(terminal["payload"]["to_state"], "CLOSED_VERIFIED")
        self.assertEqual(terminal["payload"]["mandatory_gate_ids"], ["G-MK-1"])

    def test_acceptance_rejects_gate_that_does_not_cover_mandatory_criterion(self):
        self.record_evidence("EV-GATE")
        for state, version in (("READY", 1), ("ASSESSED", 2), ("PLANNED", 3), ("AUTHORIZED", 4)):
            kwargs = {}
            if state == "AUTHORIZED":
                kwargs["action_request"] = {
                    "principal": "test-runtime-principal", "action": "EXECUTE",
                    "resource": "tool:test:action", "scope": ["tool:test:action"],
                    "task_id": "T-MK-1", "policy_version": POLICY_VERSION,
                    "capability_affecting": False,
                    "capability_gate": {"applies": False, "reason": "test-only tool action does not change HG capabilities"},
                }
            self.store.transition_task("T-MK-1", state, expected_version=version, **kwargs)
        self.store.transition_task(
            "T-MK-1", "RUNNING", expected_version=5,
            action_request={
                "principal": "test-runtime-principal", "action": "EXECUTE",
                "resource": "tool:test:action", "scope": ["tool:test:action"],
                "task_id": "T-MK-1", "policy_version": POLICY_VERSION,
                "capability_affecting": False,
                "capability_gate": {"applies": False, "reason": "test-only tool action does not change HG capabilities"},
            },
        )
        self.store.transition_task("T-MK-1", "VERIFYING", expected_version=6)
        self.store.acceptance_provider = lambda task_id, target: {
            "candidate_ref": "candidate-1",
            "policy_version": POLICY_VERSION,
            "mandatory_gates": [{
                "gate_id": "G-WRONG", "task_id": task_id, "candidate_ref": "candidate-1",
                "required": True, "status": "PASS", "criteria_refs": ["OTHER-CRITERION"],
                "evidence_refs": ["EV-GATE"],
            }],
        }
        with self.assertRaisesRegex(MAEPError, "cover every mandatory task criterion"):
            self.store.transition_task("T-MK-1", "ACCEPTED", expected_version=7)
        self.assertEqual(self.store.get_task("T-MK-1")["task"]["state"], "VERIFYING")

    def test_candidate_mismatched_evidence_rejected(self):
        with self.assertRaisesRegex(MAEPError, "candidate does not match"):
            self.store.record_evidence("T-MK-1", self.evidence(candidate_ref="other"))
        self.assertFalse(any(
            event["event_type"] == "evidence.recorded"
            for event in self.store.get_events("T-MK-1")
        ))

    def test_evidence_is_saved_with_event_in_same_store(self):
        result = self.record_evidence()
        self.assertEqual(result["status"], "RECORDED")
        events = self.store.get_events("T-MK-1")
        self.assertEqual(events[-1]["event_type"], "evidence.recorded")
        self.assertEqual(events[-1]["payload"]["evidence_id"], "EV-1")

    def test_fact_claim_requires_evidence_and_is_unverified_by_default(self):
        claim = {
            "claim_id": "CL-1", "claim_type": "FACT", "statement": "HG memory is candidate-bound",
            "evidence_refs": [], "limitations": [],
        }
        with self.assertRaises(MAEPError):
            self.store.put_knowledge(
                "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://memory",
                collector="test", method="inspection", provenance_limitations=["test-only"],
            )
        self.record_evidence()
        claim["evidence_refs"] = ["EV-1"]
        record = self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://memory",
            collector="test", method="inspection", provenance_limitations=["test-only"],
        )
        self.assertEqual(record["verification_status"], "UNVERIFIED")
        found = self.store.search_knowledge("T-MK-1", "candidate-bound")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["verification_status"], "UNVERIFIED")

    def test_verification_is_a_new_authorized_immutable_version(self):
        self.record_evidence()
        claim = {
            "claim_id": "CL-VERIFY", "claim_type": "FACT", "statement": "The event and evidence share candidate identity",
            "evidence_refs": ["EV-1"], "limitations": [],
        }
        first = self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://candidate",
            collector="test", method="controlled observation", provenance_limitations=["fixture only"],
        )
        second = self.store.verify_knowledge(
            "T-MK-1", "CL-VERIFY", candidate_ref="candidate-1", evidence_refs=["EV-1"],
            verification_id="VER-1", limitations=["asserted by test-only verifier"],
        )
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["supersedes_record_id"], first["record_id"])
        self.assertEqual(second["verification_status"], "VERIFIED")
        found = self.store.search_knowledge("T-MK-1", "candidate identity")
        self.assertEqual(found[0]["record_id"], second["record_id"])
        self.assertEqual(found[0]["verification_status"], "VERIFIED")

    def test_get_knowledge_returns_latest_authorized_version_by_claim_id(self):
        self.record_evidence()
        claim = {
            "claim_id": "CL-GET", "claim_type": "FACT",
            "statement": "Direct claim lookup stays task scoped",
            "evidence_refs": ["EV-1"], "limitations": [],
        }
        first = self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://lookup",
            collector="test", method="controlled observation", provenance_limitations=["fixture only"],
        )
        second = self.store.verify_knowledge(
            "T-MK-1", "CL-GET", candidate_ref="candidate-1", evidence_refs=["EV-1"],
            verification_id="VER-GET", limitations=["test verifier"],
        )
        found = self.store.get_knowledge("T-MK-1", "CL-GET")
        self.assertEqual(found["record_id"], second["record_id"])
        self.assertEqual(found["version"], 2)
        self.assertEqual(found["verification_status"], "VERIFIED")
        self.assertNotEqual(found["record_id"], first["record_id"])

    def test_get_knowledge_survives_store_reopen_with_same_canonical_binding(self):
        self.record_evidence()
        claim = {
            "claim_id": "CL-RESTART", "claim_type": "FACT",
            "statement": "Knowledge remains versioned after reopen",
            "evidence_refs": ["EV-1"], "limitations": [],
        }
        self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://restart",
            collector="test", method="controlled observation", provenance_limitations=["fixture only"],
        )
        self.store.verify_knowledge(
            "T-MK-1", "CL-RESTART", candidate_ref="candidate-1", evidence_refs=["EV-1"],
            verification_id="VER-RESTART", limitations=["test verifier"],
        )
        reopened = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision, live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        found = reopened.get_knowledge("T-MK-1", "CL-RESTART")
        self.assertEqual(found["version"], 2)
        self.assertEqual(found["verification_status"], "VERIFIED")
        self.assertEqual(found["candidate_ref"], "candidate-1")

    def test_get_knowledge_returns_none_for_stale_claim_by_default(self):
        self.record_evidence()
        claim = {
            "claim_id": "CL-GET-STALE", "claim_type": "FACT",
            "statement": "Candidate scoped knowledge", "evidence_refs": ["EV-1"], "limitations": [],
        }
        self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://stale",
            collector="test", method="observation", provenance_limitations=["candidate scoped"],
        )
        self.store.update_candidate(
            "T-MK-1", expected_version=1, old_candidate_ref="candidate-1", new_candidate_ref="candidate-2"
        )
        self.assertIsNone(self.store.get_knowledge("T-MK-1", "CL-GET-STALE"))
        stale = self.store.get_knowledge("T-MK-1", "CL-GET-STALE", include_stale=True)
        self.assertEqual(stale["record_status"], "STALE")

    def test_candidate_change_invalidates_old_knowledge_for_default_retrieval(self):
        self.record_evidence()
        claim = {
            "claim_id": "CL-STALE", "claim_type": "FACT", "statement": "Old candidate was observed",
            "evidence_refs": ["EV-1"], "limitations": [],
        }
        self.store.put_knowledge(
            "T-MK-1", claim, candidate_ref="candidate-1", source_ref="fixture://old",
            collector="test", method="observation", provenance_limitations=["candidate-specific"],
        )
        changed = self.store.update_candidate(
            "T-MK-1", expected_version=1, old_candidate_ref="candidate-1", new_candidate_ref="candidate-2"
        )
        self.assertTrue(changed["impact_assessment_required"])
        self.assertEqual(changed["invalidate_evidence_refs"], ["EV-1"])
        self.assertEqual(self.store.search_knowledge("T-MK-1", "Old candidate"), [])
        stale = self.store.search_knowledge("T-MK-1", "Old candidate", include_stale=True)
        self.assertEqual(stale[0]["record_status"], "STALE")

    def test_checkpoint_digest_and_resume_reconciliation(self):
        record = self.store.save_checkpoint(
            "T-MK-1",
            expected_version=1,
            completed_steps=[],
            pending_steps=[{
                "step_id": "STEP-1", "prerequisites": [],
                "acceptance_conditions": ["live candidate agrees"],
            }],
            blockers=[],
            decisions=[],
            evidence_refs=[],
            next_action={
                "description": "Inspect the next authorized step",
                "preconditions": ["checkpoint current"],
                "required_authorization": {"action": "READ", "resource": "repo/OAI-GIANG/HG"},
                "expected_result": "current task context and evidence",
                "stop_condition": "missing or conflicting evidence",
            },
        )
        self.assertEqual(len(record["checkpoint"]["content_digest"]), 64)
        loaded = self.store.latest_checkpoint("T-MK-1")
        self.assertEqual(loaded["checkpoint"]["checkpoint_id"], record["checkpoint"]["checkpoint_id"])
        decision = self.store.assess_resume("T-MK-1")
        self.assertEqual(decision["status"], "CURRENT")
        self.assertTrue(decision["can_resume"])
        self.assertTrue(decision["audit_recorded"])

    def test_resume_blocks_live_candidate_conflict(self):
        self.store.save_checkpoint(
            "T-MK-1", expected_version=1, completed_steps=[],
            pending_steps=[{"step_id": "STEP-1", "prerequisites": [], "acceptance_conditions": ["compare candidate"]}],
            blockers=[], decisions=[], evidence_refs=[],
            next_action={
                "description": "Continue after reconciliation", "preconditions": [],
                "required_authorization": ["action-specific grant"],
                "expected_result": "candidate reconciled", "stop_condition": "candidate conflict",
            },
        )
        self.live_candidate = "candidate-2"
        result = self.store.assess_resume("T-MK-1")
        self.assertEqual(result["status"], "CONFLICTING")
        self.assertFalse(result["can_resume"])
        self.assertTrue(result["audit_recorded"])

    def test_checkpoint_requires_explicit_completed_step_verification_status(self):
        with self.assertRaisesRegex(MAEPError, "explicitly label verification status"):
            self.store.save_checkpoint(
                "T-MK-1", expected_version=1,
                completed_steps=[{
                    "step_id": "STEP-DONE", "outcome": "done",
                    "timestamp": now_text(), "evidence_refs": [],
                }],
                pending_steps=[{
                    "step_id": "STEP-NEXT", "prerequisites": [],
                    "acceptance_conditions": ["verified context"],
                }],
                blockers=[], decisions=[], evidence_refs=[],
                next_action={
                    "description": "continue", "preconditions": [],
                    "required_authorization": ["grant"],
                    "expected_result": "validated context", "stop_condition": "missing evidence",
                },
            )

    def test_checkpoint_creation_blocks_without_live_state_provider(self):
        no_observer = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision, live_state_provider=None,
        )
        with self.assertRaisesRegex(MAEPError, "live-state observer unavailable"):
            no_observer.save_checkpoint(
                "T-MK-1", expected_version=1, completed_steps=[], pending_steps=[],
                blockers=[], decisions=[], evidence_refs=[],
                next_action={
                    "description": "continue", "preconditions": [],
                    "required_authorization": ["grant"], "expected_result": "done",
                    "stop_condition": "unknown",
                },
            )

    def test_unresolved_blocker_prevents_resume(self):
        record = self.store.save_checkpoint(
            "T-MK-1", expected_version=1, completed_steps=[],
            pending_steps=[{"step_id": "STEP-1", "prerequisites": [], "acceptance_conditions": ["resolve blocker"]}],
            blockers=[{
                "blocker_id": "BL-1", "known_cause": "missing evidence", "unknowns": [],
                "missing_prerequisite": "resolution evidence", "next_action": "collect evidence",
                "reopen_condition": "evidence linked",
            }],
            decisions=[], evidence_refs=[],
            next_action={
                "description": "resolve blocker", "preconditions": [],
                "required_authorization": ["write"],
                "expected_result": "blocker resolved", "stop_condition": "evidence absent",
            },
        )
        result = self.store.assess_resume("T-MK-1")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["can_resume"])

    def test_resume_blocks_when_live_observer_is_unavailable(self):
        self.store.save_checkpoint(
            "T-MK-1", expected_version=1, completed_steps=[],
            pending_steps=[{"step_id": "STEP-1", "prerequisites": [], "acceptance_conditions": ["observe live state"]}],
            blockers=[], decisions=[], evidence_refs=[],
            next_action={
                "description": "Observe live state", "preconditions": [],
                "required_authorization": ["read access"],
                "expected_result": "reconciled context", "stop_condition": "observer unavailable",
            },
        )
        no_observer = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision, live_state_provider=None,
            applicability_provider=applicability_provider_for_test,
        )
        result = no_observer.assess_resume("T-MK-1")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["can_resume"])
        self.assertTrue(result["audit_recorded"])

    def test_terminal_task_cannot_resume(self):
        with sqlite3.connect(self.db) as connection:
            task = json.loads(connection.execute(
                "SELECT task_json FROM tasks WHERE task_id='T-MK-1'"
            ).fetchone()[0])
            task["state"] = "CLOSED_VERIFIED"
            connection.execute(
                "UPDATE tasks SET state='CLOSED_VERIFIED', task_json=? WHERE task_id='T-MK-1'",
                (json.dumps(task),),
            )
        result = self.store.assess_resume("T-MK-1")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["can_resume"])
        self.assertIn("linked task/amendment", result["differences"][0])

    def test_events_and_checkpoint_rows_reject_updates(self):
        self.record_evidence()
        with sqlite3.connect(self.db) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE maep_events SET event_type='rewritten' WHERE sequence=1")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM evidence WHERE evidence_id='EV-1'")

    def test_privileged_event_payload_tampering_is_detected_and_blocks_reads(self):
        self.record_evidence()
        with sqlite3.connect(self.db) as connection:
            connection.execute("DROP TRIGGER maep_events_no_update")
            connection.execute(
                "UPDATE maep_events SET payload_json=? WHERE sequence=1",
                (json.dumps({"tampered": True}),),
            )
        with self.assertRaisesRegex(MAEPError, "event digest mismatch"):
            self.store.get_task("T-MK-1")
        integrity = self.store.check_integrity(task_id="T-MK-1")
        self.assertEqual(integrity["status"], "FAIL")
        self.assertIn("event digest mismatch", integrity["details"][0])

    def test_same_claim_id_can_be_versioned_per_task(self):
        self.store.create_task(self.task("T-MK-2"), candidate_ref="candidate-1")
        for task_id, evidence_id in (("T-MK-1", "EV-SHARED-1"), ("T-MK-2", "EV-SHARED-2")):
            self.store.record_evidence(task_id, self.evidence(evidence_id))
            record = self.store.put_knowledge(
                task_id,
                {
                    "claim_id": "CLAIM-SHARED",
                    "claim_type": "FACT",
                    "statement": f"Claim scoped to {task_id}",
                    "evidence_refs": [evidence_id],
                    "limitations": ["test fixture"],
                },
                candidate_ref="candidate-1",
                source_ref=f"fixture://{task_id}",
                collector="test",
                method="controlled fixture",
                provenance_limitations=["not production evidence"],
            )
            self.assertEqual(record["version"], 1)

    def test_online_backup_and_isolated_restore(self):
        backup = self.root / "backup.sqlite3"
        restored = self.root / "restored.sqlite3"
        self.record_evidence()
        result = self.store.backup_to(backup, task_id="T-MK-1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            self.store.restore_to(restored, task_id="T-MK-1", source_path=backup)["status"],
            "PASS",
        )
        clone = MemoryStore(
            restored, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision, live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
        )
        self.assertEqual(clone.get_task("T-MK-1")["task"]["task_id"], "T-MK-1")
        self.assertEqual(clone.check_integrity(task_id="T-MK-1")["status"], "PASS")

    def test_backup_never_overwrites_existing_destination(self):
        destination = self.root / "already-exists.sqlite3"
        destination.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(MAEPError, "overwrite is prohibited"):
            self.store.backup_to(destination, task_id="T-MK-1")
        self.assertEqual(destination.read_text(encoding="utf-8"), "preserve")

    def test_external_action_authorization_fails_closed_without_maep022_provider(self):
        guarded = MemoryStore(
            self.db,
            principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision,
            live_state_provider=self.live_state,
        )
        request = {
            "principal": "test-runtime-principal",
            "action": "WRITE",
            "resource": "hg:capability/test",
            "scope": ["capability:test:write"],
            "task_id": "T-MK-1",
            "policy_version": POLICY_VERSION,
            "capability_affecting": False,
            "capability_gate": {"applies": False, "reason": "caller assertion under test"},
        }
        with self.assertRaisesRegex(MAEPError, "trusted MAEP-022 applicability provider unavailable"):
            guarded._authorize_external_action(request, "T-MK-1")
        # This authorization-only path must not mutate the durable store.
        self.assertEqual(self.store.get_events("T-MK-1")[0]["event_type"], "task.created")

    def test_external_action_blocks_caller_false_when_trusted_applicability_requires_gate(self):
        def allow_without_caller_gate_assertion(request):
            issued = datetime.now(timezone.utc)
            grant = {
                "authorization_id": "TEST-AUTH-EXTERNAL",
                "principal": request["principal"], "action": request["action"],
                "resource": request["resource"], "scope": list(request["scope"]),
                "conditions": [], "task_id": request["task_id"],
                "policy_version": request["policy_version"], "decision": "ALLOW",
                "issued_at": issued.isoformat(), "expires_at": (issued + timedelta(minutes=5)).isoformat(),
            }
            return {"grant": grant, "trusted_policy_allow": True, "satisfied_conditions": []}

        def trusted_requires_gate(request):
            return {
                "verified": True, "candidate_ref": request.get("candidate_ref"),
                "action": request["action"], "resource": request["resource"],
                "capability_affecting": True,
                "gate_decision": {"status": "PASS", "verified": True,
                                  "candidate_ref": request.get("candidate_ref"),
                                  "policy_version": request["policy_version"],
                                  "gate_id": "gate:test", "evidence_refs": ["evidence:test"]},
            }

        guarded = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=allow_without_caller_gate_assertion,
            live_state_provider=self.live_state,
            applicability_provider=trusted_requires_gate,
            candidate_ref_provider=lambda task_id: "candidate:current",
        )
        request = {
            "principal": "test-runtime-principal", "action": "WRITE",
            "resource": "hg:capability/test", "scope": ["capability:test:write"],
            "task_id": "T-MK-1", "policy_version": POLICY_VERSION,
            "capability_affecting": False,
            "capability_gate": {"applies": False, "reason": "caller assertion under test"},
        }
        with self.assertRaisesRegex(MAEPError, "differs from trusted applicability"):
            guarded._authorize_external_action(request, "T-MK-1")

    def test_external_action_blocks_when_trusted_applicability_requires_gate_without_pass_evidence(self):
        def allow_policy(request):
            issued = datetime.now(timezone.utc)
            grant = {
                "authorization_id": "TEST-AUTH-EXTERNAL-GATE",
                "principal": request["principal"], "action": request["action"],
                "resource": request["resource"], "scope": list(request["scope"]),
                "conditions": [], "task_id": request["task_id"],
                "policy_version": request["policy_version"], "decision": "ALLOW",
                "issued_at": issued.isoformat(), "expires_at": (issued + timedelta(minutes=5)).isoformat(),
            }
            return {"grant": grant, "trusted_policy_allow": True, "satisfied_conditions": []}

        def requires_gate_without_evidence(request):
            return {
                "verified": True, "candidate_ref": request.get("candidate_ref"),
                "action": request["action"], "resource": request["resource"],
                "capability_affecting": True,
            }

        guarded = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=allow_policy, live_state_provider=self.live_state,
            applicability_provider=requires_gate_without_evidence,
            candidate_ref_provider=lambda task_id: "candidate:current",
        )
        request = {
            "principal": "test-runtime-principal", "action": "WRITE",
            "resource": "hg:capability/test", "scope": ["capability:test:write"],
            "task_id": "T-MK-1", "policy_version": POLICY_VERSION,
            "capability_affecting": True,
            "capability_gate": {"applies": True, "reason": "capability evolution"},
        }
        with self.assertRaisesRegex(MAEPError, "applicable MAEP-022 gate lacks verified"):
            guarded._authorize_external_action(request, "T-MK-1")

    def test_read_only_mode_denies_mutations(self):
        readonly = MemoryStore(
            self.db, principal_provider=lambda: "test-runtime-principal",
            policy_evaluator=policy_decision, live_state_provider=self.live_state,
            applicability_provider=applicability_provider_for_test,
            execution_mode="READ_ONLY",
        )
        self.assertEqual(readonly.get_task("T-MK-1")["task"]["state"], "DRAFT")
        with self.assertRaisesRegex(MAEPError, "side effect denied"):
            readonly.transition_task("T-MK-1", "READY", expected_version=1)

    def test_schema_documents_parse(self):
        schema_dir = Path(__file__).resolve().parents[1] / "schemas"
        for name in ("continuity-record.schema.json", "knowledge-record.schema.json"):
            with self.subTest(name=name):
                data = json.loads((schema_dir / name).read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("$id", data)
                self.assertTrue(data["required"])


if __name__ == "__main__":
    unittest.main()
