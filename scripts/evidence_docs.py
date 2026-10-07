"""One current evidence block; historical milestone documents stay historical."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- CURRENT-EVIDENCE:START -->'
END = '<!-- CURRENT-EVIDENCE:END -->'
LINK = '<!-- CURRENT-EVIDENCE:LINK -->'
ENTRY_DOCS = ('PROJECT.md','docs/IMPLEMENTATION-PLAN.md','docs/OPEN-ITEMS.md',
              'docs/FOUNDATION-EVIDENCE.md','docs/FOUNDATION-TEST-MAP.md','docs/STATE-EVIDENCE-RETENTION.md')


def current_link(path):
    target = 'docs/CURRENT-EVIDENCE.md' if path == 'PROJECT.md' else 'CURRENT-EVIDENCE.md'
    return f'当前运行、计数和证据范围统一见 [当前证据]({target})；本文件的里程碑记录保留对应历史范围。'


def render_current(report, trace):
    if (report['status'] != 'passed' or trace['status'] != 'valid' or report['run_id'] != trace['run_id']
            or report['exit_code'] != 0 or any(report[k] != 0 for k in ('skipped','failures','errors'))):
        raise ValueError('Current documentation requires a successful paired run')
    plan = trace['local_dialogues']['plan']
    unique = sum(bool(r['dialogue_ids']) for r in plan)
    links = sum(len(r['dialogue_ids']) for r in plan)
    turns = [t for r in report['dialogue_batch']['results'] for t in r['turns']]
    calls = [c for t in turns for c in t['http_calls']]
    writes = [c for c in calls if c['method'] in {'POST','PUT'} and c['path'] != '/v1/customers/search']
    replay = trace.get('local_replays')
    replay_text = (f'\n\n重建工具重放 **{replay["replay_pairs"]}** 对，'
                   f'{replay["restoration_checkpoints"]} 个 JSON／历史恢复检查点、'
                   f'{replay["fault_scenarios"]} 个重复／中断故障场景。'
                   '重放与故障注入单独计数，不加到原批次对话或完整业务 AT 执行数。') if replay else ''
    boundaries = trace.get('local_boundaries')
    boundary_text = (f'\n\n真实 SDK 边界探针 {boundaries["receipt_scenarios"]} 个回执场景、'
                     f'{boundaries["gateway_scenarios"]} 个假网关场景；合成副作用与拒绝按固定预期核验，'
                     '这些场景单独计数，不增加完整业务 AT 执行数。') if boundaries else ''
    package = trace.get('local_package')
    package_text = (f'\n\n部署审计 {package["package"]["file_count"]} 个文件、'
                    f'源码原始字节 {package["package"]["raw_source_bytes"]}；'
                    f'完整提交 JSON 字节 {package["package"]["payload_bytes"]}。'
                    '复制包逐文件字节在隔离 SDK 运行前后均核对；真实 SDK 导入／工具库存核查通过。'
                    '真实模型成本未实测，token／费用为 unknown。') if package else ''
    business = trace.get('local_business_acceptance')
    defects = trace.get('defect_closure')
    defect_new_label = '台账在 M6.6 新增修复' if business else '本轮新增修复'
    defect_text = (f'\n\n有限根因台账 {defects["incident_count"]} 项：'
                   f'生产缺陷 {defects["by_kind"]["production"]}、测试／证据基础设施 {defects["by_kind"]["test_infrastructure"]}；'
                   f'{defect_new_label} {defects["new_incidents"]} 项，'
                   f'{defects["unique_regressions"]} 个不同回归方法均在本次报告实际通过。'
                   '历史修复不计为新增能力，分类不冒充自动根因证明或完整业务 AT。') if defects else ''
    business_label = '直接本地业务 AT 执行' if business else '完整业务 AT 执行'
    business_complete = bool(business and business['ats_passed_local'] == 522 and business['ats_not_executed'] == 0 and business['cases_complete_local'] == 134)
    business_text = (f'\n\nM6.7 直接本地业务验收{"完成" if business_complete else "进行中"}：{business["scenarios_executed"]} 个独立合成对话，'
                     f'{business["ats_passed_local"]}/522 条原子要求直接通过，{business["ats_not_executed"]} 条未执行；'
                     f'{business["cases_complete_local"]}/134 案例的全部原子要求有本地断言。'
                     '不把组件或首批关联计为执行，不代表原始课堂 fixture／模型效果；'
                     + ('M0.2 和 M6 的本地验收完成，课堂实测仍归 M7。' if business_complete else 'M0.2 和 M6 整体保持未完成。')) if business else ''
    review = business.get('predicate_review_index') if business else None
    review_text = (f'\n\n逐 AT [谓词审阅索引](AT-PREDICATE-REVIEW.md)：{review["assertion_occurrences"]} 次直接谓词检查，'
                   f'{review["distinct_predicates"]} 个按场景区分的定义，{review["shared_predicates"]} 个定义由多个 AT 共用；'
                   f'{review["single_predicate_atoms"]} 条 AT 仅有一个不同的直接谓词。'
                   '字段、期望值、实际判定及审阅队列从固定夹具和本轮观察派生；标记不证明语义充分或存在缺陷。') if review else ''
    return (f'实际完整回归 **{report["tests_run"]}/{report["tests_run"]}**，零跳过/失败/错误、退出码 0。'
            f'原生 SDK＋合成后台对话 **{trace["local_dialogues"]["dialogues_passed"]}** 组，'
            f'{len(turns)} 个 user 轮次、{len(calls)} 次 HTTP 调用、{len(writes)} 次业务发送。\n\n'
            f'计划保留 {trace["case_count"]} 案例／{len(plan)} AT；关联 {unique} 个不同 AT、{links} 条关联关系，'
            f'{len(plan)-unique} 条尚未关联首批对话。{business_label} **{trace["business_ats_executed"]}**；'
            '全部本地业务验收由 M6.7 收口，课堂正式评分由 M7 单列。\n\n'
            f'run_id `{report["run_id"]}`；source_sha256 `{report["source_sha256"]}`；'
            f'specification_sha256 `{report["specification_sha256"]}`。'+replay_text+boundary_text+package_text+defect_text+business_text+review_text)


def update_current(root, report, trace):
    path = root/'docs/CURRENT-EVIDENCE.md'
    text = path.read_text(encoding='utf-8')
    replacement = START+'\n'+render_current(report, trace)+'\n'+END
    text, count = re.subn(re.escape(START)+r'.*?'+re.escape(END), lambda _:replacement, text, flags=re.S)
    if count != 1:
        raise ValueError('Exactly one current evidence block is required')
    path.write_text(text,encoding='utf-8')


def validate_documents(root, report, trace):
    text = (root/'docs/CURRENT-EVIDENCE.md').read_text(encoding='utf-8')
    expected = START+'\n'+render_current(report, trace)+'\n'+END
    if text.count(START) != 1 or text.count(END) != 1 or expected not in text:
        raise ValueError('Current evidence block is stale or duplicated')
    for name in ENTRY_DOCS:
        text = (root/name).read_text(encoding='utf-8')
        if text.count(LINK) != 1 or LINK+'\n'+current_link(name) not in text:
            raise ValueError('Evidence entry must reference the single current source: '+name)


if __name__ == '__main__':
    import argparse
    import importlib.util
    parser=argparse.ArgumentParser()
    parser.add_argument('--update',action='store_true')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('foundation_trace',ROOT/'scripts/foundation_trace.py')
    foundation=importlib.util.module_from_spec(spec); spec.loader.exec_module(foundation)
    report=json.loads((ROOT/'docs/FOUNDATION-RUN.json').read_text(encoding='utf-8'))
    trace=json.loads((ROOT/'docs/AT-TEST-TRACE.json').read_text(encoding='utf-8'))
    foundation.validate_evidence_pair((ROOT/'docs/CASE-REQUIREMENTS.md').read_text(encoding='utf-8'),
                                     report,trace,snapshot=foundation.input_snapshot())
    if args.update: update_current(ROOT,report,trace)
    validate_documents(ROOT,report,trace)
    print('CURRENT_EVIDENCE_PASSED; paired source/spec/run and six linked entry documents')
