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
    return (f'实际完整回归 **{report["tests_run"]}/{report["tests_run"]}**，零跳过/失败/错误、退出码 0。'
            f'原生 SDK＋合成后台对话 **{trace["local_dialogues"]["dialogues_passed"]}** 组，'
            f'{len(turns)} 个 user 轮次、{len(calls)} 次 HTTP 调用、{len(writes)} 次业务发送。\n\n'
            f'计划保留 {trace["case_count"]} 案例／{len(plan)} AT；关联 {unique} 个不同 AT、{links} 条关联关系，'
            f'{len(plan)-unique} 条尚未关联首批对话。完整业务 AT 执行 **{trace["business_ats_executed"]}**；'
            '全部本地业务验收由 M6.7 收口，课堂正式评分由 M7 单列。\n\n'
            f'run_id `{report["run_id"]}`；source_sha256 `{report["source_sha256"]}`；'
            f'specification_sha256 `{report["specification_sha256"]}`。')


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
