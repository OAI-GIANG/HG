import unittest
from maep.native_authority import Applicability, NativePolicyEngine, TrustRootRecord
from brain import BrainOrchestrator, OrchestrationError

class RootStore:
    def __init__(self):
        self.root = TrustRootRecord.create(root_id='root:1', generation=1, created_at='2026-10-22T10:00:00Z', bootstrap_authorization_ref='approved:1', verification_method='fixture', verification_material_ref='fixture-ref', policy_change_rule_ref='policy-change:1', evidence_ref='ledger:1')
    def load_active(self): return self.root
    def store_active(self, record): self.root = record

class Sink:
    def __init__(self): self.events = []
    def append(self, event):
        self.events.append(event)
        return 'ledger:' + str(len(self.events))

class Principal:
    def resolve(self, context):
        return {'principal_id':'test-owner','status':'ACTIVE','verified':True,'identity_evidence_ref':'identity:test','capabilities':['WRITE'],'resource_scopes':['hg://test/resource'],'allowed_scopes':['fixture']}

class Candidate:
    def __init__(self): self.verified = True; self.ref = 'candidate:1'
    def inspect(self, target):
        if not self.verified: return None
        return {'verified':True,'repository':'OAI-GIANG/HG','source_manifest_digest':'sha256:0000000000000000000000000000000000000000000000000000000000000000','candidate_ref':self.ref}

class Policy:
    def load_active(self, root):
        return {'status':'ACTIVE','version':'policy:1','root_generation':root.generation,'provenance_verified':True,'policy_digest':'sha256:0000000000000000000000000000000000000000000000000000000000000000','approval_evidence_refs':['approval:test'],'grant_ttl_seconds':60,'rules':[{'action':'WRITE','resource':'hg://test/resource','effect':'ALLOW','scope':['fixture']}]}

class ApplicabilityProvider:
    def classify(self, request, candidate):
        return {'verified':True,'classification':Applicability.NOT_REQUIRED.value,'candidate_ref':candidate['candidate_ref'],'action':request['action'],'resource':request['resource'],'applicability_id':'app:1','rule_version':'app-rules:1','facts_used':['action','resource'],'evidence_refs':['app-evidence:1']}

class Gate:
    def __init__(self, status='PASS'):
        self.status = status
    def evaluate(self, request, candidate, policy):
        result = {'status':self.status,'verified':True,'evidence_verified':self.status == 'PASS','evidence_refs':['gate-evidence:1'],'candidate_ref':candidate['candidate_ref'],'policy_version':policy['version'],'gate_id':'gate:1'}
        if self.status == 'PASS':
            refs = ['INV-1', 'CMP-1', 'IMPACT-1', 'REGRESSION-1']
            result['record'] = {
                'decision_id':'MAEP022-brain-e2e', 'candidate_ref':candidate['candidate_ref'],
                'policy_version':policy['version'], 'scope':'isolated E2E fixture',
                'capability':'isolated dispatch capability', 'inventory_status':'COMPLETE',
                'inventory_evidence_refs':[refs[0]], 'overlap_detected':True,
                'comparison_evidence_refs':[refs[1]], 'decision':'EXISTING_REUSE',
                'selected_implementation':'existing implementation',
                'rationale':'Isolated E2E fixture validates the canonical gate path',
                'impact_analysis_refs':[refs[2]], 'regression_test_refs':[refs[3]],
                'gate_status':'PASS',
                'superiority_basis':{key:'isolated test evidence' for key in (
                    'correctness','security','reliability','functional_coverage','compatibility',
                    'performance_resource_cost','maintainability_operational_burden')},
            }
            result['evidence_by_id'] = {
                ref:{'evidence_id':ref,'evidence_type':'TEST_RESULT','source_ref':'test://'+ref,
                     'candidate_ref':candidate['candidate_ref'],'collected_at':'2026-10-22T10:00:00Z',
                     'collector':'isolated-e2e-test','method':'unittest','result':'PASS','limitations':[]}
                for ref in refs
            }
        return result

class TaskStore:
    def __init__(self, state='RUNNING', candidate_ref='candidate:1', policy_status='CURRENT'):
        self.state = state
        self.candidate_ref = candidate_ref
        self.policy_status = policy_status
        self.calls = 0

    def get_task(self, task_id):
        self.calls += 1
        return {
            'task': {
                'task_id': task_id, 'objective': 'bounded test task',
                'scope': {'include': ['fixture', 'hg://test/resource'], 'exclude': []},
                'inputs': [], 'outputs': ['test receipt'],
                'acceptance_criteria': ['effect is authorized and receipted'],
                'evidence_requirements': ['candidate-bound receipt'],
                'risks': ['test-only side effect'], 'stop_conditions': ['authority denied'],
                'next_action': 'verify receipt', 'state': self.state,
                'policy_version': 'MAEP-1.2.0',
            },
            'candidate_ref': self.candidate_ref,
            'row_version': 3,
            'policy_status': self.policy_status,
        }

class IdempotencyLedger:
    def __init__(self): self.claims = {}; self.receipts = {}
    def claim(self, *, idempotency_key, request_digest, decision_digest):
        if idempotency_key in self.claims:
            old = self.claims[idempotency_key]
            return {'status':'CONFLICT' if old['request_digest'] != request_digest else 'DUPLICATE'}
        self.claims[idempotency_key] = {'request_digest':request_digest,'decision_digest':decision_digest}
        return {'status':'RESERVED'}
    def record_outcome(self, *, idempotency_key, request_digest, outcome, receipt):
        self.receipts[idempotency_key] = {'request_digest':request_digest,'outcome':outcome,'receipt':receipt}

class Adapter:
    def __init__(self, timeout=False): self.calls = 0; self.timeout = timeout
    def execute(self, **kwargs):
        self.calls += 1
        if self.timeout: raise TimeoutError()
        return {'outcome':'SUCCESS','idempotent':False,'provider_ref':'fixture-effect'}

class BrainTests(unittest.TestCase):
    def setUp(self):
        self.root = RootStore(); self.candidate = Candidate(); self.auth_sink = Sink(); self.receipt_sink = Sink()
        self.idempotency = IdempotencyLedger(); self.adapter = Adapter(); self.task_store = TaskStore()
        authority = NativePolicyEngine(root_store=self.root, principal_provider=Principal(), candidate_provider=self.candidate, policy_provider=Policy(), applicability_provider=ApplicabilityProvider(), gate_provider=Gate(), evidence_sink=self.auth_sink)
        self.brain = BrainOrchestrator(authority=authority, adapter_registry={'test':self.adapter}, idempotency_ledger=self.idempotency, receipt_sink=self.receipt_sink, task_store=self.task_store)
        self.request = {'action':'WRITE','resource':'hg://test/resource','task_ref':'task:1','scope':['fixture']}
    def dispatch(self, key='idem:1'):
        return self.brain.dispatch(request=self.request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='test', idempotency_key=key)
    def test_non_running_canonical_task_blocks_before_effect(self):
        self.task_store.state = 'DRAFT'
        with self.assertRaisesRegex(OrchestrationError, 'canonical MAEP task contract'):
            self.dispatch(key='idem:task-not-running')
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.idempotency.claims, {})

    def test_stale_task_policy_blocks_before_effect(self):
        self.task_store.policy_status = 'STALE'
        with self.assertRaisesRegex(OrchestrationError, 'canonical MAEP task contract'):
            self.dispatch(key='idem:task-policy-stale')
        self.assertEqual(self.adapter.calls, 0)

    def test_task_candidate_mismatch_blocks_before_effect(self):
        self.task_store.candidate_ref = 'candidate:old'
        with self.assertRaisesRegex(OrchestrationError, 'canonical MAEP task contract'):
            self.dispatch(key='idem:task-candidate-mismatch')
        self.assertEqual(self.adapter.calls, 0)

    def test_task_scope_mismatch_blocks_before_effect(self):
        self.task_store.get_task = lambda task_id: {
            'task': {
                'task_id': task_id, 'objective': 'bounded test task',
                'scope': {'include': ['different-scope'], 'exclude': []},
                'inputs': [], 'outputs': ['receipt'], 'acceptance_criteria': ['authorized'],
                'evidence_requirements': ['receipt'], 'risks': ['test'],
                'stop_conditions': ['deny'], 'next_action': 'verify',
                'state': 'RUNNING', 'policy_version': 'MAEP-1.2.0',
            }, 'candidate_ref': 'candidate:1', 'row_version': 3, 'policy_status': 'CURRENT'
        }
        with self.assertRaisesRegex(OrchestrationError, 'canonical MAEP task contract'):
            self.dispatch(key='idem:task-scope-mismatch')
        self.assertEqual(self.adapter.calls, 0)

    def test_deny_before_effect_when_candidate_unverified(self):
        self.candidate.verified = False
        with self.assertRaisesRegex(OrchestrationError, 'BLOCKED before side effect'): self.dispatch()
        self.assertEqual(self.adapter.calls, 0)
    def test_gate_revocation_between_authorize_and_effect_blocks_dispatch(self):
        class RequiredApplicability:
            def classify(self, request, candidate):
                return {'verified':True,'classification':Applicability.REQUIRED.value,'candidate_ref':candidate['candidate_ref'],'action':request['action'],'resource':request['resource'],'applicability_id':'app:required','rule_version':'app-rules:1','facts_used':['action','resource'],'evidence_refs':['app-evidence:1']}
        class RevokingGate:
            def __init__(self): self.calls = 0
            def evaluate(self, request, candidate, policy):
                self.calls += 1
                status = 'PASS' if self.calls == 1 else 'BLOCKED'
                result = {'status':status,'verified':True,'evidence_verified':True,'evidence_refs':['gate-evidence:1'],'candidate_ref':candidate['candidate_ref'],'policy_version':policy['version'],'gate_id':'gate:1'}
                if status == 'PASS':
                    refs = ['INV-1', 'CMP-1', 'IMPACT-1', 'REGRESSION-1']
                    result['record'] = {
                        'decision_id':'MAEP022-brain-test', 'candidate_ref':candidate['candidate_ref'],
                        'policy_version':policy['version'], 'scope':'test scope', 'capability':'test capability',
                        'inventory_status':'COMPLETE', 'inventory_evidence_refs':[refs[0]],
                        'overlap_detected':True, 'comparison_evidence_refs':[refs[1]],
                        'decision':'EXISTING_REUSE', 'selected_implementation':'existing implementation',
                        'rationale':'Test evidence supports reuse', 'impact_analysis_refs':[refs[2]],
                        'regression_test_refs':[refs[3]], 'gate_status':'PASS',
                        'superiority_basis':{key:'evidence-backed test rationale' for key in (
                            'correctness','security','reliability','functional_coverage','compatibility',
                            'performance_resource_cost','maintainability_operational_burden')},
                    }
                    result['evidence_by_id'] = {
                        ref:{'evidence_id':ref,'evidence_type':'TEST_RESULT','source_ref':'test://'+ref,
                             'candidate_ref':candidate['candidate_ref'],'collected_at':'2026-10-22T10:00:00Z',
                             'collector':'unit-test','method':'unittest','result':'PASS','limitations':[]}
                        for ref in refs
                    }
                return result
        self.brain.authority.applicability_provider = RequiredApplicability()
        gate = RevokingGate()
        self.brain.authority.gate_provider = gate
        with self.assertRaisesRegex(OrchestrationError, 'fresh authorization denied'):
            self.dispatch()
        self.assertEqual(gate.calls, 2)
        self.assertEqual(self.adapter.calls, 0)

    def test_maep022_required_gate_denies_before_any_effect_and_records_deny_receipt(self):
        class RequiredApplicability:
            def classify(self, request, candidate):
                return {'verified': True, 'classification': Applicability.REQUIRED.value,
                        'candidate_ref': candidate['candidate_ref'], 'action': request['action'],
                        'resource': request['resource'], 'applicability_id': 'app:e2e-deny',
                        'rule_version': 'app-rules:e2e', 'facts_used': ['action', 'resource'],
                        'evidence_refs': ['app-evidence:e2e']}
        self.brain.authority.applicability_provider = RequiredApplicability()
        self.brain.authority.gate_provider = Gate(status='BLOCKED')
        with self.assertRaisesRegex(OrchestrationError, 'BLOCKED before side effect'):
            self.dispatch(key='idem:maep022-deny')
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.receipt_sink.events[-1]['payload']['outcome'], 'BLOCKED')
        self.assertEqual(self.receipt_sink.events[-1]['payload']['candidate_ref'], self.candidate.ref)

    def test_maep022_current_pass_allows_once_with_bound_receipt_and_replay_blocked(self):
        class RequiredApplicability:
            def classify(self, request, candidate):
                return {'verified': True, 'classification': Applicability.REQUIRED.value,
                        'candidate_ref': candidate['candidate_ref'], 'action': request['action'],
                        'resource': request['resource'], 'applicability_id': 'app:e2e-allow',
                        'rule_version': 'app-rules:e2e', 'facts_used': ['action', 'resource'],
                        'evidence_refs': ['app-evidence:e2e']}
        self.brain.authority.applicability_provider = RequiredApplicability()
        # Gate() builds canonical evidence bound to the current fixture candidate and policy.
        self.brain.authority.gate_provider = Gate(status='PASS')
        receipt = self.dispatch(key='idem:maep022-current-pass')
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(receipt['candidate_ref'], self.candidate.ref)
        self.assertEqual(receipt['policy_version'], 'policy:1')
        self.assertEqual(receipt['outcome'], 'SUCCESS')
        self.assertEqual(self.idempotency.receipts['idem:maep022-current-pass']['receipt'], receipt)
        self.assertEqual(self.receipt_sink.events[-1]['payload'], receipt)
        with self.assertRaisesRegex(OrchestrationError, 'duplicate'):
            self.dispatch(key='idem:maep022-current-pass')
        self.assertEqual(self.adapter.calls, 1)

    def test_authorized_dispatch_records_receipt(self):
        receipt = self.dispatch()
        self.assertEqual(receipt['outcome'], 'SUCCESS'); self.assertEqual(self.adapter.calls, 1)
        self.assertIn('idem:1', self.idempotency.receipts); self.assertTrue(self.receipt_sink.events)
    def test_duplicate_idempotency_key_does_not_dispatch_twice(self):
        self.dispatch()
        with self.assertRaisesRegex(OrchestrationError, 'duplicate'): self.dispatch()
        self.assertEqual(self.adapter.calls, 1)
    def test_timeout_is_unknown_not_failure(self):
        self.brain.adapter_registry['timeout'] = Adapter(timeout=True)
        with self.assertRaisesRegex(OrchestrationError, 'OUTCOME_UNKNOWN'):
            self.brain.dispatch(request=self.request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='timeout', idempotency_key='idem:timeout')
        self.assertEqual(self.idempotency.receipts['idem:timeout']['outcome'], 'UNKNOWN')
    def test_unknown_adapter_rejected(self):
        with self.assertRaisesRegex(OrchestrationError, 'not registered'):
            self.brain.dispatch(request=self.request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='unknown', idempotency_key='idem:unknown')
        self.assertEqual(self.adapter.calls, 0)

    def test_tools_contract_rejects_missing_scope_before_authority_or_adapter(self):
        request = dict(self.request)
        request.pop('scope')
        before = len(self.auth_sink.events)
        with self.assertRaisesRegex(OrchestrationError, 'invalid tools-and-automation request'):
            self.brain.dispatch(request=request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='test', idempotency_key='idem:no-scope')
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(len(self.auth_sink.events), before)

    def test_malformed_adapter_result_is_unknown_and_receipted(self):
        class MalformedAdapter:
            def __init__(self): self.calls = 0
            def execute(self, **kwargs):
                self.calls += 1
                return {'outcome': 'SUCCESS', 'provider_ref': '../invalid'}
        adapter = MalformedAdapter()
        self.brain.adapter_registry['malformed'] = adapter
        with self.assertRaisesRegex(OrchestrationError, 'OUTCOME_UNKNOWN'):
            self.brain.dispatch(request=self.request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='malformed', idempotency_key='idem:malformed')
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(self.idempotency.receipts['idem:malformed']['outcome'], 'UNKNOWN')
        self.assertEqual(self.idempotency.receipts['idem:malformed']['receipt']['adapter_receipt']['outcome'], 'UNKNOWN')

    def test_adapter_result_unknown_is_not_promoted_to_success(self):
        class UnknownAdapter:
            def execute(self, **kwargs):
                return {'outcome': 'UNKNOWN', 'idempotent': False}
        self.brain.adapter_registry['unknown-result'] = UnknownAdapter()
        with self.assertRaisesRegex(OrchestrationError, 'OUTCOME_UNKNOWN'):
            self.brain.dispatch(request=self.request, authenticated_context='fixture-session', candidate_target='candidate-target', adapter_name='unknown-result', idempotency_key='idem:unknown-result')
        self.assertEqual(self.idempotency.receipts['idem:unknown-result']['outcome'], 'UNKNOWN')

if __name__ == '__main__': unittest.main()
