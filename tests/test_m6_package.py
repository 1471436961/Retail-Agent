"""Offline package controls; fabricated validator controls are not native evidence."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4
from temp_dirs import temporary_directory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
spec=importlib.util.spec_from_file_location('local_package_audit',ROOT/'scripts/local_package_audit.py')
contract=importlib.util.module_from_spec(spec); spec.loader.exec_module(contract)
PARENT_RUN=None
BATCH_EVIDENCE=None

def minimal():
    return [{'path':'agent.json','content':json.dumps({'protocol':'hyper-lab-v1','language':'python','domain':'retail_plus'})},
            {'path':'agent.py','content':'pass\n'},{'path':'tools.py','content':'pass\n'}]

class PackageAuditTests(unittest.TestCase):
    def test_real_collector_scans_every_upload_file_and_both_complete_payloads(self):
        result,files=contract.audit_package()
        self.assertEqual(result['file_count'],len(files))
        self.assertEqual(set(result['content_hashes']),{r['path'] for r in files})
        self.assertEqual(result['scan']['files'],len(files))
        self.assertEqual(result['scan']['payloads'],2)
        self.assertEqual(result['scan']['findings'],[])

    def test_file_count_limit_accepts_128_and_refuses_129(self):
        rows=minimal()+[{'path':f'data{i}.txt','content':''} for i in range(125)]
        self.assertEqual(contract.audit_files(rows)['file_count'],128)
        with self.assertRaisesRegex(ValueError,'file_count_budget'):
            contract.audit_files(rows+[{'path':'extra.txt','content':''}])

    def test_single_file_limit_counts_utf8_bytes_at_exact_boundary(self):
        rows=minimal()+[{'path':'data.txt','content':'中'*(262144//3)+'x'}]
        contract.audit_files(rows)
        rows[-1]['content']+='x'
        with self.assertRaisesRegex(ValueError,'single_file_budget'): contract.audit_files(rows)

    def test_payload_limit_measures_complete_serialized_envelope_not_raw_source(self):
        rows=minimal()+[{'path':'data.txt','content':'"\\中\n'*100}]
        result=contract.audit_files(rows)
        size=max(result['payload_bytes'].values())
        self.assertGreater(size,result['source_text_bytes'])
        contract.audit_files(rows,payload_limit=size)
        with self.assertRaisesRegex(ValueError,'submission_payload_budget'):
            contract.audit_files(rows,payload_limit=size-1)

    def test_many_individually_valid_files_still_fail_actual_two_mib_payload_limit(self):
        rows=minimal()+[{'path':f'data{i}.txt','content':'x'*262144} for i in range(8)]
        with self.assertRaisesRegex(ValueError,'submission_payload_budget'): contract.audit_files(rows)

    def test_node_raw_newlines_and_python_normalized_text_have_distinct_payloads(self):
        rows=minimal(); raw=deepcopy(rows); raw[1]['content']='pass\r\n'
        result=contract.audit_files(rows,node_files=raw)
        self.assertEqual(result['payload_bytes']['manual_node'],len(contract.encode_payload('manual_node',contract.payloads(rows,raw)['manual_node'])))
        raw[1]['content']='wrong\r\n'
        with self.assertRaisesRegex(ValueError,'differs beyond newline'): contract.audit_files(rows,node_files=raw)

    def test_secret_controls_are_rejected_without_echoing_matched_values(self):
        for secret in ('-----BEGIN PRIVATE KEY-----','sk-'+'A'*25,'ghp_'+'B'*25,
                       'AKIA'+'C'*16,'Bearer '+'D'*25,'api_key = "'+'E'*20+'"'):
            rows=minimal()+[{'path':'data.txt','content':secret}]
            with self.assertRaises(ValueError) as caught: contract.audit_files(rows)
            self.assertNotIn(secret,str(caught.exception))
            self.assertIn('source_audit_rejected',str(caught.exception))

    def test_unquoted_yaml_and_env_credentials_are_rejected_by_assignment_rule(self):
        for text in ('api_key: synthetic_canary_value','  password: synthetic_canary_value # comment',
                     'ACCESS_TOKEN=synthetic_canary_value','"client_secret": synthetic_canary_value\r\n'):
            rows=minimal()+[{'path':'data.yaml','content':text}]
            with self.assertRaises(ValueError) as caught: contract.audit_files(rows)
            self.assertIn('credential_assignment',str(caught.exception))
            self.assertNotIn('synthetic_canary_value',str(caught.exception))

    def test_ordinary_text_empty_values_and_environment_references_are_positive_controls(self):
        for text in ('description: harmless_text','api_key: null','password: ""','api_key: ${API_KEY}',
                     'This explains api_key: synthetic_canary_value as prose.', 'api_key = os.environ.get("NAME")'):
            self.assertEqual(contract.scan_text('control.yaml',text),[])

    def test_traversal_external_credentials_and_noncanonical_paths_are_rejected(self):
        for name in ('../data.txt','/tmp/data.txt','C:/data.txt','tests/a.py','a//b.py','a/./b.py','credentials.json','a\\b.py'):
            with self.assertRaisesRegex(ValueError,'forbidden_package_path'):
                contract.audit_files(minimal()+[{'path':name,'content':''}])

    def test_duplicate_manifest_missing_entrypoints_and_raw_file_overflow_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'): contract.audit_files(minimal()+[minimal()[1]])
        with self.assertRaisesRegex(ValueError,'missing_entrypoints'): contract.audit_files(minimal()[:-1])
        rows=minimal(); rows[0]['content']='{}'
        with self.assertRaisesRegex(ValueError,'unexpected_manifest'): contract.audit_files(rows)
        with self.assertRaisesRegex(ValueError,'single_file_budget'):
            contract.audit_files(minimal(),{r['path']:262145 for r in minimal()})

    def test_import_log_output_dynamic_code_and_external_path_controls_are_rejected(self):
        for code in ('import logging','import requests','import tests.helper','from support_agent.missing import x',
                     'print("private")','open("data")','eval("1")','p="E:/outside/file"'):
            rows=minimal(); rows[1]['content']=code
            with self.assertRaisesRegex(ValueError,'source_audit_rejected'): contract.audit_files(rows)

    def test_collector_rejects_symlink_package(self):
        # Mock the real filesystem predicate, not the audit result.
        from unittest.mock import patch
        with patch('pathlib.Path.is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'real agent'): contract.audit_package()

    def test_package_junction_is_rejected_before_source_collection(self):
        from unittest.mock import patch
        with patch('pathlib.Path.is_junction',return_value=True,create=True), \
             patch('pathlib.Path.is_symlink',return_value=False), \
             patch.object(contract.importlib.util,'spec_from_file_location',side_effect=AssertionError('collector reached')) as loader:
            with self.assertRaisesRegex(ValueError,'junctions'): contract.audit_package()
            loader.assert_not_called()

    def test_read_bytes_compile_pickle_and_existing_path_open_reach_exact_ast_rules(self):
        cases=(('from pathlib import Path; Path("local.txt").read_bytes()','output_dynamic_or_filesystem_call'),
               ('compile("pass","local","exec")','output_dynamic_or_filesystem_call'),
               ('import builtins; builtins.compile("pass","local","exec")','output_dynamic_or_filesystem_call'),
               ('import pickle','direct_io_or_logging_import'),
               ('from pathlib import Path; Path("local.txt").open()','output_dynamic_or_filesystem_call'))
        for code,rule in cases:
            rows=minimal(); rows[1]['content']=code
            with self.assertRaises(ValueError) as caught: contract.audit_files(rows)
            self.assertIn(rule,str(caught.exception))
        rows=minimal(); rows[1]['content']='import re; pattern=re.compile("safe")'
        self.assertEqual(contract.audit_files(rows)['scan']['findings'],[])

    def test_copied_byte_hash_check_accepts_actual_upload_bytes(self):
        with temporary_directory() as directory:
            root=Path(directory); (root/'agent.py').write_bytes(b'pass\r\n')
            expected={'agent.py':contract.sha(b'pass\r\n')}
            self.assertEqual(contract.verify_copied_package(root,expected),expected)

    def test_same_paths_with_changed_bytes_or_missing_extra_file_cannot_pass_copy_check(self):
        with temporary_directory() as directory:
            root=Path(directory); path=root/'agent.py'; path.write_bytes(b'pass\n')
            expected={'agent.py':contract.sha(b'pass\n')}
            paths={p.name for p in root.iterdir()}
            path.write_bytes(b'wrong\n')
            self.assertEqual({p.name for p in root.iterdir()},paths)
            with self.assertRaisesRegex(ValueError,'byte hashes'): contract.verify_copied_package(root,expected)
            path.write_bytes(b'pass\n'); (root/'extra.txt').write_bytes(b'')
            with self.assertRaisesRegex(ValueError,'byte hashes'): contract.verify_copied_package(root,expected)
            (root/'extra.txt').unlink()
            with self.assertRaisesRegex(ValueError,'byte hashes'): contract.verify_copied_package(root,{**expected,'missing.py':contract.sha(b'')})

    def test_usage_controls_do_not_create_an_unmeasured_cost_baseline(self):
        from support_agent.adapters.model_gateway import usage_record
        from types import SimpleNamespace
        self.assertEqual(usage_record(SimpleNamespace()),{'prompt_tokens':None,'completion_tokens':None,'total_tokens':None,'reported_cost':None})
        value=usage_record(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=4,completion_tokens=5),cost=0))
        self.assertEqual(value['total_tokens'],9)
        self.assertEqual(value['reported_cost'],0)

class NativePackageTests(unittest.TestCase):
    def test_isolated_uploaded_package_with_real_sdk(self):
        global BATCH_EVIDENCE
        BATCH_EVIDENCE=None
        package,files=contract.audit_package()
        interpreter=ROOT/'.venv/Scripts/python.exe'
        self.assertTrue(interpreter.is_file(),'SDK evidence cannot be skipped')
        parent=PARENT_RUN or {'run_id':uuid4().hex,'source_sha256':contract.sha(b'standalone')}
        env=os.environ.copy(); env.pop('PYTHONPATH',None)
        env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',LITELLM_TELEMETRY='False',LITELLM_LOCAL_MODEL_COST_MAP='True')
        with temporary_directory() as directory:
            root=Path(directory)
            for row in files:
                path=root/row['path']; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(row['content'].encode('utf-8'))
            self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()},set(package['content_hashes']))
            contract.verify_copied_package(root,package['content_hashes'])
            run=subprocess.run([str(interpreter),'-I','-B',str(ROOT/contract.RUNNER),'--package',str(root)],
                cwd=root,env=env,capture_output=True,text=True,timeout=120)
            copied_hashes=contract.verify_copied_package(root,package['content_hashes'])
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertNotIn('M65_PRIVATE_ERROR_CANARY_0123456789',run.stdout+run.stderr)
        self.assertIn('M6_PACKAGE_PASSED; network attempts 0',run.stdout)
        rows=[line[len('M6_PACKAGE_JSON '):] for line in run.stdout.splitlines() if line.startswith('M6_PACKAGE_JSON ')]
        self.assertEqual(len(rows),1)
        isolated=json.loads(rows[0]); isolated['copied_content_sha256']=copied_hashes
        value={'scope':contract.SCOPE,'execution':contract.metadata(parent),'package':package,
               'isolated':isolated,'measurement':{'status':'not_measured','real_model_calls':0,'token_total':None,'cost_total':None}}
        contract.validate_batch(value,parent)
        BATCH_EVIDENCE=value

class PackagePublicationTests(unittest.TestCase):
    def setUp(self):
        self.parent={'run_id':'validator-control','source_sha256':contract.sha(b'control')}
        self.value={'scope':contract.SCOPE,'execution':contract.metadata(self.parent),'package':contract.audit_package()[0],
            'isolated':{'sdk_version':'1.0.1','module_origins_inside_package':True,'read_tools':8,'write_tools':7,
                       'factory_fresh':True,'private_error_marker_absent':True,'network_attempts':0,'transport_calls':1,'model_calls':0},
            'measurement':{'status':'not_measured','real_model_calls':0,'token_total':None,'cost_total':None}}
        self.value['isolated']['copied_content_sha256']=dict(self.value['package']['content_hashes'])

    def test_fixed_validator_control_passes_but_missing_native_observations_fail(self):
        contract.validate_batch(self.value,self.parent)
        with self.assertRaisesRegex(ValueError,'without observations'):
            contract.trace_package({**self.parent,'results':{contract.WRAPPER:'passed'}})

    def test_changed_payload_hash_parent_source_or_input_cannot_publish(self):
        for field in ('package','parent','input'):
            bad=deepcopy(self.value)
            if field=='package': bad['package']['payload_sha256']['manual_node']='0'*64
            elif field=='parent': bad['execution']['source_sha256']='0'*64
            else: bad['execution']['inputs'][contract.RUNNER]='0'*64
            with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)

    def test_network_model_call_or_unsafe_module_origin_cannot_publish(self):
        for key,value in (('network_attempts',1),('model_calls',1),('module_origins_inside_package',False),('transport_calls',True)):
            bad=deepcopy(self.value); bad['isolated'][key]=value
            with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)

    def test_unmeasured_cost_cannot_be_replaced_by_zero_or_estimate(self):
        for key,value in (('cost_total',0),('token_total',0),('status','estimated')):
            bad=deepcopy(self.value); bad['measurement'][key]=value
            with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)

    def test_observations_without_successful_wrapper_cannot_publish(self):
        with self.assertRaisesRegex(ValueError,'lack passed wrapper'):
            contract.trace_package({**self.parent,'results':{},'package_batch':self.value})

    def test_malformed_runtime_observations_are_public_value_errors(self):
        for value in (None,[],1,True):
            bad=deepcopy(self.value); bad['isolated']=value
            with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)

    def test_copied_content_hash_observation_cannot_be_missing_or_tampered(self):
        bad=deepcopy(self.value); bad['isolated'].pop('copied_content_sha256')
        with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)
        bad=deepcopy(self.value); bad['isolated']['copied_content_sha256']['agent.py']='0'*64
        with self.assertRaises(ValueError): contract.validate_batch(bad,self.parent)
