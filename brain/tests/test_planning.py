import io
import json
import unittest

from maep.core import POLICY_VERSION
from maep.native_authority import TrustRootRecord
from brain import BrainOrchestrator, OrchestrationError
from brain.planning import (
    LocalOpenAICompatibleProvider,
    PLAN_CONTRACT_VERSION,
    PlanningEngine,
    PlanningError,
    _NoRedirectHandler,
    verify_plan_digest,
)


def make_task(*, state="ASSESSED", policy_version=POLICY_VERSION):
    return {
        "task_id": "task:plan-1",
        "objective": "Safely validate the proposed change",
        "scope": {"include": ["repo://HG"], "exclude": ["repo://HG/secrets"]},
        "inputs": [{"ref_id": "input:spec", "kind": "FILE"}],
        "outputs": ["validated plan"],
        "acceptance_criteria": ["scope is respected", "verification is defined"],
        "evidence_requirements": ["candidate-bound test evidence"],
        "risks": ["wrong candidate"],
        "stop_conditions": ["candidate mismatch", "authorization denied"],
        "next_action": "Plan bounded steps",
        "state": state,
        "policy_version": policy_version,
    }


def make_snapshot(*, state="ASSESSED", policy_status="CURRENT",
                  candidate_ref="sha256:" + "a" * 64,
                  policy_version=POLICY_VERSION):
    return {
        "task": make_task(state=state, policy_version=policy_version),
        "candidate_ref": candidate_ref,
        "policy_status": policy_status,
    }


def valid_candidate():
    return {
        "contract_version": PLAN_CONTRACT_VERSION,
        "task_id": "task:plan-1",
        "objective_summary": "Validate the change within the exact HG repository scope.",
        "assumptions": [],
        # Deliberately reverse input order; the dependency resolver must sort it.
        "steps": [
            {
                "step_id": "S2", "objective": "Capture test evidence",
                "effect_class": "SIDE_EFFECT", "depends_on": ["S1"],
                "resource_ref": "repo://HG", "input_refs": ["input:spec"],
                "expected_output": "Candidate-bound test report",
                "acceptance_criteria_indices": [1],
                "evidence_requirement_indices": [0],
                "verification_method": "Check test exit status and bind the report to the candidate",
                "risk_level": "MEDIUM", "authorization_required": True,
                "preconditions": ["Isolated environment and scoped authorization are present"],
                "recovery_action": "Reconcile live state before any retry",
                "stop_condition": "Stop if candidate identity changes",
            },
            {
                "step_id": "S1", "objective": "Inspect the specification",
                "effect_class": "READ_ONLY", "depends_on": [],
                "resource_ref": "repo://HG", "input_refs": ["input:spec"],
                "expected_output": "A bounded acceptance map",
                "acceptance_criteria_indices": [0],
                "evidence_requirement_indices": [],
                "verification_method": "Compare every acceptance item with the specification",
                "risk_level": "LOW", "authorization_required": False,
                "preconditions": [],
                "recovery_action": "Not applicable; no side effect is performed",
                "stop_condition": "Stop if the requested scope is unclear",
            },
        ],
    }


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else valid_candidate()
        self.error = error
        self.calls = 0
        self.last_user_prompt = None

    def generate_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        self.last_user_prompt = user_prompt
        if self.error:
            raise self.error
        return self.result


class ContextResolver:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def resolve(self, *, refs, candidate_ref, policy_version):
        self.calls.append((refs, candidate_ref, policy_version))
        return self.records


class PlanningAuthority:
    def __init__(self, candidate_ref="sha256:" + "a" * 64, policy_version=POLICY_VERSION,
                 repository="OAI-GIANG/HG", verified=True):
        self.root_store = self.RootStore()
        self.policy_provider = self.PolicyProvider(policy_version)
        self.candidate_provider = self.CandidateProvider(
            candidate_ref, repository=repository, verified=verified
        )

    class RootStore:
        def __init__(self):
            self.root = TrustRootRecord.create(
                root_id="root:planning-test", generation=1,
                created_at="2026-10-23T00:00:00Z",
                bootstrap_authorization_ref="approved:planning-test",
                verification_method="test fixture",
                verification_material_ref="fixture:root",
                policy_change_rule_ref="fixture:policy-rule",
                evidence_ref="fixture:evidence",
            )

        def load_active(self):
            return self.root

    class PolicyProvider:
        def __init__(self, version):
            self.version = version

        def load_active(self, root):
            return {
                "status": "ACTIVE", "version": self.version,
                "root_generation": root.generation, "provenance_verified": True,
                "policy_digest": "sha256:" + "b" * 64,
                "approval_evidence_refs": ["evidence:policy-approved"],
            }

    class CandidateProvider:
        def __init__(self, candidate_ref, *, repository, verified):
            self.candidate_ref = candidate_ref
            self.repository = repository
            self.verified = verified

        def inspect(self, target):
            return {
                "verified": self.verified, "candidate_ref": self.candidate_ref,
                "repository": self.repository,
                "source_manifest_digest": "sha256:" + "c" * 64,
            }


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.engine = PlanningEngine(provider=self.provider)

    def test_bounded_plan_correction_recovers_from_one_invalid_candidate(self):
        invalid = valid_candidate()
        invalid["steps"][0]["resource_ref"] = "repo://HG/secrets"
        class SequenceProvider:
            def __init__(self): self.responses = [invalid, valid_candidate()]; self.calls = 0
            def generate_json(self, **kwargs):
                self.calls += 1
                return self.responses.pop(0)
        provider = SequenceProvider()
        result = PlanningEngine(provider=provider).create_plan(make_snapshot())
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["status"], "VALIDATED_PLAN_NOT_AUTHORIZED")

    def test_plan_correction_is_disabled_when_limit_is_zero(self):
        invalid = valid_candidate()
        invalid["steps"][0]["resource_ref"] = "repo://HG/secrets"
        provider = FakeProvider(invalid)
        engine = PlanningEngine(provider=provider, max_revisions=0)
        with self.assertRaisesRegex(PlanningError, "outside task scope"):
            engine.create_plan(make_snapshot())
        self.assertEqual(provider.calls, 1)

    def test_revision_limit_is_hard_bounded(self):
        with self.assertRaisesRegex(PlanningError, "max_revisions"):
            PlanningEngine(provider=FakeProvider(), max_revisions=2)

    def test_no_redirect_handler_disables_redirects(self):
        handler = _NoRedirectHandler()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://example.com/"))

    def test_valid_plan_is_candidate_bound_and_never_authorizes(self):
        result = self.engine.create_plan(make_snapshot())
        self.assertEqual(result["status"], "VALIDATED_PLAN_NOT_AUTHORIZED")
        self.assertEqual(result["candidate_ref"], "sha256:" + "a" * 64)
        self.assertEqual(result["policy_version"], POLICY_VERSION)
        self.assertEqual(result["execution_order"], ["S1", "S2"])
        self.assertEqual(result["acceptance_coverage"], {"0": ["S1"], "1": ["S2"]})
        self.assertEqual(result["evidence_coverage"], {"0": ["S2"]})
        self.assertEqual(result["authority_effect"], "NONE")
        self.assertFalse(result["side_effects_performed"])
        self.assertFalse(result["ready_to_execute"])
        self.assertTrue(result["plan_digest"].startswith("sha256:"))
        self.assertTrue(verify_plan_digest(result))
        changed = dict(result)
        changed["objective_summary"] = "tampered"
        self.assertFalse(verify_plan_digest(changed))

    def test_requires_canonical_assessed_state(self):
        with self.assertRaisesRegex(PlanningError, "ASSESSED"):
            self.engine.create_plan(make_snapshot(state="RUNNING"))
        self.assertEqual(self.provider.calls, 0)

    def test_stale_policy_blocks_before_model_call(self):
        with self.assertRaisesRegex(PlanningError, "stale"):
            self.engine.create_plan(make_snapshot(policy_status="STALE"))
        self.assertEqual(self.provider.calls, 0)

    def test_missing_candidate_blocks_before_model_call(self):
        snapshot = make_snapshot(candidate_ref="")
        with self.assertRaisesRegex(PlanningError, "candidate binding"):
            self.engine.create_plan(snapshot)
        self.assertEqual(self.provider.calls, 0)

    def test_provider_failure_fails_closed(self):
        engine = PlanningEngine(provider=FakeProvider(error=TimeoutError()))
        with self.assertRaisesRegex(PlanningError, "provider failed"):
            engine.create_plan(make_snapshot())

    def test_out_of_scope_resource_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][0]["resource_ref"] = "repo://HG/secrets"
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "outside task scope"):
            engine.create_plan(make_snapshot())

    def test_missing_acceptance_coverage_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][1]["acceptance_criteria_indices"] = []
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "omits acceptance criterion"):
            engine.create_plan(make_snapshot())

    def test_missing_evidence_coverage_rejected(self):
        candidate = valid_candidate()
        # Make this a non-side-effect-only plan so the global coverage check is reached.
        for step in candidate["steps"]:
            step["effect_class"] = "REASONING"
            step["authorization_required"] = False
            step["preconditions"] = []
            step["evidence_requirement_indices"] = []
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "omits evidence requirement"):
            engine.create_plan(make_snapshot())

    def test_side_effect_without_authorization_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][0]["authorization_required"] = False
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "action-specific MAEP authorization"):
            engine.create_plan(make_snapshot())

    def test_side_effect_without_preconditions_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][0]["preconditions"] = []
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "preconditions"):
            engine.create_plan(make_snapshot())

    def test_cyclic_dependency_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][1]["depends_on"] = ["S2"]
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "cycle"):
            engine.create_plan(make_snapshot())

    def test_unknown_dependency_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][0]["depends_on"] = ["S-MISSING"]
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "unknown step"):
            engine.create_plan(make_snapshot())

    def test_unknown_input_reference_rejected(self):
        candidate = valid_candidate()
        candidate["steps"][0]["input_refs"] = ["invented-ref"]
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "unknown or unverified input"):
            engine.create_plan(make_snapshot())

    def test_unknown_field_rejected(self):
        candidate = valid_candidate()
        candidate["bypass_maep"] = True
        engine = PlanningEngine(provider=FakeProvider(candidate))
        with self.assertRaisesRegex(PlanningError, "unknown or missing top-level"):
            engine.create_plan(make_snapshot())

    def test_duplicate_json_keys_rejected(self):
        raw = '{"contract_version":"hg.plan.v1","contract_version":"evil"}'
        engine = PlanningEngine(provider=FakeProvider(raw))
        with self.assertRaisesRegex(PlanningError, "duplicate JSON keys"):
            engine.create_plan(make_snapshot())

    def test_context_without_resolver_blocked(self):
        with self.assertRaisesRegex(PlanningError, "resolver is unavailable"):
            self.engine.create_plan(make_snapshot(), context_refs=["knowledge:1"])
        self.assertEqual(self.provider.calls, 0)

    def test_context_must_match_candidate_policy_and_have_evidence(self):
        resolver = ContextResolver([{
            "record_id": "knowledge:1", "content": "Verified design fact",
            "source_ref": "memory:record:1", "evidence_refs": ["evidence:1"],
            "verification_status": "VERIFIED", "candidate_ref": "candidate:wrong",
            "policy_version": POLICY_VERSION,
        }])
        engine = PlanningEngine(provider=self.provider, context_resolver=resolver)
        with self.assertRaisesRegex(PlanningError, "provenance/status/candidate/policy mismatch"):
            engine.create_plan(make_snapshot(), context_refs=["knowledge:1"])
        self.assertEqual(self.provider.calls, 0)

    def test_verified_context_is_resolved_and_candidate_bound(self):
        candidate_ref = "sha256:" + "a" * 64
        resolver = ContextResolver([{
            "record_id": "knowledge:1", "content": "Verified design fact",
            "source_ref": "memory:record:1", "evidence_refs": ["evidence:1"],
            "verification_status": "VERIFIED", "candidate_ref": candidate_ref,
            "policy_version": POLICY_VERSION,
        }])
        engine = PlanningEngine(provider=self.provider, context_resolver=resolver)
        result = engine.create_plan(make_snapshot(), context_refs=["knowledge:1"])
        self.assertEqual(result["context_record_refs"], ["knowledge:1"])
        self.assertEqual(resolver.calls, [(["knowledge:1"], candidate_ref, POLICY_VERSION)])
        self.assertIn("verified_context", self.provider.last_user_prompt)

    def test_context_resolver_missing_evidence_rejected(self):
        candidate_ref = "sha256:" + "a" * 64
        resolver = ContextResolver([{
            "record_id": "knowledge:1", "content": "Fact",
            "source_ref": "memory:record:1", "evidence_refs": [],
            "verification_status": "VERIFIED", "candidate_ref": candidate_ref,
            "policy_version": POLICY_VERSION,
        }])
        engine = PlanningEngine(provider=self.provider, context_resolver=resolver)
        with self.assertRaisesRegex(PlanningError, "evidence_refs must not be empty"):
            engine.create_plan(make_snapshot(), context_refs=["knowledge:1"])

    def test_local_provider_rejects_control_characters_in_api_key(self):
        with self.assertRaisesRegex(PlanningError, "printable"):
            LocalOpenAICompatibleProvider(
                endpoint="http://127.0.0.1:8788/v1/chat/completions",
                model="local-model", api_key="bad\x0akey",
            )

    def test_local_provider_rejects_public_endpoint(self):
        with self.assertRaisesRegex(PlanningError, "loopback"):
            LocalOpenAICompatibleProvider(endpoint="http://example.com/v1/chat/completions",
                                          model="local-model")

    def test_local_provider_rejects_credential_smuggling_in_url(self):
        with self.assertRaisesRegex(PlanningError, "loopback"):
            LocalOpenAICompatibleProvider(endpoint="http://user:pass@127.0.0.1:8788/v1/chat/completions",
                                          model="local-model")

    def test_local_provider_uses_loopback_and_extracts_content(self):
        response_body = json.dumps({
            "choices": [{"message": {"content": '{"ok": true}'}}]
        }).encode("utf-8")
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return io.BytesIO(response_body)

        provider = LocalOpenAICompatibleProvider(
            endpoint="http://127.0.0.1:8788/v1/chat/completions",
            model="qwen-local", api_key="test-key", opener=opener,
        )
        result = provider.generate_json(system_prompt="system", user_prompt="user")
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(captured["url"], "http://127.0.0.1:8788/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer test-key")
        self.assertEqual(captured["body"]["temperature"], 0)
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})

    def test_local_provider_rejects_oversized_response(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size=-1): return b"x" * (size + 1)

        provider = LocalOpenAICompatibleProvider(
            endpoint="http://127.0.0.1:8788/v1/chat/completions",
            model="qwen-local", max_response_bytes=1024,
            opener=lambda *args, **kwargs: FakeResponse(),
        )
        with self.assertRaisesRegex(PlanningError, "exceeds size limit"):
            provider.generate_json(system_prompt="system", user_prompt="user")


class BrainPlanningIntegrationTests(unittest.TestCase):
    def test_brain_uses_canonical_task_and_returns_non_authorizing_plan(self):
        class Store:
            def get_task(self, task_id):
                snapshot = make_snapshot()
                snapshot["task"]["task_id"] = task_id
                return snapshot

        class Adapter:
            def __init__(self): self.calls = 0
            def execute(self, **kwargs):
                self.calls += 1
                return {"outcome": "SUCCESS"}

        adapter = Adapter()
        brain = BrainOrchestrator(
            authority=PlanningAuthority(), adapter_registry={"fake": adapter},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
            planning_engine=PlanningEngine(provider=FakeProvider()),
        )
        plan = brain.plan_task(task_ref="task:plan-1", candidate_target="candidate-target")
        self.assertEqual(plan["task_id"], "task:plan-1")
        self.assertFalse(plan["ready_to_execute"])
        self.assertEqual(adapter.calls, 0)

    def test_brain_blocks_planning_when_provider_is_not_configured(self):
        class Store:
            def get_task(self, task_id):
                snapshot = make_snapshot()
                snapshot["task"]["task_id"] = task_id
                return snapshot

        class Adapter:
            def execute(self, **kwargs): raise AssertionError("must not execute")

        brain = BrainOrchestrator(
            authority=PlanningAuthority(), adapter_registry={"fake": Adapter()},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
        )
        with self.assertRaisesRegex(OrchestrationError, "reasoning provider is not configured"):
            brain.plan_task(task_ref="task:plan-1", candidate_target="candidate-target")

    def test_brain_rejects_canonical_task_id_mismatch_before_provider(self):
        class Store:
            def get_task(self, task_id):
                return make_snapshot()

        provider = FakeProvider()
        class Adapter:
            def execute(self, **kwargs): raise AssertionError("must not execute")

        brain = BrainOrchestrator(
            authority=PlanningAuthority(), adapter_registry={"fake": Adapter()},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
            planning_engine=PlanningEngine(provider=provider),
        )
        with self.assertRaisesRegex(OrchestrationError, "task identity mismatch"):
            brain.plan_task(task_ref="task:attacker-selected", candidate_target="candidate-target")
        self.assertEqual(provider.calls, 0)


    def test_brain_blocks_stale_live_policy_before_model_call(self):
        class Store:
            def get_task(self, task_id):
                snapshot = make_snapshot()
                snapshot["task"]["task_id"] = task_id
                return snapshot

        provider = FakeProvider()
        authority = PlanningAuthority(policy_version="MAEP-stale")
        class Adapter:
            def execute(self, **kwargs): raise AssertionError("must not execute")

        brain = BrainOrchestrator(
            authority=authority, adapter_registry={"fake": Adapter()},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
            planning_engine=PlanningEngine(provider=provider),
        )
        with self.assertRaisesRegex(OrchestrationError, "active policy is stale"):
            brain.plan_task(task_ref="task:plan-1", candidate_target="candidate-target")
        self.assertEqual(provider.calls, 0)

    def test_brain_blocks_candidate_mismatch_before_model_call(self):
        class Store:
            def get_task(self, task_id):
                snapshot = make_snapshot()
                snapshot["task"]["task_id"] = task_id
                return snapshot

        provider = FakeProvider()
        authority = PlanningAuthority(candidate_ref="sha256:" + "d" * 64)
        class Adapter:
            def execute(self, **kwargs): raise AssertionError("must not execute")

        brain = BrainOrchestrator(
            authority=authority, adapter_registry={"fake": Adapter()},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
            planning_engine=PlanningEngine(provider=provider),
        )
        with self.assertRaisesRegex(OrchestrationError, "does not match the live candidate"):
            brain.plan_task(task_ref="task:plan-1", candidate_target="candidate-target")
        self.assertEqual(provider.calls, 0)

    def test_brain_blocks_candidate_from_wrong_repository(self):
        class Store:
            def get_task(self, task_id):
                snapshot = make_snapshot()
                snapshot["task"]["task_id"] = task_id
                return snapshot

        provider = FakeProvider()
        authority = PlanningAuthority(repository="OAI-GIANG/HG2")
        class Adapter:
            def execute(self, **kwargs): raise AssertionError("must not execute")

        brain = BrainOrchestrator(
            authority=authority, adapter_registry={"fake": Adapter()},
            idempotency_ledger=object(), receipt_sink=object(), task_store=Store(),
            planning_engine=PlanningEngine(provider=provider),
        )
        with self.assertRaisesRegex(OrchestrationError, "missing or unverified"):
            brain.plan_task(task_ref="task:plan-1", candidate_target="candidate-target")
        self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
