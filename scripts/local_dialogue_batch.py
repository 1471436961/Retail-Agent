"""Requirement-linked synthetic dialogue oracles, never a classroom score.

Fixture expectations are fixed before execution. Every atomic requirement stays
in the plan; a related synthetic dialogue does not execute its full public AT.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/m6_dialogues.json'
WRAPPER = 'test_m6_dialogues.NativeDialogueBatchTests.test_default_sdk_dialogue_batch_matches_fixed_oracles'
SCOPE = 'synthetic requirement-linked dialogues; not complete public business ATs'
RUNNER = 'tests/sdk_m6_checks.py'
TOOL_STEP_LIMIT = 12


def tool_step_allowed(steps, pending_count):
    if type(steps) is not int or type(pending_count) is not int or not 0 <= steps < TOOL_STEP_LIMIT or pending_count != 1:
        raise ValueError('Unexpected batch or unbounded internal loop')


def api_path(collection, identifier):
    return '/v1/' + collection + '/' + quote(identifier, safe='')


def context_reads(context):
    return {('POST', '/v1/customers/search'),
            ('GET', api_path('customers', context['customer_id'])),
            *(('GET', api_path('orders', oid)) for oid in context['order_ids']),
            *(('GET', api_path('catalog/products', pid)) for pid in context['product_ids'])}


def readback_path(call, context):
    path = call['path']
    if path == api_path('customers', context['customer_id']) + '/default-shipping-address':
        return api_path('customers', context['customer_id'])
    for oid in context['order_ids']:
        base = api_path('orders', oid)
        if path in {base+'/'+suffix for suffix in ('shipping-address', 'payment-method', 'cancellations', 'item-modifications', 'returns', 'exchanges')}:
            return base
    if path == api_path('conversations', context['conversation_id']) + '/transfers':
        return None
    raise ValueError('Business target is outside fixture context')


def runner_inputs(root=ROOT):
    paths = [RUNNER, 'scripts/local_dialogue_batch.py']
    return {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}


def execution_metadata(run_id, source_sha256, *, mode='native_sdk', sdk_version='1.0.1'):
    return {'mode':mode, 'runner':RUNNER, 'sdk_version':sdk_version,
            'parent_run_id':run_id, 'source_sha256':source_sha256, 'runner_inputs':runner_inputs()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def atomic_inventory(requirements):
    rows = []
    for number, line in enumerate(requirements.splitlines(), 1):
        if not line.startswith('- A'):
            continue
        match = re.fullmatch(r'- (A\d{3}-\d{2}) \[([^;]+); ([A-Z]+(?:,[A-Z]+)*)\] (.+)', line)
        if match is None:
            raise ValueError('Invalid atomic requirement')
        at, sources, groups, text = match.groups()
        rows.append({'at_id': 'AT-'+at, 'case_id': int(at[1:4]), 'requirement_line': number,
                     'sources': sources, 'groups': groups.split(','), 'requirement': text})
    if (len(rows) != 522 or len({r['at_id'] for r in rows}) != 522
            or {r['case_id'] for r in rows} != set(range(134))):
        raise ValueError('The complete 134/522 inventory is required')
    return rows


def apply_patches(value, patches):
    value = deepcopy(value)
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {'path', 'value'} or not patch['path']:
            raise ValueError('A patch needs an exact path and value')
        cursor = value
        for key in patch['path'][:-1]:
            cursor = cursor[key]
        cursor[patch['path'][-1]] = deepcopy(patch['value'])
    return value


def _validate_manifest(manifest, requirements):
    known = {r['at_id'] for r in atomic_inventory(requirements)}
    if (not isinstance(manifest, dict) or set(manifest) != {'schema_version', 'scope', 'scenarios'}
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 2
            or manifest['scope'] != SCOPE or not isinstance(manifest['scenarios'], list)
            or not manifest['scenarios']):
        raise ValueError('Invalid dialogue manifest')
    ids = set()
    for scenario in manifest['scenarios']:
        if (not isinstance(scenario, dict) or set(scenario) != {'id', 'at_ids', 'coverage_note', 'context', 'setup', 'initial_sha256', 'turns', 'final_patches', 'journal', 'handoff'}
                or not isinstance(scenario['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_]+', scenario['id'])
                or scenario['id'] in ids or not isinstance(scenario['coverage_note'], str) or not scenario['coverage_note']
                or not isinstance(scenario['at_ids'], list) or not scenario['at_ids']
                or any(not isinstance(at, str) for at in scenario['at_ids'])
                or len(set(scenario['at_ids'])) != len(scenario['at_ids']) or not set(scenario['at_ids']) <= known
                or not isinstance(scenario['initial_sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', scenario['initial_sha256'])
                or not isinstance(scenario['turns'], list) or not scenario['turns']):
            raise ValueError('Invalid scenario or requirement link')
        ids.add(scenario['id'])
        context = scenario['context']
        if (not isinstance(context, dict) or set(context) != {'conversation_id','customer_id','order_ids','product_ids'}
                or any(not isinstance(context[k], str) or not context[k].strip() for k in ('conversation_id','customer_id'))
                or any(not isinstance(context[k], list) or any(not isinstance(v,str) or not v.strip() for v in context[k])
                       or len(set(context[k])) != len(context[k]) for k in ('order_ids','product_ids'))):
            raise ValueError('Invalid fixture context')
        for field in ('setup', 'final_patches', 'journal'):
            if not isinstance(scenario[field], list):
                raise ValueError('Invalid scenario oracle')
        for turn in scenario['turns']:
            if (not isinstance(turn, dict) or set(turn) - {'user', 'writes', 'reads', 'http_calls', 'assessment', 'no_http', 'identity', 'reply_contains', 'reply_exact'}
                    or not {'user', 'writes', 'reads'} <= set(turn) or not isinstance(turn['user'], str) or not turn['user']
                    or not isinstance(turn['writes'], list) or not isinstance(turn['reads'], list)):
                raise ValueError('Invalid dialogue turn')
            for call in turn['reads']:
                if (not isinstance(call,dict) or set(call) != {'method','path','body'}
                        or (call['method'],call['path']) not in context_reads(context)
                        or (call['method']=='GET' and call['body'] is not None)
                        or (call['method']=='POST' and not isinstance(call['body'],dict))):
                    raise ValueError('Invalid expected read or fixture context')
            for call in turn['writes']:
                if (not isinstance(call, dict) or set(call) != {'method', 'path', 'body'}
                        or call['method'] not in {'POST', 'PUT'} or not isinstance(call['body'], dict)):
                    raise ValueError('Invalid expected business call')
                readback_path(call, context)
    # Also excludes non-JSON fixture values and NaN before native SDK dispatch.
    digest(manifest)
    return deepcopy(manifest)


def validate_manifest(manifest, requirements):
    try:
        return _validate_manifest(manifest, requirements)
    except (TypeError, KeyError, IndexError, OverflowError) as error:
        raise ValueError('Malformed dialogue manifest') from error


def load_manifest():
    return validate_manifest(json.loads(FIXTURE.read_text(encoding='utf-8')),
                             (ROOT/'docs/CASE-REQUIREMENTS.md').read_text(encoding='utf-8'))


def build_plan(requirements, manifest):
    manifest = validate_manifest(manifest, requirements)
    return [{**row, 'dialogue_ids': [s['id'] for s in manifest['scenarios'] if row['at_id'] in s['at_ids']],
             'coverage_milestone':'M6.7', 'business_result': 'not_executed', 'remote_result': 'not_run'}
            for row in atomic_inventory(requirements)]


def business_calls(calls):
    return [c for c in calls if c['method'] in {'PUT', 'POST'} and c['path'] != '/v1/customers/search']


def _verify_scenario(scenario, result):
    if (not isinstance(result, dict) or set(result) != {'id', 'at_ids', 'status', 'context', 'initial_backend', 'turns', 'final_backend', 'journal', 'handoff'}
            or result['id'] != scenario['id'] or result['at_ids'] != scenario['at_ids']
            or result['context'] != scenario['context']
            or result['status'] != 'passed' or len(result['turns']) != len(scenario['turns'])):
        raise ValueError('Incomplete or mismatched dialogue result')
    calls = []
    if digest(result['initial_backend']) != scenario['initial_sha256']:
        raise ValueError('Initial backend does not match the fixed fixture snapshot')
    context = scenario['context']
    customer = result['initial_backend']['customers'][context['customer_id']]
    for oid in context['order_ids']:
        if oid not in customer['order_ids'] or result['initial_backend']['orders'][oid]['customer_id'] != context['customer_id']:
            raise ValueError('Fixture context contains a cross-customer order')
    if any(pid not in result['initial_backend']['products'] for pid in context['product_ids']):
        raise ValueError('Fixture context contains an unknown product')
    for expected, actual in zip(scenario['turns'], result['turns']):
        if (set(actual) != {'user', 'http_calls', 'tool_calls', 'reply', 'assessment', 'identity'}
                or expected['user'] != actual['user']):
            raise ValueError('Turn source mismatch')
        calls.extend(actual['http_calls'])
        if business_calls(calls) != expected['writes']:
            raise ValueError(f"{scenario['id']}: business calls expected {expected['writes']!r}, got {business_calls(calls)!r}")
        if expected.get('no_http') is True and actual['http_calls']:
            raise ValueError('This turn must not access the API')
        for field in ('assessment', 'identity'):
            if field in expected and actual[field] != expected[field]:
                raise ValueError(f"{scenario['id']}: {field} expected {expected[field]!r}, got {actual[field]!r}")
        if 'reply_exact' in expected and actual['reply'] != expected['reply_exact']:
            raise ValueError('Required transfer notice mismatch')
        if any(t not in actual['reply'] for t in expected.get('reply_contains', [])):
            raise ValueError('Required facts are absent from reply')
        # Fail closed on extra/unexpected API paths, including off-scope reads.
        allowed_reads = context_reads(context)
        expected_writes = {(c['method'], c['path']) for c in expected['writes']}
        if any((c['method'], c['path']) not in allowed_reads | expected_writes for c in actual['http_calls']):
            raise ValueError('Unexpected or cross-customer API call')
        if [c for c in actual['http_calls'] if c not in business_calls(actual['http_calls'])] != expected['reads']:
            raise ValueError('Exact read trajectory mismatch')
        if 'http_calls' in expected and actual['http_calls'] != expected['http_calls']:
            raise ValueError('Exact full trajectory mismatch')
    oracle = apply_patches(result['initial_backend'], scenario['final_patches'])
    if any(o['status']=='succeeded' for o in scenario['journal']):
        for index, call in enumerate(calls):
            if call in business_calls(calls) and not call['path'].endswith('/transfers'):
                path = readback_path(call, context)
                if not any(c == {'method':'GET','path':path,'body':None} for c in calls[index+1:]):
                    raise ValueError('Verified success needs its own post-write readback')
    if result['final_backend'] != oracle:
        raise ValueError('Final backend differs from the complete fixed oracle')
    if result['journal'] != scenario['journal'] or result['handoff'] != scenario['handoff']:
        raise ValueError('Final journal or handoff outcome mismatch')


def verify_scenario(scenario, result):
    try:
        return _verify_scenario(scenario, result)
    except (TypeError, KeyError, IndexError, OverflowError) as error:
        raise ValueError('Malformed dialogue observations') from error


def validate_batch(batch, manifest):
    if (not isinstance(batch, dict) or set(batch) != {'schema_version', 'scope', 'execution', 'fixture_sha256', 'network_attempts', 'results'}
            or type(batch['schema_version']) is not int or batch['schema_version'] != 2
            or batch['scope'] != SCOPE or batch['fixture_sha256'] != digest(manifest)
            or type(batch['network_attempts']) is not int or batch['network_attempts'] != 0 or not isinstance(batch['results'], list)
            or len(batch['results']) != len(manifest['scenarios'])):
        raise ValueError('Stale, unsafe or incomplete dialogue batch')
    execution = batch['execution']
    if (not isinstance(execution,dict) or set(execution) != {'mode','runner','sdk_version','parent_run_id','source_sha256','runner_inputs'}
            or execution['mode'] not in {'native_sdk','oracle_control'} or execution['runner'] != RUNNER
            or execution['sdk_version'] != '1.0.1' or execution['runner_inputs'] != runner_inputs()
            or not isinstance(execution['parent_run_id'],str) or not execution['parent_run_id']
            or not isinstance(execution['source_sha256'],str) or not execution['source_sha256']):
        raise ValueError('Invalid execution provenance')
    for scenario, result in zip(manifest['scenarios'], batch['results']):
        verify_scenario(scenario, result)
    return deepcopy(batch)


def trace_dialogues(requirements, report, *, allow_oracle_control=False):
    manifest = load_manifest()
    if 'dialogue_batch' not in report:
        if report['results'].get(WRAPPER) == 'passed':
            raise ValueError('Native dialogue wrapper passed but batch evidence is missing')
        return None
    if report['results'].get(WRAPPER) != 'passed':
        raise ValueError('Dialogue evidence needs a successful native SDK wrapper')
    batch = validate_batch(report['dialogue_batch'], manifest)
    execution = batch['execution']
    if (execution['parent_run_id'] != report['run_id'] or execution['source_sha256'] != report['source_sha256']
            or (execution['mode'] != 'native_sdk' and not allow_oracle_control)):
        raise ValueError('Dialogue execution provenance does not match this native run')
    return {'scope': SCOPE, 'dialogues_passed': len(batch['results']),
            'execution':deepcopy(execution),
            'fixture_sha256': batch['fixture_sha256'], 'wrapper_test_id': WRAPPER,
            'complete_business_ats_executed': 0, 'plan': build_plan(requirements, manifest)}
