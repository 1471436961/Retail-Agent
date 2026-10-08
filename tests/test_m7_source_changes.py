"""Reject unrecorded production/fixture changes after the preserved M6 chain."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from m7_source_changes import MANIFEST, validate_changes


class M7SourceChangesTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/MANIFEST).read_text(encoding='utf-8'))
        old_path=ROOT/'tests/fixtures/m6_business_changes.json'
        old=json.loads(old_path.read_text(encoding='utf-8'))
        self.previous=json.loads((ROOT/'tests/fixtures/m6_3_source_baseline.json').read_text(encoding='utf-8'))['source_files']
        self.previous.update({r['path']:r['after_sha256'] for r in old['changes']})
        self.sha=hashlib.sha256(old_path.read_bytes()).hexdigest()
        paths={p.relative_to(ROOT).as_posix() for p in (ROOT/'agent').rglob('*.py') if '__pycache__' not in p.parts}
        paths |= {'agent/agent.json','tests/fixtures/m6_dialogues.json','tests/fixtures/m6_combinations.json'}
        self.current={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}

    def check(self, value=None, current=None):
        return validate_changes(self.value if value is None else value,self.sha,self.previous,
                                self.current if current is None else current)

    def test_current_bytes_match_explicit_chain_without_overwriting_m6_baseline(self):
        evidence=self.check()
        self.assertEqual(evidence['changed_existing_files'],16)
        self.assertEqual(len(evidence['added_files']),3)
        self.assertEqual(evidence['unchanged_previous_files'],43)

    def test_before_after_reason_duplicate_and_missing_change_are_rejected(self):
        for kind in ('before','after','reason','duplicate','missing'):
            bad=deepcopy(self.value)
            if kind=='before': bad['changes'][0]['before_sha256']='0'*64
            if kind=='after': bad['changes'][0]['after_sha256']='0'*64
            if kind=='reason': bad['changes'][0]['reason']=''
            if kind=='duplicate': bad['changes'].append(deepcopy(bad['changes'][0]))
            if kind=='missing': bad['changes'].pop()
            with self.subTest(kind=kind),self.assertRaises(ValueError): self.check(bad)

    def test_unregistered_module_or_fixed_dialogue_change_is_rejected(self):
        for path in ('agent/unregistered.py','tests/fixtures/m6_dialogues.json','tests/fixtures/m6_combinations.json'):
            current=dict(self.current);current[path]='0'*64
            with self.subTest(path=path),self.assertRaises(ValueError): self.check(current=current)

    def test_wrong_previous_manifest_digest_or_noninteger_schema_is_rejected(self):
        for key,value in (('previous_manifest_sha256','0'*64),('schema_version',True),('schema_version',1.0)):
            bad=deepcopy(self.value);bad[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError): self.check(bad)

    def test_unsafe_or_nonproduction_paths_cannot_enter_change_list(self):
        for path in ('../agent/evil.py','agent/../evil.py','agent\\evil.py','tests/evil.py','agent//evil.py'):
            bad=deepcopy(self.value);bad['changes'][0]['path']=path
            with self.subTest(path=path),self.assertRaises(ValueError): self.check(bad)
