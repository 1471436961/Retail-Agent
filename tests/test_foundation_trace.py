"""The inventory must not turn component evidence into business passes."""
import importlib.util
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from temp_dirs import temporary_directory

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("foundation_trace", ROOT / "scripts" / "foundation_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class FoundationTraceTests(unittest.TestCase):
    def setUp(self):
        self.requirements = (ROOT / "docs" / "CASE-REQUIREMENTS.md").read_text(encoding="utf-8")
        self.snapshot = {"source_sha256":"fixture", "specification_sha256":"spec-fixture",
                         "specification_files":{"materials/public-contract":"fixture"},
                         "requirements_sha256":hashlib.sha256(self.requirements.encode()).hexdigest()}
        self.report = {**self.snapshot, "run_id":"current-run", "status":"passed",
                       "exit_code":0, "skipped":0, "failures":0, "errors":0,
                       "results":{name:"passed" for ids in trace.GROUP_TESTS.values() for name in ids}}

    def build(self, requirements=None, report=None, *, allow_oracle_control=False):
        return trace.build_trace(self.requirements if requirements is None else requirements,
                                 self.report if report is None else report,
                                 expected_source_digest="fixture", expected_specification_digest="spec-fixture", allow_oracle_control=allow_oracle_control)

    def test_all_atomic_ids_keep_business_and_remote_execution_explicitly_pending(self):
        result = self.build()
        self.assertEqual((result["case_count"], result["at_count"]), (134, 522))
        self.assertEqual(len({r["at_id"] for r in result["records"]}), 522)
        self.assertTrue(all(r["business_result"] == "not_executed" and r["remote_result"] == "not_run" for r in result["records"]))
        self.assertEqual(result["business_ats_executed"], 0)

    def test_stale_source_failed_or_unexecuted_component_evidence_is_rejected(self):
        for kind in ("source", "failure", "missing", "skipped", "specification", "requirements", "run", "status"):
            report = {**self.report, "results":dict(self.report["results"])}
            if kind == "source": report["source_sha256"] = "stale"
            if kind == "failure": report["exit_code"] = 1
            if kind == "missing": report["results"].pop(next(iter(report["results"])))
            if kind == "skipped": report["skipped"] = 1
            if kind == "specification": report["specification_sha256"] = "stale"
            if kind == "requirements": report["requirements_sha256"] = "stale"
            if kind == "run": report.pop("run_id")
            if kind == "status": report["status"] = "running"
            with self.assertRaises(ValueError): self.build(report=report)

    def test_missing_atomic_requirement_or_unknown_rule_group_cannot_shrink_inventory(self):
        for changed in (self.requirements.replace("- A000-01", "- OMITTED-01", 1),
                        self.requirements.replace("[N1; O]", "[N1; UNKNOWN]", 1)):
            report = {**self.report, "requirements_sha256":hashlib.sha256(changed.encode()).hexdigest()}
            with self.assertRaises(ValueError): self.build(changed, report)

    def test_main_failure_and_skip_invalidate_existing_trace_and_return_one(self):
        for outcome in ("failure", "skip"):
            with self.subTest(outcome=outcome), temporary_directory() as directory:
                report_path, trace_path = Path(directory) / "run.json", Path(directory) / "trace.json"
                trace_path.write_text(json.dumps(self.build()), encoding="utf-8")
                class InnerCase(unittest.TestCase):
                    def runTest(inner):
                        if outcome == "skip": inner.skipTest("synthetic skip")
                        inner.fail("synthetic failure")
                suite = unittest.TestSuite([InnerCase()])
                with patch.object(trace, "input_snapshot", return_value=self.snapshot), \
                     patch.object(trace.unittest.defaultTestLoader, "discover", return_value=suite), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = trace.main(["--report", str(report_path), "--trace", str(trace_path)])
                report, invalid = json.loads(report_path.read_text()), json.loads(trace_path.read_text())
                self.assertEqual(code, 1)
                self.assertEqual(report["exit_code"], 1)
                self.assertEqual(report["status"], "tests_not_passed")
                self.assertEqual(report["skipped"], int(outcome == "skip"))
                self.assertEqual(report["failures"], int(outcome == "failure"))
                self.assertEqual(invalid["status"], "invalid")
                self.assertEqual(invalid["run_id"], report["run_id"])
                self.assertNotEqual(invalid["run_id"], self.report["run_id"])
                self.assertNotIn("records", invalid)
                self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_publication_binds_same_run_and_rejects_old_same_source_trace(self):
        with temporary_directory() as directory:
            report_path, trace_path = Path(directory) / "run.json", Path(directory) / "trace.json"
            old = self.build()
            report = {**self.report, "run_id":"next-run"}
            code = trace.publish_run(self.requirements, report, snapshot=self.snapshot,
                                     report_path=report_path, trace_path=trace_path)
            saved_report, saved_trace = json.loads(report_path.read_text()), json.loads(trace_path.read_text())
            self.assertEqual(code, 0)
            self.assertEqual(saved_trace["run_id"], saved_report["run_id"])
            trace.validate_evidence_pair(self.requirements, saved_report, saved_trace, snapshot=self.snapshot)
            self.assertEqual(old["run_source_sha256"], saved_trace["run_source_sha256"])
            with self.assertRaises(ValueError):
                trace.validate_evidence_pair(self.requirements, saved_report, old, snapshot=self.snapshot)

    def test_trace_build_failure_publishes_failed_report_and_invalid_marker(self):
        with temporary_directory() as directory:
            report_path, trace_path = Path(directory) / "run.json", Path(directory) / "trace.json"
            trace_path.write_text(json.dumps(self.build()), encoding="utf-8")
            report = deepcopy(self.report)
            report["results"].pop(next(iter(report["results"])))
            self.assertEqual(trace.publish_run(self.requirements, report, snapshot=self.snapshot,
                             report_path=report_path, trace_path=trace_path), 1)
            failed = json.loads(report_path.read_text())
            invalid = json.loads(trace_path.read_text())
            self.assertEqual(failed["status"], "trace_rejected")
            self.assertEqual(failed["exit_code"], 1)
            self.assertEqual(invalid["reason"], "trace_rejected")
            self.assertNotIn("groups", invalid)

    def test_interrupted_report_publication_cannot_leave_old_trace_valid(self):
        with temporary_directory() as directory:
            report_path, trace_path = Path(directory) / "run.json", Path(directory) / "trace.json"
            report_path.write_text(json.dumps(self.report), encoding="utf-8")
            trace_path.write_text(json.dumps(self.build()), encoding="utf-8")
            writer = trace._write_json_atomic
            def interrupted(path, value):
                if path == report_path: raise OSError("synthetic publish failure")
                writer(path, value)
            with patch.object(trace, "_write_json_atomic", side_effect=interrupted), self.assertRaises(OSError):
                trace.publish_run(self.requirements, {**self.report, "run_id":"interrupted-run"},
                                  snapshot=self.snapshot, report_path=report_path, trace_path=trace_path)
            old_report, invalid = json.loads(report_path.read_text()), json.loads(trace_path.read_text())
            self.assertEqual(invalid["status"], "invalid")
            self.assertNotEqual(old_report["run_id"], invalid["run_id"])
            with self.assertRaises(ValueError):
                trace.validate_evidence_pair(self.requirements, old_report, invalid, snapshot=self.snapshot)

    def test_specification_snapshot_tracks_selected_doc_and_material_bytes(self):
        paths = ("docs/selected.md", "materials/selected.yaml")
        with temporary_directory() as directory, patch.object(trace, "SPECIFICATION_PATHS", paths):
            root = Path(directory)
            for path in paths:
                (root / path).parent.mkdir(exist_ok=True)
                (root / path).write_text("original", encoding="utf-8")
            (root / "docs/unselected.md").write_text("not selected", encoding="utf-8")
            original = trace.specification_snapshot(root)
            self.assertEqual(original["specification_files"][paths[0]], hashlib.sha256(b"original").hexdigest())
            (root / "docs/unselected.md").write_text("changed", encoding="utf-8")
            self.assertEqual(trace.specification_snapshot(root), original)
            (root / paths[0]).write_text("changed spec", encoding="utf-8")
            changed = trace.specification_snapshot(root)
            self.assertNotEqual(changed["specification_sha256"], original["specification_sha256"])
            self.assertEqual(changed["specification_files"][paths[1]], original["specification_files"][paths[1]])

    def test_changed_inputs_cannot_publish_passing_trace(self):
        with temporary_directory() as directory:
            report_path, trace_path = Path(directory) / "run.json", Path(directory) / "trace.json"
            trace_path.write_text(json.dumps(self.build()), encoding="utf-8")
            after = {**self.snapshot, "specification_sha256":"changed-after-run"}
            with patch.object(trace, "input_snapshot", side_effect=[self.snapshot, after]), \
                 patch.object(trace.unittest.defaultTestLoader, "discover", return_value=unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = trace.main(["--report", str(report_path), "--trace", str(trace_path)])
            report, invalid = json.loads(report_path.read_text()), json.loads(trace_path.read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "inputs_changed")
            self.assertEqual(report["results"]["<lambda>"], "passed")
            self.assertEqual(invalid["status"], "invalid")

    def test_oracle_control_can_check_plan_without_becoming_native_publication(self):
        from test_m6_dialogues import batch, synthetic_result
        manifest=batch.load_manifest()
        report=deepcopy(self.report)
        report['results'][batch.WRAPPER]='passed'
        report['dialogue_batch']={'schema_version':2,'scope':batch.SCOPE,'fixture_sha256':batch.digest(manifest),
                                 'execution':batch.execution_metadata(report['run_id'],report['source_sha256'],mode='oracle_control'),
                                 'network_attempts':0,'results':[synthetic_result(s) for s in manifest['scenarios']]}
        with self.assertRaisesRegex(ValueError,'provenance'): self.build(report=report)
        result=self.build(report=report,allow_oracle_control=True)
        self.assertEqual(result['local_dialogues']['dialogues_passed'],16)
        self.assertEqual(len(result['local_dialogues']['plan']),522)
        self.assertEqual(result['business_ats_executed'],0)
        self.assertTrue(all(r['business_result']=='not_executed' for r in result['records']))
        self.assertEqual(next(r for r in result['records'] if r['at_id']=='AT-A017-03')['local_dialogue_ids'],['order_address','address_correction'])
        tampered=deepcopy(result); tampered['local_dialogues']['dialogues_passed']=522
        with self.assertRaises(ValueError):
            trace.validate_evidence_pair(self.requirements,report,tampered,snapshot=self.snapshot,allow_oracle_control=True)

    def test_missing_native_dialogue_observations_invalidate_publication_even_when_wrapper_passed(self):
        from test_m6_dialogues import batch
        report=deepcopy(self.report); report['results'][batch.WRAPPER]='passed'
        with temporary_directory() as directory:
            run_path, trace_path=Path(directory)/'run.json',Path(directory)/'trace.json'
            self.assertEqual(trace.publish_run(self.requirements,report,snapshot=self.snapshot,
                             report_path=run_path,trace_path=trace_path),1)
            self.assertEqual(json.loads(run_path.read_text())['status'],'trace_rejected')
            self.assertEqual(json.loads(trace_path.read_text())['status'],'invalid')

    def test_oracle_mode_or_mismatched_parent_cannot_publish_a_native_trace(self):
        from test_m6_dialogues import batch,synthetic_result
        manifest=batch.load_manifest(); report=deepcopy(self.report)
        report['results'][batch.WRAPPER]='passed'
        report['dialogue_batch']={'schema_version':2,'scope':batch.SCOPE,'fixture_sha256':batch.digest(manifest),
            'network_attempts':0,'execution':batch.execution_metadata(report['run_id'],report['source_sha256'],mode='oracle_control'),
            'results':[synthetic_result(s) for s in manifest['scenarios']]}
        for mode,run,source in (('oracle_control',report['run_id'],'fixture'),('native_sdk','old-run','fixture'),
                                ('native_sdk',report['run_id'],'old-source')):
            report['dialogue_batch']['execution'].update(mode=mode,parent_run_id=run,source_sha256=source)
            with temporary_directory() as directory:
                run_path,trace_path=Path(directory)/'run.json',Path(directory)/'trace.json'
                self.assertEqual(trace.publish_run(self.requirements,report,snapshot=self.snapshot,
                                                  report_path=run_path,trace_path=trace_path),1)
                self.assertEqual(json.loads(trace_path.read_text())['status'],'invalid')

    def test_source_digest_tracks_runner_oracle_and_fixture_but_not_unselected_docs_or_credentials(self):
        paths=('agent/agent.json','agent/core.py','tests/check.py','tests/fixtures/batch.json',
               'scripts/foundation_trace.py','scripts/local_dialogue_batch.py','scripts/evidence_docs.py')
        with temporary_directory() as directory:
            root=Path(directory)
            for name in paths:
                path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('baseline',encoding='utf-8')
            baseline=trace.source_digest(root)
            for name in paths:
                path=root/name; path.write_text('changed',encoding='utf-8')
                self.assertNotEqual(trace.source_digest(root),baseline,name)
                path.write_text('baseline',encoding='utf-8')
            (root/'docs').mkdir()
            for name in ('docs/unselected.md','.env','Enterprise-AI.json'):
                (root/name).write_text('synthetic sentinel, not a credential',encoding='utf-8')
            self.assertEqual(trace.source_digest(root),baseline)

    def test_nested_runner_restores_parent_context_and_does_not_reuse_outer_evidence(self):
        outer=SimpleNamespace(PARENT_RUN={'run_id':'outer','source_sha256':'outer-source'},
                              BATCH_EVIDENCE={'sentinel':'outer evidence'})
        original_parent,original_evidence=outer.PARENT_RUN,outer.BATCH_EVIDENCE
        def inner():
            self.assertNotEqual(outer.PARENT_RUN,original_parent)
            self.assertIsNone(outer.BATCH_EVIDENCE)
        with temporary_directory() as directory, patch.dict(trace.sys.modules,{'test_m6_dialogues':outer}), \
             patch.object(trace,'input_snapshot',return_value=self.snapshot), \
             patch.object(trace.unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite([unittest.FunctionTestCase(inner)])), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            run_path,trace_path=Path(directory)/'run.json',Path(directory)/'trace.json'
            trace.main(['--report',str(run_path),'--trace',str(trace_path)])
            self.assertIs(outer.PARENT_RUN,original_parent)
            self.assertIs(outer.BATCH_EVIDENCE,original_evidence)
            self.assertNotIn('dialogue_batch',json.loads(run_path.read_text()))
