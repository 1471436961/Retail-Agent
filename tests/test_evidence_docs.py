"""Current evidence is derived once; copied entry counts cannot drift."""
import importlib.util
from copy import deepcopy
from pathlib import Path
import unittest
from temp_dirs import temporary_directory

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('evidence_docs',ROOT/'scripts/evidence_docs.py')
docs=importlib.util.module_from_spec(spec); spec.loader.exec_module(docs)


class CurrentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report={'status':'passed','run_id':'r','source_sha256':'s','specification_sha256':'p',
                     'exit_code':0,'skipped':0,'errors':0,'failures':0,'tests_run':3,
                     'dialogue_batch':{'results':[{'turns':[{'http_calls':[]}]}]}}
        self.trace={'status':'valid','run_id':'r','case_count':1,'business_ats_executed':0,
                    'local_dialogues':{'dialogues_passed':1,'plan':[{'dialogue_ids':['a','b']},{'dialogue_ids':[]}]}}

    def populate(self,root):
        (root/'docs').mkdir()
        (root/'docs/CURRENT-EVIDENCE.md').write_text('# Evidence\n'+docs.START+'\nold\n'+docs.END,encoding='utf-8')
        for name in docs.ENTRY_DOCS:
            (root/name).write_text(docs.LINK+'\n'+docs.current_link(name),encoding='utf-8')
        docs.update_current(root,self.report,self.trace)

    def test_unique_atomic_links_and_relationship_count_are_rendered_separately(self):
        text=docs.render_current(self.report,self.trace)
        self.assertIn('关联 1 个不同 AT、2 条关联关系',text)
        self.assertIn('完整业务 AT 执行 **0**',text)

    def test_current_block_update_and_six_reference_entries_validate(self):
        with temporary_directory() as directory:
            root=Path(directory); self.populate(root)
            docs.validate_documents(root,self.report,self.trace)

    def test_stale_count_or_duplicate_current_block_is_rejected(self):
        with temporary_directory() as directory:
            root=Path(directory); self.populate(root)
            path=root/'docs/CURRENT-EVIDENCE.md'; before=path.read_text(encoding='utf-8')
            for text in (before.replace('3/3','2/2'),before+'\n'+docs.START):
                path.write_text(text,encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'stale or duplicated'): docs.validate_documents(root,self.report,self.trace)

    def test_missing_duplicate_or_wrong_current_reference_is_rejected(self):
        with temporary_directory() as directory:
            root=Path(directory); self.populate(root)
            path=root/'PROJECT.md'; before=path.read_text(encoding='utf-8')
            for text in ('current 3/3',before+'\n'+docs.LINK,before.replace('docs/CURRENT','docs/OLD')):
                path.write_text(text,encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'single current source'): docs.validate_documents(root,self.report,self.trace)

    def test_failed_or_mismatched_run_cannot_replace_current_evidence(self):
        for changed in ({'status':'failed'},{'run_id':'old'},{'skipped':1}):
            report=deepcopy(self.report); report.update(changed)
            with self.assertRaises(ValueError): docs.render_current(report,self.trace)

    def test_replay_pairs_checkpoints_and_faults_are_not_added_to_dialogue_or_at_counts(self):
        self.trace['local_replays']={'replay_pairs':23,'restoration_checkpoints':256,'fault_scenarios':24}
        text=docs.render_current(self.report,self.trace)
        self.assertIn('原生 SDK＋合成后台对话 **1** 组',text)
        self.assertIn('重建工具重放 **23** 对',text)
        self.assertIn('256 个 JSON／历史恢复检查点、24 个',text)
        self.assertIn('完整业务 AT 执行 **0**',text)

    def test_boundary_subscenarios_are_separate_from_dialogue_and_business_at_counts(self):
        self.trace['local_boundaries']={'receipt_scenarios':32,'gateway_scenarios':16}
        text=docs.render_current(self.report,self.trace)
        self.assertIn('原生 SDK＋合成后台对话 **1** 组',text)
        self.assertIn('32 个回执场景、16 个假网关场景',text)
        self.assertIn('完整业务 AT 执行 **0**',text)
