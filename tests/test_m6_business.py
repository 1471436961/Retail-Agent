"""Direct acceptance validator controls and isolated native M6.7 execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('business_acceptance', ROOT/'scripts/business_acceptance.py')
contract = importlib.util.module_from_spec(spec); spec.loader.exec_module(contract)
BATCH_EVIDENCE = None
PARENT_RUN = None


class BusinessContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = contract.load_manifest()
        self.specification = contract.requirements()

    def test_inventory_retains_all_atoms_and_does_not_promote_fixed_claims_before_execution(self):
        value = contract.coverage(self.manifest)
        self.assertEqual(len(value['plan']), 522)
        self.assertEqual({r['case_id'] for r in value['plan']}, set(range(134)))
        self.assertEqual(value['ats_passed_local'], 0)
        self.assertEqual(value['cases_complete_local'], 0)
        self.assertEqual(value['status'], 'in_progress')
        self.assertTrue(all(r['business_result']=='not_executed' for r in value['plan']))
        self.assertTrue(all(r['remote_result']=='not_run' for r in value['plan']))
        self.assertTrue(all(r['predicate_review']['predicate_ids'] for r in value['plan']))
        self.assertNotIn('passed_local', json.dumps(value['predicate_review_index']))
        self.assertTrue(all(r['observation_result'] == 'not_executed'
                            for r in value['predicate_review_index']['predicates'].values()))

    def test_changed_removed_or_duplicate_requirement_cannot_reuse_manifest(self):
        atom = next(line for line in self.specification.splitlines() if line.startswith('- A'))
        for altered in (self.specification.replace(atom, '', 1), self.specification+'\n'+atom,
                        self.specification.replace(atom, atom+' revised', 1)):
            with self.assertRaises(ValueError): contract.validate_manifest(self.manifest, altered)

    def test_association_without_direct_whole_atom_assertions_is_rejected(self):
        for field, value in (('requirement','related components passed'), ('witnesses',[]), ('substitution','')):
            altered=deepcopy(self.manifest); altered['atoms'][0][field]=value
            with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)
        altered=deepcopy(self.manifest); altered['atoms'][0]['witnesses'][0]['assertions']=[]
        with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)

    def test_duplicate_atom_or_scenario_witness_cannot_inflate_acceptance(self):
        altered=deepcopy(self.manifest); altered['atoms'].append(deepcopy(altered['atoms'][0]))
        with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)
        altered=deepcopy(self.manifest); altered['atoms'][0]['witnesses'].append(deepcopy(altered['atoms'][0]['witnesses'][0]))
        with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)

    def test_scenario_link_must_have_matching_atomic_witness(self):
        altered=deepcopy(self.manifest); altered['dialogues']['scenarios'][0]['at_ids'].append('AT-A000-01')
        with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)
        altered=deepcopy(self.manifest); altered['atoms'][0]['witnesses'][0]['scenario']='missing'
        with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)

    def test_actual_direct_predicates_reject_wrong_values_missing_paths_and_boolean_numbers(self):
        check={'path':['basis','selected'],'op':'equal','expected':'boot_original'}
        contract.assert_observation({'basis':{'selected':'boot_original'}},check)
        for value in ({'basis':{'selected':'boot_wrong_color'}}, {'basis':{}}, {}):
            with self.assertRaises(ValueError): contract.assert_observation(value,check)
        with self.assertRaises(ValueError):
            contract.assert_observation({'count':True},{'path':['count'],'op':'equal','expected':1})

    def test_contains_predicate_checks_customer_text_instead_of_success_label(self):
        check={'path':['reply'],'op':'contains','expected':'hard'}
        contract.assert_observation({'reply':'Synthetic puzzle: hard, 500 pieces, art'},check)
        with self.assertRaises(ValueError): contract.assert_observation({'reply':'passed'},check)

    def test_malformed_paths_ops_and_nan_expected_values_are_refused(self):
        for field,value in (('path',[]),('path',['evidence',True]),('path',['evidence',-1]),
                            ('op','trust_reported_status'),('expected',float('nan'))):
            altered=deepcopy(self.manifest); altered['atoms'][0]['witnesses'][0]['assertions'][0][field]=value
            with self.assertRaises(ValueError): contract.validate_manifest(altered,self.specification)

    def test_claimed_wrapper_without_native_observations_is_not_business_execution(self):
        with self.assertRaisesRegex(ValueError,'Missing native'):
            contract.trace_business({'results':{contract.WRAPPER:'passed'}})
        with self.assertRaisesRegex(ValueError,'executed native wrapper'):
            contract.trace_business({'results':{},'source_files':{contract.FIXTURE:'fake'}})
        self.assertIsNone(contract.trace_business({'results':{},'source_files':{}}))

    def test_forged_provenance_and_network_attempt_do_not_publish(self):
        parent={'run_id':'control','source_sha256':'control'}
        value={'scope':contract.SCOPE,'execution':contract.metadata(parent),'network_attempts':0,'results':[]}
        for field,changed in (('network_attempts',1),('network_attempts',False),('execution',{}),('scope','complete classroom success')):
            altered=deepcopy(value); altered[field]=changed
            with self.assertRaises(ValueError): contract.validate_batch(altered,self.manifest,parent)

    def test_historical_source_baseline_requires_explicit_before_after_bytes_and_reason(self):
        value=json.loads((ROOT/contract.SOURCE_CHANGES).read_text(encoding='utf-8'))
        baseline=json.loads((ROOT/contract.BASELINE).read_text(encoding='utf-8'))
        current={k:hashlib.sha256((ROOT/k).read_bytes()).hexdigest() for k in baseline['source_files']}
        self.assertEqual(contract.validate_source_changes(value,baseline,current)['unchanged_files'],46)
        for change in ('before','after','reason','duplicate','missing'):
            bad=deepcopy(value)
            if change=='before':bad['changes'][0]['before_sha256']='0'*64
            if change=='after':bad['changes'][0]['after_sha256']='0'*64
            if change=='reason':bad['changes'][0]['reason']=''
            if change=='duplicate':bad['changes'].append(deepcopy(bad['changes'][0]))
            if change=='missing':bad['changes'].pop()
            with self.subTest(change=change),self.assertRaises(ValueError):
                contract.validate_source_changes(bad,baseline,current)

    def test_unrecorded_file_or_old_dialogue_change_cannot_hide_in_approved_delta(self):
        value=json.loads((ROOT/contract.SOURCE_CHANGES).read_text(encoding='utf-8'))
        baseline=json.loads((ROOT/contract.BASELINE).read_text(encoding='utf-8'))
        current={k:hashlib.sha256((ROOT/k).read_bytes()).hexdigest() for k in baseline['source_files']}
        for path in ('agent/agent.py','tests/fixtures/m6_dialogues.json','tests/fixtures/m6_combinations.json','agent/unapproved.py'):
            changed=dict(current);changed[path]='0'*64
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'Unrecorded'):
                contract.validate_source_changes(value,baseline,changed)


class PredicateReviewTests(unittest.TestCase):
    def control(self):
        check = {'path': ['initial_backend', 'orders', '#A', 'items'], 'op': 'equal', 'expected': ['red']}
        return {'atoms': [
            {'at_id': 'AT-A', 'witnesses': [{'scenario': 'one', 'assertions': [deepcopy(check)]}]},
            {'at_id': 'AT-B', 'witnesses': [{'scenario': 'one', 'assertions': [deepcopy(check),
                {'path': ['turns', 2, 'reply'], 'op': 'contains', 'expected': 'confirm'}]}]},
            {'at_id': 'AT-C', 'witnesses': [{'scenario': 'two', 'assertions': [deepcopy(check)]}]}]}

    def test_predicate_ids_survive_atom_and_assertion_reordering(self):
        manifest = self.control()
        before = contract.predicate_review_index(manifest)
        manifest['atoms'].reverse()
        for atom in manifest['atoms']:
            for witness in atom['witnesses']: witness['assertions'].reverse()
        self.assertEqual(contract.predicate_review_index(manifest), before)

    def test_scenario_path_operator_and_expected_each_change_predicate_identity(self):
        original = self.control(); original['atoms'] = original['atoms'][:1]
        before = set(contract.predicate_review_index(original)['predicates'])
        for field, value in (('scenario', 'other'), ('path', ['final_backend', 'orders']),
                             ('op', 'contains'), ('expected', ['blue'])):
            changed = deepcopy(original)
            witness = changed['atoms'][0]['witnesses'][0]
            if field == 'scenario': witness[field] = value
            else: witness['assertions'][0][field] = value
            with self.subTest(field=field):
                self.assertTrue(before.isdisjoint(contract.predicate_review_index(changed)['predicates']))

    def test_shared_predicate_reports_actual_atomic_users_without_merging_scenarios(self):
        index = contract.predicate_review_index(self.control())
        self.assertEqual((index['assertion_occurrences'], index['distinct_predicates'],
                          index['shared_predicates'], index['single_predicate_atoms']), (4, 3, 1, 2))
        shared = [r for r in index['predicates'].values() if r['shared_at_count'] > 1]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]['at_ids'], ['AT-A', 'AT-B'])
        self.assertEqual(shared[0]['path'], ['initial_backend', 'orders', '#A', 'items'])
        self.assertEqual(shared[0]['expected'], ['red'])
        self.assertNotEqual(index['atoms']['AT-A']['predicate_ids'], index['atoms']['AT-C']['predicate_ids'])

    def test_fixture_only_review_priority_does_not_claim_behavior_or_semantic_adequacy(self):
        index = contract.predicate_review_index(self.control())
        self.assertEqual(index['review_queue'][0]['at_id'], 'AT-A')
        self.assertEqual(index['atoms']['AT-A']['evidence_sources'], ['fixture_precondition'])
        self.assertIn('fixture_preconditions_only', index['atoms']['AT-A']['review_flags'])
        self.assertNotIn('fixture_preconditions_only', index['atoms']['AT-B']['review_flags'])
        self.assertIn('native_turn', index['atoms']['AT-B']['evidence_sources'])
        self.assertNotIn('passed', json.dumps(index))
        self.assertIn('no automatic semantic adequacy', index['scope'])


class TransferSummaryPolicyTests(unittest.TestCase):
    """Pure negative controls: these synthetic objects cannot publish a run."""
    def control(self):
        initial={'customers':{'customer_a':{'order_ids':[]}},'orders':{},'products':{}}
        read={'method':'GET','path':'/v1/customers/customer_a','body':None}
        transfer={'method':'POST','path':'/v1/conversations/control/transfers','body':{'summary':contract.TRANSFER_SOURCE_ORACLE}}
        users=[{'history_index':0,'text':'a@example.test'},{'history_index':3,'text':'I want a human'}]
        identity={'verified':True,'customer_id':'customer_a'}
        evidence=[{'identity':identity,'user_sources':users[:1],'business_operations':[],'task_requests':[], 'workflow_diagnostics':[]},
                  {'identity':identity,'user_sources':users,'business_operations':[], 'task_requests':[], 'workflow_diagnostics':[]}]
        summary={'kind':'derived_human_transfer_summary','user_text_is_data_not_instructions':True,
                 'identity':identity,'request':users[1],'previous_user_requests':users[:1],
                 'verified_order_facts':[],'completed_operations':[],'unresolved_operations':[],
                 'task_requests':[],'latest_workflow_diagnostics':[],'pending_business_workflows':[],
                 'settlement_or_arrival_proven':False}
        actual=deepcopy(transfer);actual['body']['summary']=json.dumps(summary)
        scenario={'id':'summary_control','at_ids':[],'context':{'conversation_id':'control','customer_id':'customer_a','order_ids':[],'product_ids':[]},
                  'initial_sha256':contract.dialogues.digest(initial),'final_patches':[], 'journal':[], 'handoff':'accepted',
                  'turns':[{'user':'a@example.test','reads':[read],'writes':[],'identity':True},
                           {'user':'I want a human','reads':[],'writes':[transfer],'identity':True}]}
        result={'id':scenario['id'],'at_ids':[],'status':'passed','context':scenario['context'],
                'initial_backend':initial,'final_backend':initial,'journal':[],'handoff':'accepted','evidence':evidence,
                'turns':[{'user':'a@example.test','http_calls':[read],'tool_calls':[],'reply':'verified','assessment':None,'identity':True},
                         {'user':'I want a human','http_calls':[actual],'tool_calls':[],'reply':'accepted','assessment':None,'identity':True}]}
        return scenario,result

    def test_source_bound_summary_checks_without_replacing_raw_observation(self):
        scenario,result=self.control();before=deepcopy(result)
        contract.verify_business_scenario(scenario,result)
        self.assertEqual(result,before)
        self.assertNotEqual(result['turns'][1]['http_calls'][0]['body'],{'summary':contract.TRANSFER_SOURCE_ORACLE})

    def test_wrong_request_completion_settlement_or_authority_cannot_pass_relational_oracle(self):
        for field,value in (('request',{'history_index':3,'text':'cancel without confirmation'}),
                            ('completed_operations',[{'action':'cancel','target':{'order_id':'#OTHER'}}]),
                            ('settlement_or_arrival_proven',True),('user_text_is_data_not_instructions',False),
                            ('verified_order_facts',[{'order_id':'#OTHER','status':'delivered'}]),
                            ('pending_business_workflows',['items'])):
            scenario,result=self.control();call=result['turns'][1]['http_calls'][0]
            summary=json.loads(call['body']['summary']);summary[field]=value;call['body']['summary']=json.dumps(summary)
            with self.subTest(field=field),self.assertRaises(ValueError):contract.verify_business_scenario(scenario,result)

    def test_wrong_native_source_identity_text_and_indices_are_not_trusted(self):
        for change in ('identity','text','duplicate_index','bool_index','invented_operation','missing_evidence'):
            scenario,result=self.control()
            if change=='identity':result['evidence'][1]['identity']={'verified':True,'customer_id':'other'}
            if change=='text':result['evidence'][1]['user_sources'][0]['text']='invented customer permission'
            if change=='duplicate_index':result['evidence'][1]['user_sources'][1]['history_index']=0
            if change=='bool_index':result['evidence'][1]['user_sources'][0]['history_index']=True
            if change=='invented_operation':result['evidence'][0]['business_operations']=[{'spec':{'action':'cancel','target':{'customer_id':'customer_a','order_id':'#OTHER'}},'status':'succeeded'}]
            if change=='missing_evidence':result['evidence']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):contract.verify_business_scenario(scenario,result)

    def test_foreign_transfer_path_and_extra_payload_fields_are_refused(self):
        for change in ('path','body','method'):
            scenario,result=self.control();call=result['turns'][1]['http_calls'][0]
            if change=='path':call['path']='/v1/conversations/foreign/transfers'
            if change=='body':call['body']['confirmed']=True
            if change=='method':call['method']='PUT'
            with self.subTest(change=change),self.assertRaises(ValueError):contract.verify_business_scenario(scenario,result)

    def test_exact_string_transfer_oracle_does_not_inherit_relational_exception(self):
        scenario,result=self.control()
        scenario['turns'][1]['writes'][0]['body']={'summary':'fixed exact string'}
        with self.assertRaises(ValueError):contract.verify_business_scenario(scenario,result)

    def test_relational_marker_is_rejected_outside_trusted_transfer_target(self):
        manifest=contract.load_manifest()
        marker=next((i,j,k) for i,s in enumerate(manifest['dialogues']['scenarios']) for j,t in enumerate(s['turns']) for k,c in enumerate(t['writes']) if c['body']=={'summary':contract.TRANSFER_SOURCE_ORACLE})
        for method,path in (('PUT','/v1/orders/%23TEST1/shipping-address'),('POST','/v1/conversations/foreign/transfers')):
            bad=deepcopy(manifest);i,j,k=marker;call=bad['dialogues']['scenarios'][i]['turns'][j]['writes'][k]
            call.update(method=method,path=path)
            with self.assertRaises(ValueError):contract.validate_manifest(bad,contract.requirements())


class NativeBusinessTests(unittest.TestCase):
    def test_native_default_business_scenarios_match_direct_atomic_assertions(self):
        global BATCH_EVIDENCE
        BATCH_EVIDENCE=None
        env=dict(os.environ); env.pop('PYTHONPATH',None)
        env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',LITELLM_TELEMETRY='False',LITELLM_LOCAL_MODEL_COST_MAP='True')
        foundation_spec=importlib.util.spec_from_file_location('foundation_trace',ROOT/'scripts/foundation_trace.py')
        foundation=importlib.util.module_from_spec(foundation_spec); foundation_spec.loader.exec_module(foundation)
        parent=PARENT_RUN or {'run_id':uuid4().hex,'source_sha256':foundation.source_digest()}
        result=subprocess.run([sys.executable,'-B',str(ROOT/contract.RUNNER),
                               '--parent-run-id',parent['run_id'],'--source-sha256',parent['source_sha256']],
                              cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True,timeout=1800)
        self.assertEqual(result.returncode,0,result.stderr[-5000:])
        self.assertIn('M6_BUSINESS_CHECK_PASSED;',result.stdout)
        rows=[line.removeprefix('M6_BUSINESS_JSON=') for line in result.stdout.splitlines() if line.startswith('M6_BUSINESS_JSON=')]
        self.assertEqual(len(rows),1)
        value=contract.validate_batch(json.loads(rows[0]),contract.load_manifest(),parent)
        coverage=contract.coverage(contract.load_manifest(),value,parent=parent)
        self.assertEqual((coverage['ats_passed_local'],coverage['ats_not_executed']), (522,0))
        self.assertEqual(coverage['cases_complete_local'],134)
        self.assertEqual(coverage['status'],'complete_local')
        report={**parent,'results':{contract.WRAPPER:'passed'},'business_batch':value,
                'source_files':foundation.source_file_hashes()}
        published=contract.trace_business(report)
        self.assertEqual(published['plan'],coverage['plan'])
        self.assertEqual(published['ats_passed_local'],522)
        self.assertEqual(published['predicate_review_index'],coverage['predicate_review_index'])
        self.assertEqual(set(published['predicate_review_index']['atoms']),
                         {row['at_id'] for row in published['plan']})
        self.assertTrue(all(row['observation_result'] == 'passed_local'
                            for row in published['predicate_review_index']['predicates'].values()))
        changed=deepcopy(report)
        changed['source_files'][contract.FIXTURE]='0'*64
        with self.assertRaisesRegex(ValueError,'input hash'):
            contract.trace_business(changed)
        # Fixed native observation negative controls, not republished as runs.
        for change in ('missing','duplicate','failed','predicate','recap','extra_read','final_backend','evidence','parent'):
            altered=deepcopy(value)
            if change=='missing': altered['results'].pop()
            if change=='duplicate': altered['results'][1]=deepcopy(altered['results'][0])
            if change=='failed': altered['results'][0]['status']='failed'
            if change=='predicate': altered['results'][0]['evidence'][2]['basis']['exchange']['spec']['parameters']['replacements'][0]['replacement_item_id']='boot_wrong_color'
            if change=='recap': altered['results'][0]['turns'][2]['reply']='Please confirm; incomplete list and no amount or method.'
            if change=='extra_read': altered['results'][0]['turns'][1]['http_calls'].append(deepcopy(altered['results'][0]['turns'][1]['http_calls'][-1]))
            if change=='final_backend': altered['results'][0]['final_backend']['orders']['#TEST2']['status']='cancelled'
            if change=='evidence': altered['results'][0]['evidence'].pop()
            if change=='parent': altered['execution']['run_id']='foreign'
            with self.subTest(change=change):
                with self.assertRaises(ValueError): contract.validate_batch(altered,contract.load_manifest(),parent)
        BATCH_EVIDENCE=value
