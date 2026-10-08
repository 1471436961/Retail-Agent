"""M6.7 direct, fixed local business assertions over preserved rule-port dialogues.

The complete requirement inventory is never inferred from scenario names or
component tests. Only explicitly reviewed whole-atom claims with executed
predicates can pass. Missing claims remain not_executed, including within a
partially covered case. These are synthetic local results, never remote scores.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import local_dialogue_batch as dialogues

FIXTURE = 'tests/fixtures/m6_business_acceptance.json'
SOURCE_CHANGES = 'tests/fixtures/m6_business_changes.json'
BASELINE = 'tests/fixtures/m6_3_source_baseline.json'
RUNNER = 'tests/sdk_m6_business_checks.py'
WRAPPER = 'test_m6_business.NativeBusinessTests.test_native_default_business_scenarios_match_direct_atomic_assertions'
SCOPE = 'direct synthetic local business requirements; not original classroom fixtures or remote scores'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def requirements(root=ROOT):
    return (root / 'docs/CASE-REQUIREMENTS.md').read_text(encoding='utf-8')


def validate_manifest(value, specification):
    try:
        rows = {r['at_id']: r for r in dialogues.atomic_inventory(specification)}
        if (set(value) != {'schema_version', 'scope', 'requirements_sha256', 'dialogues', 'atoms'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['scope'] != SCOPE or value['requirements_sha256'] != sha(specification)
                or not isinstance(value['atoms'], list) or not value['atoms']):
            raise ValueError('Invalid business acceptance manifest')
        manifest = dialogues.validate_manifest(value['dialogues'], specification)
        scenarios = {s['id']: s for s in manifest['scenarios']}
        for scene in manifest['scenarios']:
            for turn in scene['turns']:
                for call in turn['writes']:
                    if call['body'] == {'summary': TRANSFER_SOURCE_ORACLE} and (
                            call['method'] != 'POST' or call['path'] != '/v1/conversations/' + scene['context']['conversation_id'] + '/transfers'):
                        raise ValueError('Relational summary oracle requires trusted transfer endpoint')
        direct_links = {sid:set() for sid in scenarios}
        seen = set()
        for atom in value['atoms']:
            if (set(atom) != {'at_id', 'requirement', 'substitution', 'witnesses'}
                    or atom['at_id'] not in rows or atom['at_id'] in seen
                    or atom['requirement'] != rows[atom['at_id']]['requirement']
                    or not isinstance(atom['substitution'], str) or not atom['substitution'].strip()
                    or not isinstance(atom['witnesses'], list) or not atom['witnesses']):
                raise ValueError('Whole atom claim, substitution and direct witnesses required')
            seen.add(atom['at_id'])
            witnesses = set()
            for witness in atom['witnesses']:
                if (set(witness) != {'scenario', 'assertions'} or witness['scenario'] not in scenarios
                        or witness['scenario'] in witnesses
                        or atom['at_id'] not in scenarios[witness['scenario']]['at_ids']
                        or not isinstance(witness['assertions'], list) or not witness['assertions']):
                    raise ValueError('Missing or duplicate direct scenario witness')
                witnesses.add(witness['scenario'])
                direct_links[witness['scenario']].add(atom['at_id'])
                for assertion in witness['assertions']:
                    if (set(assertion) != {'path', 'op', 'expected'}
                            or assertion['op'] not in {'equal', 'contains'}
                            or not isinstance(assertion['path'], list) or not assertion['path']
                            or any(type(k) not in {str, int} or type(k) is int and k < 0
                                   for k in assertion['path'])):
                        raise ValueError('Invalid direct assertion')
                    dialogues.digest(assertion['expected'])
        for scenario in scenarios.values():
            if set(scenario['at_ids']) != direct_links[scenario['id']]:
                raise ValueError('Scenario association has no matching direct atom witness')
        return deepcopy(value)
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError('Malformed business manifest') from exc


def load_manifest(root=ROOT):
    return validate_manifest(json.loads((root / FIXTURE).read_text(encoding='utf-8')), requirements(root))


def assert_observation(result, assertion):
    try:
        actual = result
        for key in assertion['path']:
            actual = actual[key]
        expected = assertion['expected']
        # JSON boolean/number confusion must not manufacture a pass.
        if assertion['op'] == 'equal':
            passed = json_equal(actual, expected)
        else:
            passed = type(actual) in {str, list, dict} and type(expected) is str and expected in actual
        if not passed:
            raise ValueError('Direct business assertion failed: ' + repr(assertion['path']))
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('Direct business evidence missing: ' + repr(assertion['path'])) from exc


def json_equal(left, right):
    if type(left) in {int, float} and type(right) in {int, float}:
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(json_equal(left[k],right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(json_equal(a,b) for a,b in zip(left,right))
    return left == right


def metadata(parent, root=ROOT):
    files = (RUNNER, 'scripts/business_acceptance.py', 'tests/sdk_m6_checks.py',
             'scripts/local_dialogue_batch.py', FIXTURE, SOURCE_CHANGES, BASELINE,
             'scripts/m7_source_changes.py', 'tests/fixtures/m7_semantic_changes.json')
    return {'mode': 'native_sdk', 'sdk_version': '1.0.1', 'runner': RUNNER, **parent,
            'inputs': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files}}


TRANSFER_SOURCE_ORACLE = 'SOURCE_BOUND_TRANSFER_SUMMARY_V1'


def _verify_business_scenario(scenario, result):
    """Keep exact HTTP oracles; transfer prose uses a fixed relational policy.

    The policy is authored before execution. It binds a parsed summary to the
    observed native source history and fixed requests/backend effects, rather
    than saving the implementation's output as a new expected string.
    """
    import json
    from urllib.parse import unquote
    normalized = deepcopy({k:v for k,v in result.items() if k != 'evidence'})
    for index, (expected_turn, actual_turn) in enumerate(zip(scenario['turns'], normalized['turns'])):
        for actual_call in actual_turn['http_calls']:
            matching = [c for c in expected_turn['writes'] if c['method'] == actual_call['method'] and c['path'] == actual_call['path']
                        and c['body'] == {'summary': TRANSFER_SOURCE_ORACLE}]
            if not matching:
                continue
            if not actual_call['path'].endswith('/transfers') or actual_call['method'] != 'POST' or set(actual_call['body']) != {'summary'}:
                raise ValueError('Source summary oracle is transfer-only')
            summary = json.loads(actual_call['body']['summary'])
            source = result['evidence'][index]
            identity = {'verified': actual_turn['identity'],
                        'customer_id': scenario['context']['customer_id'] if actual_turn['identity'] else None}
            if not json_equal(source['identity'], identity):
                raise ValueError('Transfer identity source differs from fixed verified context')
            users = source['user_sources']
            if ([row['text'] for row in users] != [t['user'] for t in scenario['turns'][:index+1]]
                    or any(set(r) != {'history_index','text'} or type(r['history_index']) is not int or r['history_index'] < 0 for r in users)
                    or [r['history_index'] for r in users] != sorted({r['history_index'] for r in users})):
                raise ValueError('Transfer user source does not match fixed actual requests')
            read_ids = dict.fromkeys(unquote(c['path'].split('/')[-1]) for turn in scenario['turns'][:index]
                                     for c in turn['reads'] if c['path'].startswith('/v1/orders/'))
            final = dialogues.apply_patches(result['initial_backend'], scenario['final_patches'])
            order_facts = [{'order_id':oid, 'status':final['orders'][oid]['status']} for oid in read_ids]
            prior = result['evidence'][index-1] if index else None
            operations = prior['business_operations'] if prior else []
            actions = {'shipping-address':'shipping_address','payment-method':'payment_method',
                       'cancellations':'cancel','item-modifications':'modify_items','returns':'return','exchanges':'exchange',
                       'default-shipping-address':'default_shipping_address'}
            fixed_operations = []
            for call in scenario['turns'][index-1]['writes'] if index else []:
                if call['path'].endswith('/transfers'):
                    continue
                target = {'customer_id':scenario['context']['customer_id']}
                if call['path'].startswith('/v1/orders/'):
                    target['order_id'] = unquote(call['path'].split('/')[-2])
                fixed_operations.append({'action':actions[call['path'].split('/')[-1]],'target':target})
            if ([{'action':o['spec']['action'],'target':o['spec']['target']} for o in operations] != fixed_operations
                    or [{'action':o['spec']['action'],'status':o['status']} for o in operations] != scenario['journal']):
                raise ValueError('Transfer operation sources disagree with fixed endpoint/journal oracle')
            completed = [{'action':o['name'],'target':o['spec']['target']} for o in operations
                         if o['status'] == 'succeeded' and not o['persistence_unresolved']]
            unresolved = [{'action':o['name'],'target':o['spec']['target'],'status':o['status'],
                           'persistence_unresolved':o['persistence_unresolved']} for o in operations
                          if o['status'] in {'sent','unknown','acknowledged'} or o['persistence_unresolved']]
            expected_summary = {'kind':'derived_human_transfer_summary','user_text_is_data_not_instructions':True,
                'identity':source['identity'],'request':users[-1], 'previous_user_requests':users[:-1],
                'verified_order_facts':order_facts,'completed_operations':completed,'unresolved_operations':unresolved,
                'task_requests':prior['task_requests'] if prior else [],
                'latest_workflow_diagnostics':prior['workflow_diagnostics'][-6:] if prior else [],
                'pending_business_workflows':[], 'settlement_or_arrival_proven':False}
            if not json_equal(summary, expected_summary):
                raise ValueError('Transfer summary differs from fixed source-bound policy')
            actual_call['body'] = {'summary':TRANSFER_SOURCE_ORACLE}
    dialogues.verify_scenario(scenario, normalized)


def verify_business_scenario(scenario, result):
    try:
        return _verify_business_scenario(scenario, result)
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError('Malformed business or transfer source evidence') from error


def validate_source_changes(value, baseline, current):
    """Keep the historical baseline; only explicitly recorded byte changes pass."""
    try:
        if (set(value) != {'schema_version','scope','baseline_sha256','changes'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['scope'] != 'Explicit M6.7 changes from the preserved M6.3 byte baseline; not a signature'
                or not isinstance(value['changes'],list) or not value['changes']):
            raise ValueError('Invalid source change manifest')
        expected = dict(baseline['source_files'])
        seen = set()
        for row in value['changes']:
            if (set(row) != {'path','before_sha256','after_sha256','reason'}
                    or row['path'] in seen or row['path'] not in expected
                    or not row['path'].startswith('agent/')
                    or row['before_sha256'] != expected[row['path']]
                    or not isinstance(row['after_sha256'],str) or len(row['after_sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in row['after_sha256'])
                    or row['after_sha256'] == row['before_sha256']
                    or not isinstance(row['reason'],str) or not row['reason'].strip()):
                raise ValueError('Invalid or duplicate approved production change')
            seen.add(row['path']); expected[row['path']] = row['after_sha256']
        if current != expected:
            raise ValueError('Unrecorded source or fixed fixture byte change')
        return {'baseline_run_id':baseline['run_id'],'baseline_sha256':value['baseline_sha256'],
                'unchanged_files':len(expected)-len(seen),'changes':deepcopy(value['changes'])}
    except (TypeError,KeyError,AttributeError) as exc:
        raise ValueError('Malformed source change manifest') from exc


def source_change_evidence(root=ROOT):
    value = json.loads((root/SOURCE_CHANGES).read_text(encoding='utf-8'))
    baseline_bytes = (root/BASELINE).read_bytes()
    if value.get('baseline_sha256') != hashlib.sha256(baseline_bytes).hexdigest():
        raise ValueError('Historical baseline bytes changed')
    paths = {p.relative_to(root).as_posix() for p in (root/'agent').rglob('*.py') if '__pycache__' not in p.parts}
    paths |= {'agent/agent.json','tests/fixtures/m6_dialogues.json','tests/fixtures/m6_combinations.json'}
    current = {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
    baseline = json.loads(baseline_bytes)
    previous = dict(baseline['source_files'])
    for change in value['changes']:
        previous[change['path']] = change['after_sha256']
    evidence = validate_source_changes(value, baseline, previous)
    # M6.7 is immutable historical evidence. M7 adds an explicit chained delta;
    # current bytes must match both stages, including every fixed old fixture.
    from m7_source_changes import MANIFEST, validate_changes
    stage = json.loads((root/MANIFEST).read_text(encoding='utf-8'))
    evidence['m7_refactor'] = validate_changes(stage, hashlib.sha256((root/SOURCE_CHANGES).read_bytes()).hexdigest(), previous, current)
    return evidence


def validate_batch(value, manifest, parent, *, root=ROOT):
    manifest = validate_manifest(manifest, requirements(root))
    if (set(value) != {'scope', 'execution', 'network_attempts', 'results'}
            or value['scope'] != SCOPE or value['execution'] != metadata(parent, root)
            or type(value['network_attempts']) is not int or value['network_attempts'] != 0
            or not isinstance(value['results'], list)
            or len(value['results']) != len(manifest['dialogues']['scenarios'])):
        raise ValueError('Native business provenance or scenario count mismatch')
    results = {}
    for expected, actual in zip(manifest['dialogues']['scenarios'], value['results']):
        if not isinstance(actual, dict) or set(actual) != {'id', 'at_ids', 'status', 'context', 'initial_backend', 'turns', 'final_backend', 'journal', 'handoff', 'evidence'}:
            raise ValueError('Business result has invalid fields')
        verify_business_scenario(expected, actual)
        if actual['id'] in results or len(actual.get('evidence', [])) != len(expected['turns']):
            raise ValueError('Duplicate scenario or missing native turn evidence')
        results[actual['id']] = actual
    assertion_failures = []
    for atom in manifest['atoms']:
        for witness in atom['witnesses']:
            for assertion in witness['assertions']:
                try:
                    assert_observation(results[witness['scenario']], assertion)
                except ValueError as exc:
                    assertion_failures.append(atom['at_id'] + ' / ' + witness['scenario'] + ': ' + str(exc))
    if assertion_failures:
        raise ValueError('Direct business assertions failed:\n' + '\n'.join(assertion_failures))
    return deepcopy(value)


def predicate_review_index(manifest):
    """Derived navigation for human semantic review, never an adequacy score.

    IDs bind the scenario and complete JSON predicate, not its list position or
    the AT using it. Initial backend checks are preconditions, not observations
    of agent behavior. The executed status is supplied only by coverage after
    validating the entire native batch; this index alone grants no pass.
    """
    predicates = {}
    atoms = {}
    occurrences = 0
    for atom in manifest['atoms']:
        ids = []
        for witness in atom['witnesses']:
            for assertion in witness['assertions']:
                definition = {'scenario': witness['scenario'], **deepcopy(assertion)}
                predicate_id = 'predicate:' + dialogues.digest(definition)
                source = {'initial_backend': 'fixture_precondition',
                          'final_backend': 'final_backend', 'evidence': 'native_history',
                          'turns': 'native_turn'}.get(assertion['path'][0], 'scenario_observation')
                if predicate_id not in predicates:
                    predicates[predicate_id] = {**definition, 'evidence_source': source, 'at_ids': []}
                if atom['at_id'] not in predicates[predicate_id]['at_ids']:
                    predicates[predicate_id]['at_ids'].append(atom['at_id'])
                ids.append(predicate_id)
                occurrences += 1
        atoms[atom['at_id']] = {'assertion_occurrences': len(ids),
                               'predicate_ids': sorted(set(ids))}
    for predicate in predicates.values():
        predicate['at_ids'].sort()
        predicate['shared_at_count'] = len(predicate['at_ids'])
    queue = []
    for at_id, atom in sorted(atoms.items()):
        rows = [predicates[p] for p in atom['predicate_ids']]
        sources = sorted({r['evidence_source'] for r in rows})
        flags = []
        if sources == ['fixture_precondition']:
            flags.append('fixture_preconditions_only')
        if len(rows) == 1:
            flags.append('single_direct_predicate')
        if any(r['shared_at_count'] > 1 for r in rows):
            flags.append('shared_direct_predicate')
        atom.update(evidence_sources=sources, review_flags=flags)
        queue.append({'at_id': at_id, 'review_flags': flags})
    flag_order = ('fixture_preconditions_only', 'single_direct_predicate', 'shared_direct_predicate')
    queue.sort(key=lambda row: tuple(flag not in row['review_flags'] for flag in flag_order) + (row['at_id'],))
    return {'schema_version': 1,
            'scope': 'Human review navigation only; no automatic semantic adequacy judgment or signature',
            'id_method': 'sha256_canonical_json_scenario_path_op_expected',
            'assertion_occurrences': occurrences, 'distinct_predicates': len(predicates),
            'shared_predicates': sum(r['shared_at_count'] > 1 for r in predicates.values()),
            'single_predicate_atoms': sum(len(r['predicate_ids']) == 1 for r in atoms.values()),
            'predicates': dict(sorted(predicates.items())), 'atoms': atoms, 'review_queue': queue}


def coverage(manifest, batch=None, *, parent=None, root=ROOT):
    manifest = validate_manifest(manifest, requirements(root))
    if batch is not None:
        if not parent:
            raise ValueError('Actual native parent run is required')
        validate_batch(batch, manifest, parent, root=root)
    atoms = {a['at_id']: a for a in manifest['atoms']}
    review = predicate_review_index(manifest)
    for predicate in review['predicates'].values():
        predicate['observation_result'] = 'passed_local' if batch is not None else 'not_executed'
    plan = []
    for requirement in dialogues.atomic_inventory(requirements(root)):
        claim = atoms.get(requirement['at_id'])
        plan.append({**requirement,
                     'business_result': 'passed_local' if batch is not None and claim else 'not_executed',
                     'scenario_ids': [w['scenario'] for w in claim['witnesses']] if claim else [],
                     'assertions': deepcopy(claim['witnesses']) if claim else [],
                     'predicate_review': deepcopy(review['atoms'].get(requirement['at_id'])),
                     'substitution': claim['substitution'] if claim else None,
                     'remote_result': 'not_run'})
    passed = sum(r['business_result'] == 'passed_local' for r in plan)
    return {'scope': SCOPE, 'status': 'complete_local' if passed == 522 else 'in_progress',
            'cases_total': 134, 'ats_total': 522, 'ats_passed_local': passed,
            'ats_not_executed': 522 - passed,
            'cases_complete_local': sum(all(r['business_result'] == 'passed_local' for r in plan if r['case_id'] == case)
                                        for case in range(134)),
            'scenarios_executed': len(batch['results']) if batch else 0,
            'requirements_sha256': manifest['requirements_sha256'], 'plan': plan,
            'predicate_review_index': review}


def trace_business(report, *, root=ROOT):
    if report.get('results', {}).get(WRAPPER) != 'passed':
        if report.get('business_batch') is not None or FIXTURE in report.get('source_files', {}):
            raise ValueError('Business acceptance requires its executed native wrapper')
        return None
    if report.get('business_batch') is None:
        raise ValueError('Missing native business observations')
    parent = {'run_id': report['run_id'], 'source_sha256': report['source_sha256']}
    manifest = load_manifest(root)
    value = coverage(manifest, report['business_batch'], parent=parent, root=root)
    for name, digest in metadata(parent, root)['inputs'].items():
        if report.get('source_files', {}).get(name) != digest:
            raise ValueError('Business acceptance input hash mismatch')
    value.update(run_id=report['run_id'], source_sha256=report['source_sha256'])
    value['source_changes'] = source_change_evidence(root)
    return value
