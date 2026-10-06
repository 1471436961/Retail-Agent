"""M6.3 fixed replay evidence controls plus an isolated real SDK worker.

Oracle controls below validate rejection behavior, never publish observations.
The native wrapper is the only writer of BATCH_EVIDENCE.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from test_m6_dialogues import batch as dialogues, synthetic_result

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('replay_contract', ROOT/'scripts/local_replay_batch.py')
replay = importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)
BATCH_EVIDENCE = None
PARENT_RUN = None


def oracle_control(run_id='control', source='fixture'):
    manifest = dialogues.load_manifest()
    rows = []
    for scenario in manifest['scenarios']:
        result = synthetic_result(scenario)
        frames = [{'event': event, 'message': 'a'*64, 'evidence': 'b'*64, 'http_calls': 'c'*64}
                  for _ in scenario['turns'] for event in ('user', 'reply')]
        trajectory = {'initial_backend': replay.digest(result['initial_backend']),
                      'final_backend': replay.digest(result['final_backend']), 'result': result, 'frames': frames}
        rows.append({'id': scenario['id'], 'first': deepcopy(trajectory), 'rebuilt': deepcopy(trajectory),
                     'checkpoints': 2*len(scenario['turns'])})
    faults = []
    for sid, kind, action in replay.FAULT_CASES:
        for mode in replay.FAULT_MODES:
            status = ('accepted' if kind == 'handoff' else 'succeeded') if mode == 'duplicate_receipt' else 'unknown'
            faults.append({'id': sid, 'kind': kind, 'action': action, 'mode': mode, 'sends': 1, 'extra_sends': 0,
                           'status': status, 'before': 'd'*64, 'after': 'd'*64,
                           'claim_code': 'handoff_claim_conflict' if kind == 'handoff' else 'write_already_claimed',
                           'investigation_reads': int(mode == 'timeout_after_effect' and kind != 'handoff'), 'late_status': status})
    return {'schema_version': 1, 'scope': replay.SCOPE, 'fixture_sha256': replay.digest(manifest),
            'execution': replay.execution_metadata(run_id, source, mode='oracle_control'),
            'network_attempts': 0, 'replays': rows, 'faults': faults}


class ReplayOracleTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dialogues.load_manifest()
        self.value = oracle_control()

    def validate(self, value=None):
        return replay.validate_batch(self.value if value is None else value, self.manifest, allow_oracle_control=True)

    def reject(self, change):
        value = deepcopy(self.value); change(value)
        with self.assertRaises(ValueError): self.validate(value)

    def test_control_is_valid_only_with_explicit_oracle_permission(self):
        self.validate()
        with self.assertRaises(ValueError): replay.validate_batch(self.value, self.manifest)

    def test_missing_duplicate_or_reordered_scenarios_are_rejected(self):
        for change in (lambda v:v['replays'].pop(),
                       lambda v:v['replays'].__setitem__(1,deepcopy(v['replays'][0])),
                       lambda v:v['replays'].reverse()): self.reject(change)

    def test_second_backend_must_equal_first_fixed_initial_backend(self):
        self.reject(lambda v:v['replays'][0]['rebuilt'].__setitem__('initial_backend','0'*64))
        for row in self.value['replays'][:1]:
            row['first']['initial_backend'] = row['rebuilt']['initial_backend'] = '0'*64
        with self.assertRaises(ValueError): self.validate()

    def test_same_wrong_final_backend_cannot_pass_by_matching_two_runs(self):
        for side in ('first','rebuilt'):
            r=self.value['replays'][0][side]
            r['result']['final_backend']['customers']['customer_a']['email']='wrong@example.test'
            r['final_backend']=replay.digest(r['result']['final_backend'])
        with self.assertRaisesRegex(ValueError,'fixed oracle'): self.validate()

    def test_second_reply_or_full_state_fingerprint_difference_is_rejected(self):
        for key in ('message','evidence','http_calls'):
            self.reject(lambda v,k=key:v['replays'][0]['rebuilt']['frames'][0].__setitem__(k,'0'*64))

    def test_fixed_calls_still_reject_extra_send_even_when_replay_matches(self):
        row=next(r for r in self.value['replays'] if r['id']=='whole_cancellation')
        for side in ('first','rebuilt'):
            calls=row[side]['result']['turns'][-1]['http_calls']; calls.extend(deepcopy(calls))
        with self.assertRaisesRegex(ValueError,'business calls'): self.validate()

    def test_missing_frames_tool_results_or_checkpoints_are_rejected(self):
        for change in (lambda v:v['replays'][0].__setitem__('checkpoints',0),
                       lambda v:v['replays'][0].__setitem__('checkpoints',999),
                       lambda v:v['replays'][0]['first']['frames'].pop()): self.reject(change)

    def test_equal_truncated_frames_fail_the_independent_turn_count(self):
        row=self.value['replays'][0]
        row['first']['frames'].pop(); row['rebuilt']['frames'].pop()
        with self.assertRaisesRegex(ValueError,'Truncated'): self.validate()

    def test_unpaired_tool_or_result_is_rejected_even_when_both_runs_match(self):
        for event in ('tool','result'):
            value=deepcopy(self.value); row=value['replays'][0]
            for side in ('first','rebuilt'):
                frame=deepcopy(row[side]['frames'][0]); frame['event']=event
                row[side]['frames'].insert(1,frame)
            if event=='tool': row['checkpoints']+=1
            with self.assertRaisesRegex(ValueError,'Truncated'): self.validate(value)

    def test_equal_fake_tool_frames_cannot_disagree_with_actual_tool_inventory(self):
        row=self.value['replays'][0]
        for side in ('first','rebuilt'):
            frames=row[side]['frames']
            frames[1:1]=[{**deepcopy(frames[0]),'event':event} for event in ('tool','result')]
        row['checkpoints']+=1
        with self.assertRaisesRegex(ValueError,'inventory'): self.validate()

    def test_unknown_or_wrong_frame_hash_fields_are_rejected(self):
        for side in ('first','rebuilt'):
            self.value['replays'][0][side]['frames'][0]['evidence']='not-a-hash'
        with self.assertRaises(ValueError): self.validate()

    def test_missing_endpoint_or_fault_mode_cannot_shrink_interruption_coverage(self):
        self.reject(lambda v:v['faults'].pop())
        self.reject(lambda v:v['faults'].__setitem__(1,deepcopy(v['faults'][0])))

    def test_extra_send_changed_receipt_and_wrong_claim_guard_are_rejected(self):
        for key, value in (('sends',2),('extra_sends',1),('after','0'*64),('claim_code','order_processed')):
            self.reject(lambda v,k=key,x=value:v['faults'][0].__setitem__(k,x))

    def test_unknown_cannot_be_promoted_by_late_payload_or_same_backend_state(self):
        for key in ('status','late_status'):
            self.reject(lambda v,k=key:v['faults'][1].__setitem__(k,'succeeded'))

    def test_accepted_unknown_requires_a_real_investigation_read(self):
        self.reject(lambda v:v['faults'][2].__setitem__('investigation_reads',0))

    def test_lost_result_and_terminal_handoff_cannot_permit_investigation_reads(self):
        for index in (1,21,22,23):
            self.reject(lambda v,i=index:v['faults'][i].__setitem__('investigation_reads',1))

    def test_native_provenance_rejects_stale_runner_inputs_sdk_or_fixture(self):
        for key,value in (('runner','other.py'),('sdk_version','0'),('runner_inputs',{})):
            self.reject(lambda v,k=key,x=value:v['execution'].__setitem__(k,x))
        self.reject(lambda v:v.__setitem__('fixture_sha256','0'*64))
        self.reject(lambda v:v.__setitem__('network_attempts',1))

    def test_sdk_wall_time_is_excluded_but_id_arguments_and_text_are_compared(self):
        a={'role':'assistant','timestamp':'first','content':'recap','tool_calls':[{'id':'one','name':'get_order','arguments':{'order_id':'#TEST1'}}]}
        b=deepcopy(a); b['timestamp']='second'
        self.assertEqual(replay.message_data(a),replay.message_data(b))
        for key,value in (('content','different'),('tool_calls',[{'id':'two'}])):
            c=deepcopy(b); c[key]=value
            self.assertNotEqual(replay.digest(replay.message_data(a)),replay.digest(replay.message_data(c)))
        self.assertEqual(a['timestamp'],'first')

    def test_validation_preserves_all_observed_input_data(self):
        before=deepcopy(self.value); verified=self.validate()
        self.assertEqual(self.value,before)
        verified['faults'][0]['sends']=2
        self.assertEqual(self.value,before)

    def test_missing_or_unexecuted_native_wrapper_cannot_publish_observations(self):
        for report in ({'results':{replay.WRAPPER:'passed'}}, {'results':{},'replay_batch':self.value}):
            with self.assertRaises(ValueError): replay.trace_replays(report,self.manifest)

    def test_parent_run_source_and_oracle_mode_cannot_be_substituted_at_publication(self):
        report={'run_id':'control','source_sha256':'fixture','results':{replay.WRAPPER:'passed'},'replay_batch':self.value}
        with self.assertRaises(ValueError): replay.trace_replays(report,self.manifest)
        control=replay.trace_replays(report,self.manifest,allow_oracle_control=True)
        self.assertEqual(control['complete_business_ats_executed'],0)
        for key in ('run_id','source_sha256'):
            altered=deepcopy(report); altered[key]='old'
            with self.assertRaises(ValueError): replay.trace_replays(altered,self.manifest,allow_oracle_control=True)


class NativeReplayTests(unittest.TestCase):
    def test_native_rebuilt_toolkits_replay_and_faults_match_fixed_contracts(self):
        global BATCH_EVIDENCE
        BATCH_EVIDENCE = None
        env=dict(os.environ); env.pop('PYTHONPATH',None)
        env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',LITELLM_TELEMETRY='False',LITELLM_LOCAL_MODEL_COST_MAP='True')
        spec=importlib.util.spec_from_file_location('foundation_for_replay',ROOT/'scripts/foundation_trace.py')
        foundation=importlib.util.module_from_spec(spec); spec.loader.exec_module(foundation)
        parent=PARENT_RUN or {'run_id':uuid4().hex,'source_sha256':foundation.source_digest()}
        run=subprocess.run([sys.executable,'-B',str(ROOT/'tests/sdk_m6_replay_checks.py'),
                            '--parent-run-id',parent['run_id'],'--source-sha256',parent['source_sha256']],
                           cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True,timeout=300)
        self.assertEqual(run.returncode,0,run.stderr[-6000:])
        self.assertIn('M6_REPLAY_SDK_CHECK_PASSED;',run.stdout)
        lines=[line.removeprefix('M6_REPLAY_JSON=') for line in run.stdout.splitlines() if line.startswith('M6_REPLAY_JSON=')]
        self.assertEqual(len(lines),1)
        verified=replay.validate_batch(json.loads(lines[0]),dialogues.load_manifest())
        self.assertEqual(verified['execution'],replay.execution_metadata(parent['run_id'],parent['source_sha256']))
        self.assertEqual(len(verified['faults']),len(replay.FAULT_CASES)*len(replay.FAULT_MODES))
        BATCH_EVIDENCE=verified
