"""Finite root-cause closure; historical incidents are not new business tests."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import unittest

from temp_dirs import temporary_directory

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('defect_register',ROOT/'scripts/defect_register.py')
register=importlib.util.module_from_spec(spec); spec.loader.exec_module(register)


class DefectRegisterTests(unittest.TestCase):
    def setUp(self):
        self.value=register.load_register()

    def report(self):
        from test_foundation_trace import trace
        outcomes={test:'passed' for row in self.value['incidents'] for test in row['tests']}
        outcomes[register.WRAPPER]='passed'
        return {'run_id':'validator-control','source_sha256':'control',
                'source_files':trace.source_file_hashes(),'results':outcomes}

    def test_registered_regressions_have_valid_fix_and_source_references(self):
        rows=register.validate_register(self.value)
        self.assertEqual(len(rows),15)
        self.assertEqual({r['category'] for r in rows},set(register.CATEGORIES))
        self.assertTrue(all(r['test_references'] and r['fix_sites'] for r in rows))

    def test_known_production_fixes_and_test_errors_have_distinct_reviewed_classification(self):
        rows={r['id']:r for r in register.validate_register(self.value)}
        for id in ('M66-R01','M66-R02','M66-C01','M66-C03','M66-D01','M66-D02','M66-V01'):
            self.assertEqual(rows[id]['kind'],'production')
        for id in ('M66-T02','M66-T03','M66-V02','M66-V03','M66-V04'):
            self.assertEqual(rows[id]['kind'],'test_infrastructure')
        self.assertEqual([r['id'] for r in rows.values() if r['phase']=='current'],['M66-V04'])

    def test_duplicate_incident_ids_or_duplicate_witness_sets_cannot_inflate_counts(self):
        for kind in ('id','witness'):
            bad=deepcopy(self.value); row=deepcopy(bad['incidents'][0])
            if kind=='witness':row['id']='second-copy'
            bad['incidents'].append(row)
            with self.assertRaisesRegex(ValueError,'uplicate'):register.validate_register(bad)

    def test_missing_category_and_unknown_kind_or_phase_are_rejected(self):
        for field,value in (('category','invented'),('kind','all_failures_are_test_errors'),('phase','new_business_capability')):
            bad=deepcopy(self.value);bad['incidents'][0][field]=value
            with self.assertRaises(ValueError):register.validate_register(bad)
        bad=deepcopy(self.value)
        bad['incidents']=[r for r in bad['incidents'] if r['category']!='dialogue_omission']
        with self.assertRaisesRegex(ValueError,'five'):register.validate_register(bad)

    def test_empty_root_cause_missing_fix_and_extra_authority_field_are_rejected(self):
        for kind in ('root','fix','authority'):
            bad=deepcopy(self.value);row=bad['incidents'][0]
            if kind=='root':row['root_cause']=' '
            elif kind=='fix':row['fix_sites']=[]
            else:row['write_authorized']=True
            with self.assertRaises(ValueError):register.validate_register(bad)

    def test_existing_file_with_nonexistent_fix_symbol_or_test_method_is_rejected(self):
        for kind in ('fix','test'):
            bad=deepcopy(self.value);row=bad['incidents'][0]
            if kind=='fix':row['fix_sites'][0]['symbol']='missing_function'
            else:row['tests'][0]='test_m5_matrix.ProductInteractionMatrixTests.test_missing_method'
            with self.assertRaisesRegex(ValueError,'Missing'):register.validate_register(bad)

    def test_duplicate_or_malformed_regression_ids_are_rejected(self):
        for tests in ([],[None],['not_a_test'],['test_m5_matrix.X.other_method']):
            bad=deepcopy(self.value);bad['incidents'][0]['tests']=tests
            with self.assertRaises(ValueError):register.validate_register(bad)
        bad=deepcopy(self.value);row=bad['incidents'][0];row['tests'].append(row['tests'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):register.validate_register(bad)

    def test_narrative_source_anchor_missing_or_traversing_path_is_rejected(self):
        for kind in ('anchor','path'):
            bad=deepcopy(self.value)
            if kind=='anchor':bad['incidents'][0]['origin']['contains']='nonexistent-source-anchor'
            else:bad['incidents'][0]['origin']['path']='../outside.md'
            with self.assertRaises(ValueError):register.validate_register(bad)

    def test_failed_missing_or_skipped_registered_regression_cannot_close_incident(self):
        base=self.report();test=self.value['incidents'][0]['tests'][0]
        self.assertEqual(register.closure(base)['incident_count'],15)
        for outcome in (None,'failed','skipped','error'):
            bad=deepcopy(base)
            if outcome is None:bad['results'].pop(test)
            else:bad['results'][test]=outcome
            with self.assertRaisesRegex(ValueError,'not executed'):register.closure(bad)

    def test_changed_or_missing_source_hash_prevents_closure_even_with_all_passed_results(self):
        base=self.report();name=self.value['incidents'][0]['fix_sites'][0]['path']
        for value in (None,'0'*64):
            bad=deepcopy(base)
            if value is None:bad['source_files'].pop(name)
            else:bad['source_files'][name]=value
            with self.assertRaisesRegex(ValueError,'source hashes'):register.closure(bad)

    def test_selected_historical_doc_and_register_bytes_are_run_inputs_without_git(self):
        from test_foundation_trace import trace
        files=trace.source_file_hashes()
        for name in (register.REGISTER,'scripts/defect_register.py','docs/M5.5-DELIVERY.md','docs/M6.5-DELIVERY.md'):
            self.assertEqual(files[name],hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
        with temporary_directory() as directory:
            root=Path(directory);(root/'docs').mkdir();(root/'docs/origin.md').write_text('original')
            (root/'tests/fixtures').mkdir(parents=True)
            (root/register.REGISTER).write_text(json.dumps({'incidents':[{'origin':{'path':'docs/origin.md'}}]}))
            for path in trace.source_paths(root):
                if not path.exists():
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixed input')
            before=trace.source_digest(root)
            (root/'docs/origin.md').write_text('changed')
            self.assertNotEqual(trace.source_digest(root),before)

    def test_closure_counts_history_and_current_fixes_separately_not_as_business_ats(self):
        result=register.closure(self.report())
        self.assertEqual(result['by_kind'],{'production':10,'test_infrastructure':5})
        self.assertEqual(sum(result['by_category'].values()),15)
        self.assertEqual(result['new_incidents'],1)
        self.assertEqual(result['complete_business_ats_executed'],0)
        self.assertEqual(result['unique_regressions'],len({t for r in self.value['incidents'] for t in r['tests']}))

    def test_hashed_register_requires_actual_check_wrapper_not_just_declared_references(self):
        report=self.report();report['results'].pop(register.WRAPPER)
        with self.assertRaisesRegex(ValueError,'wrapper'):register.trace_defects(report)
        report['results'][register.WRAPPER]='failed'
        with self.assertRaisesRegex(ValueError,'did not pass'):register.trace_defects(report)

    def test_changed_closure_fields_cannot_validate_as_an_unchanged_evidence_pair(self):
        from test_foundation_trace import FoundationTraceTests,trace
        control=FoundationTraceTests();control.setUp()
        report=control.report
        report['source_files']=trace.source_file_hashes()
        report['results'].update(self.report()['results'])
        report['tests_run']=len(report['results'])
        snapshot={**control.snapshot,'source_files':report['source_files']}
        pair=control.build(report=report)
        self.assertEqual(pair['defect_closure']['incident_count'],15)
        trace.validate_evidence_pair(control.requirements,report,pair,snapshot=snapshot)
        for field in ('incident_count','new_incidents','unique_regressions'):
            bad=deepcopy(pair);bad['defect_closure'][field]+=1
            with self.assertRaises(ValueError):trace.validate_evidence_pair(control.requirements,report,bad,snapshot=snapshot)

    def test_malformed_register_values_raise_public_value_error(self):
        for value in (None,[],{}, {'schema_version':True}):
            with self.assertRaises(ValueError):register.validate_register(value)
        bad=deepcopy(self.value);bad['incidents'][0]['fix_sites'][0]['symbol']=[]
        with self.assertRaises(ValueError):register.validate_register(bad)


if __name__=='__main__':unittest.main()
