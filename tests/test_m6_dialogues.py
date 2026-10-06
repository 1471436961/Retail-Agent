"""M6.1 fixed-oracle contract tests plus one isolated native SDK batch."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_dialogue_batch', ROOT/'scripts/local_dialogue_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
BATCH_EVIDENCE = None
PARENT_RUN = None


def synthetic_result(scenario):
    # Oracle-validation fixture only: never reported as an executed dialogue.
    from test_m5_matrix import MatrixBackend
    backend = MatrixBackend()
    initial = batch.apply_patches({'orders':backend.orders,'customers':backend.customers,'products':backend.products}, scenario['setup'])
    calls = []
    turns = []
    for expected in scenario['turns']:
        current = deepcopy(expected.get('http_calls', expected['writes'][len(calls):]+expected['reads']))
        calls = deepcopy(expected['writes'])
        turns.append({'user':expected['user'], 'http_calls':current, 'tool_calls':[],
                      'reply':expected.get('reply_exact', ' '.join(expected.get('reply_contains', []))),
                      'assessment':expected.get('assessment'), 'identity':expected.get('identity', False)})
    return {'id':scenario['id'], 'at_ids':scenario['at_ids'], 'status':'passed', 'context':deepcopy(scenario['context']), 'initial_backend':initial,
            'turns':turns, 'final_backend':batch.apply_patches(initial, scenario['final_patches']),
            'journal':scenario['journal'], 'handoff':scenario['handoff']}


class DialogueOracleTests(unittest.TestCase):
    def setUp(self):
        self.manifest = batch.load_manifest()
        self.requirements = (ROOT/'docs/CASE-REQUIREMENTS.md').read_text(encoding='utf-8')
        self.scenario = next(s for s in self.manifest['scenarios'] if s['id']=='whole_cancellation')
        self.result = synthetic_result(self.scenario)

    def test_complete_plan_keeps_all_134_cases_522_atoms_and_m67_ownership(self):
        plan = batch.build_plan(self.requirements, self.manifest)
        self.assertEqual((len(plan), len({r['case_id'] for r in plan})), (522, 134))
        self.assertTrue(any(not r['dialogue_ids'] for r in plan))
        self.assertTrue(all(r['business_result']=='not_executed' and r['remote_result']=='not_run' for r in plan))
        self.assertTrue(all(r['coverage_milestone']=='M6.7' for r in plan))
        self.assertEqual(next(r for r in plan if r['at_id']=='AT-A017-03')['dialogue_ids'], ['order_address','address_correction'])

    def test_removing_or_duplicating_an_atom_cannot_shrink_the_plan(self):
        atom = next(line for line in self.requirements.splitlines() if line.startswith('- A'))
        for text in (self.requirements.replace(atom,'',1), self.requirements+'\n'+atom):
            with self.assertRaisesRegex(ValueError,'inventory'):
                batch.build_plan(text, self.manifest)

    def test_unknown_or_duplicate_requirement_links_are_rejected(self):
        for ids in (['AT-A999-01'], ['AT-A017-03','AT-A017-03']):
            value = deepcopy(self.manifest); value['scenarios'][0]['at_ids']=ids
            with self.assertRaisesRegex(ValueError,'requirement link'):
                batch.validate_manifest(value,self.requirements)

    def test_duplicate_scenarios_and_noninteger_schema_are_rejected(self):
        for field, value in (('schema_version',True), ('scenarios',self.manifest['scenarios']*2)):
            manifest = deepcopy(self.manifest); manifest[field]=value
            with self.assertRaises(ValueError): batch.validate_manifest(manifest,self.requirements)

    def test_unknown_manifest_or_turn_keys_do_not_grant_extra_behavior(self):
        for location in ('manifest','turn'):
            value = deepcopy(self.manifest)
            target = value if location=='manifest' else value['scenarios'][0]['turns'][0]
            target['confirmed']=True
            with self.assertRaises(ValueError): batch.validate_manifest(value,self.requirements)

    def test_missing_turn_and_reply_only_result_cannot_pass_a_dialogue(self):
        batch.verify_scenario(self.scenario,self.result)
        for value in ({'reply':'success'}, {**self.result,'turns':self.result['turns'][:-1]}):
            with self.assertRaises(ValueError): batch.verify_scenario(self.scenario,value)

    def test_wrong_endpoint_payload_extra_send_and_early_send_fail_fixed_oracles(self):
        for kind in ('path','body','extra','early'):
            value = deepcopy(self.result); calls=value['turns'][-1]['http_calls']
            if kind=='path': calls[0]['path']='/v1/orders/%23TEST3/cancellations'
            if kind=='body': calls[0]['body']['reason']='ordered by mistake'
            if kind=='extra': calls.extend(deepcopy(calls))
            if kind=='early': value['turns'][1]['http_calls']=calls; value['turns'][-1]['http_calls']=[]
            with self.assertRaisesRegex(ValueError,'business calls'): batch.verify_scenario(self.scenario,value)

    def test_current_turn_code_and_identity_have_independent_oracles(self):
        for key, changed in (('assessment',{'kind':'cancellation','code':'unrelated_failure'}),('identity',False)):
            value=deepcopy(self.result)
            index=-1 if key=='assessment' else 0
            value['turns'][index][key]=changed
            with self.assertRaisesRegex(ValueError,key): batch.verify_scenario(self.scenario,value)

    def test_forbidden_read_cannot_hide_inside_a_zero_write_turn(self):
        value=deepcopy(self.result)
        value['turns'][1]['http_calls']=[{'method':'GET','path':'/v1/orders/%23TEST2','body':None}]
        with self.assertRaisesRegex(ValueError,'cross-customer'): batch.verify_scenario(self.scenario,value)

    def test_private_reads_on_declared_zero_http_turns_are_rejected(self):
        scenario=next(s for s in self.manifest['scenarios'] if s['id']=='unverified_order')
        value=synthetic_result(scenario)
        value['turns'][0]['http_calls']=[{'method':'GET','path':'/v1/customers/customer_a','body':None}]
        with self.assertRaisesRegex(ValueError,'must not access'): batch.verify_scenario(scenario,value)

    def test_complete_backend_oracle_detects_target_error_and_unrelated_side_effect(self):
        for key in ('target','unrelated'):
            value=deepcopy(self.result)
            if key=='target': value['final_backend']['orders']['#TEST1']['status']='pending'
            else: value['final_backend']['customers']['customer_a']['email']='changed@example.test'
            with self.assertRaisesRegex(ValueError,'complete fixed oracle'): batch.verify_scenario(self.scenario,value)

    def test_changed_initial_backend_cannot_be_used_to_excuse_an_unrelated_change(self):
        value=deepcopy(self.result)
        value['initial_backend']['customers']['customer_a']['email']='changed@example.test'
        value['final_backend']['customers']['customer_a']['email']='changed@example.test'
        with self.assertRaisesRegex(ValueError,'Initial backend'): batch.verify_scenario(self.scenario,value)

    def test_exact_identity_read_body_and_call_count_cannot_be_substituted(self):
        for kind in ('body','extra'):
            value=deepcopy(self.result)
            if kind=='body': value['turns'][0]['http_calls'][0]['body']={'email':'b@example.test'}
            else: value['turns'][0]['http_calls'].append(deepcopy(value['turns'][0]['http_calls'][-1]))
            with self.assertRaisesRegex(ValueError,'Exact read'): batch.verify_scenario(self.scenario,value)

    def test_unknown_journal_cannot_match_the_fixed_success_oracle(self):
        value=deepcopy(self.result); value['journal'][0]['status']='unknown'
        with self.assertRaisesRegex(ValueError,'journal'): batch.verify_scenario(self.scenario,value)

    def test_success_state_without_a_post_write_owned_readback_is_rejected(self):
        # Keep the fixed read trajectory intact, but move it before the write.
        value=deepcopy(self.result)
        calls=value['turns'][-1]['http_calls']
        value['turns'][-1]['http_calls']=[c for c in calls if c['method']=='GET']+[c for c in calls if c['method']!='GET']
        with self.assertRaisesRegex(ValueError,'post-write readback'): batch.verify_scenario(self.scenario,value)

    def test_wrong_required_transfer_notice_or_terminal_state_is_rejected(self):
        scenario=next(s for s in self.manifest['scenarios'] if s['id']=='human')
        value=synthetic_result(scenario)
        batch.verify_scenario(scenario,value)
        for key in ('reply','handoff'):
            altered=deepcopy(value)
            if key=='reply': altered['turns'][0]['reply']='Transfer started'
            else: altered['handoff']='unknown'
            with self.assertRaises(ValueError): batch.verify_scenario(scenario,altered)

    def test_missing_duplicate_failed_or_stale_batch_results_cannot_be_published(self):
        value={'schema_version':2,'scope':batch.SCOPE,'fixture_sha256':batch.digest(self.manifest),
               'execution':batch.execution_metadata('oracle-test','fixture',mode='oracle_control'),
               'network_attempts':0,'results':[synthetic_result(s) for s in self.manifest['scenarios']]}
        batch.validate_batch(value,self.manifest)
        for kind in ('missing','duplicate','failed','stale','network'):
            altered=deepcopy(value)
            if kind=='missing': altered['results'].pop()
            if kind=='duplicate': altered['results'][1]=deepcopy(altered['results'][0])
            if kind=='failed': altered['results'][0]['status']='skipped'
            if kind=='stale': altered['fixture_sha256']='old'
            if kind=='network': altered['network_attempts']=1
            with self.assertRaises(ValueError): batch.validate_batch(altered,self.manifest)

    def test_passed_wrapper_requires_observations_and_a_matching_test_record(self):
        with self.assertRaisesRegex(ValueError,'missing'):
            batch.trace_dialogues(self.requirements,{'results':{batch.WRAPPER:'passed'}})
        with self.assertRaisesRegex(ValueError,'successful native'):
            batch.trace_dialogues(self.requirements,{'results':{},'dialogue_batch':{}})

    def test_plan_and_oracle_validation_do_not_mutate_fixture_or_observations(self):
        before=deepcopy(self.manifest); result=deepcopy(self.result)
        batch.build_plan(self.requirements,self.manifest); batch.verify_scenario(self.scenario,self.result)
        self.assertEqual(self.manifest,before); self.assertEqual(self.result,result)

    def test_duplicate_allowed_read_changed_body_and_reordering_fail_exact_counts(self):
        for kind in ('extra','body','order'):
            result=deepcopy(self.result); calls=result['turns'][1]['http_calls']
            if kind=='extra': calls.append(deepcopy(calls[0]))
            if kind=='body': calls[0]['body']={'unexpected':True}
            if kind=='order': calls.reverse()
            with self.assertRaisesRegex(ValueError,'Exact read'): batch.verify_scenario(self.scenario,result)

    def test_fixture_scope_can_target_another_owned_order_without_verifier_literals(self):
        scenario=deepcopy(self.scenario)
        scenario['context']['order_ids']=['#TEST3']
        for turn in scenario['turns']:
            turn['user']=turn['user'].replace('#TEST1','#TEST3')
            for call in turn['writes']+turn['reads']:
                call['path']=call['path'].replace('%23TEST1','%23TEST3')
        for patch in scenario['final_patches']:
            patch['path']=[('#TEST3' if key=='#TEST1' else key) for key in patch['path']]
        result=synthetic_result(scenario)
        batch.verify_scenario(scenario,result)
        scenario['context']['order_ids'].append('#TEST1'); result['context']=deepcopy(scenario['context'])
        # Preserve exact read counts while placing target reads before the write.
        writes=batch.business_calls(result['turns'][-1]['http_calls'])
        reads=deepcopy(scenario['turns'][-1]['reads'])
        wrong={'method':'GET','path':'/v1/orders/%23TEST1','body':None}
        scenario['turns'][-1]['reads'].append(wrong)
        result['turns'][-1]['http_calls']=reads+writes+[wrong]
        with self.assertRaisesRegex(ValueError,'post-write readback'): batch.verify_scenario(scenario,result)

    def test_scope_cannot_include_foreign_orders_even_when_oracle_agrees(self):
        scenario=deepcopy(self.scenario); scenario['context']['order_ids'].append('#TEST2')
        result=synthetic_result(scenario)
        with self.assertRaisesRegex(ValueError,'cross-customer order'): batch.verify_scenario(scenario,result)

    def test_conversation_target_and_encoding_come_from_fixed_context(self):
        scenario=deepcopy(next(s for s in self.manifest['scenarios'] if s['id']=='human'))
        scenario['context']['conversation_id']='session/新'
        for turn in scenario['turns']:
            for call in turn['writes']:
                call['path']='/v1/conversations/session%2F%E6%96%B0/transfers'
        result=synthetic_result(scenario); batch.verify_scenario(scenario,result)
        result['context']['conversation_id']='caller-changed'
        with self.assertRaises(ValueError): batch.verify_scenario(scenario,result)
        self.assertEqual(batch.api_path('customers','customer/a'),'/v1/customers/customer%2Fa')

    def test_batch_provenance_requires_exact_runner_sdk_and_input_hashes(self):
        value={'schema_version':2,'scope':batch.SCOPE,'fixture_sha256':batch.digest(self.manifest),
               'execution':batch.execution_metadata('oracle-test','fixture',mode='oracle_control'),
               'network_attempts':0,'results':[synthetic_result(s) for s in self.manifest['scenarios']]}
        batch.validate_batch(value,self.manifest)
        for field, changed in (('runner','elsewhere.py'),('sdk_version','unknown'),('runner_inputs',{}),('mode','native=true')):
            altered=deepcopy(value); altered['execution'][field]=changed
            with self.assertRaisesRegex(ValueError,'provenance'): batch.validate_batch(altered,self.manifest)

    def test_tool_step_limit_accepts_twelfth_and_blocks_thirteenth_before_dispatch(self):
        sent=[]
        for index in range(12):
            batch.tool_step_allowed(index,1); sent.append(index)
        with self.assertRaisesRegex(ValueError,'unbounded'): batch.tool_step_allowed(len(sent),1)
        self.assertEqual(len(sent),12)
        for steps,count in ((True,1),(0,2),(0,0),(-1,1)):
            with self.assertRaises(ValueError): batch.tool_step_allowed(steps,count)


class NativeDialogueBatchTests(unittest.TestCase):
    def test_default_sdk_dialogue_batch_matches_fixed_oracles(self):
        global BATCH_EVIDENCE
        BATCH_EVIDENCE = None
        env = dict(os.environ)
        env.pop('PYTHONPATH',None)
        env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',LITELLM_TELEMETRY='False',LITELLM_LOCAL_MODEL_COST_MAP='True')
        foundation_spec=importlib.util.spec_from_file_location('foundation_trace',ROOT/'scripts/foundation_trace.py')
        foundation=importlib.util.module_from_spec(foundation_spec); foundation_spec.loader.exec_module(foundation)
        parent=PARENT_RUN or {'run_id':uuid4().hex, 'source_sha256':foundation.source_digest()}
        result = subprocess.run([sys.executable,'-B',str(ROOT/'tests/sdk_m6_checks.py'),
                                '--parent-run-id',parent['run_id'],'--source-sha256',parent['source_sha256']],
                                cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr[-6000:])
        self.assertIn('M6_DIALOGUE_SDK_CHECK_PASSED; native SDK/default turns;',result.stdout)
        records=[line.removeprefix('M6_DIALOGUE_JSON=') for line in result.stdout.splitlines() if line.startswith('M6_DIALOGUE_JSON=')]
        self.assertEqual(len(records),1)
        verified=batch.validate_batch(json.loads(records[0]),batch.load_manifest())
        self.assertEqual(verified['execution'],batch.execution_metadata(parent['run_id'],parent['source_sha256']))
        self.assertEqual(len(verified['results']),16)
        self.assertTrue(any(r['journal'] for r in verified['results']))
        BATCH_EVIDENCE = verified  # Published only after all native observations pass.
