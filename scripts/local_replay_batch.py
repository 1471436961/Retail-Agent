"""M6.3 native replay evidence, separate from original dialogue/AT counts.

Equality against a second run is supplemental: both runs must first satisfy
the unchanged M6.1/M6.2 fixed oracles. Hashes locate observations; they are not
signatures, durable claims, or evidence of real classroom payments.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNNER = 'tests/sdk_m6_replay_checks.py'
WRAPPER = 'test_m6_replays.NativeReplayTests.test_native_rebuilt_toolkits_replay_and_faults_match_fixed_contracts'
SCOPE = 'native synthetic replay and interruption checks; not additional business ATs'
FAULT_CASES = (
    ('order_address', 'address', 'shipping_address'),
    ('default_address', 'address', 'default_shipping_address'),
    ('whole_gift_payment', 'payment', 'payment_method'),
    ('whole_cancellation', 'cancellation', 'cancel'),
    ('complete_items', 'items', 'modify_items'),
    ('complete_return', 'returns', 'return'),
    ('complete_exchange', 'exchange', 'exchange'),
    ('human', 'handoff', 'handoff'),
)
FAULT_MODES = ('duplicate_receipt', 'lost_execute_result', 'timeout_after_effect')
HASH = re.compile(r'[0-9a-f]{64}')
_spec = importlib.util.spec_from_file_location('replay_dialogue_oracles', ROOT/'scripts/local_dialogue_batch.py')
_dialogues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dialogues)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def message_data(value):
    """Exclude only SDK creation wall time; retain IDs, text and arguments."""
    result = deepcopy(value)
    result.pop('timestamp', None)
    return result


def runner_inputs():
    paths = (RUNNER, 'tests/sdk_m6_checks.py', 'scripts/local_replay_batch.py',
             'scripts/local_dialogue_batch.py', 'tests/fixtures/m6_dialogues.json',
             'tests/fixtures/m6_combinations.json')
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def execution_metadata(run_id, source_sha256, *, mode='native_sdk', sdk_version='1.0.1'):
    return {'mode': mode, 'runner': RUNNER, 'sdk_version': sdk_version,
            'parent_run_id': run_id, 'source_sha256': source_sha256,
            'runner_inputs': runner_inputs()}


def _validate(batch, manifest, *, allow_oracle_control=False):
    if (set(batch) != {'schema_version', 'scope', 'fixture_sha256', 'execution',
                      'network_attempts', 'replays', 'faults'}
            or type(batch['schema_version']) is not int or batch['schema_version'] != 1
            or batch['scope'] != SCOPE or batch['fixture_sha256'] != digest(manifest)
            or type(batch['network_attempts']) is not int or batch['network_attempts'] != 0):
        raise ValueError('Invalid replay envelope')
    execution = batch['execution']
    modes = {'native_sdk', 'oracle_control'} if allow_oracle_control else {'native_sdk'}
    if (set(execution) != {'mode', 'runner', 'sdk_version', 'parent_run_id', 'source_sha256', 'runner_inputs'}
            or execution['mode'] not in modes or execution['runner'] != RUNNER
            or execution['sdk_version'] != '1.0.1' or execution['runner_inputs'] != runner_inputs()
            or any(not isinstance(execution[k], str) or not execution[k]
                   for k in ('parent_run_id', 'source_sha256'))):
        raise ValueError('Invalid native replay provenance')
    replays = batch['replays']
    if not isinstance(replays, list) or len(replays) != len(manifest['scenarios']):
        raise ValueError('Missing replay scenario')
    for expected, replay in zip(manifest['scenarios'], replays):
        if (set(replay) != {'id', 'first', 'rebuilt', 'checkpoints'} or replay['id'] != expected['id']
                or type(replay['checkpoints']) is not int or replay['checkpoints'] < len(expected['turns'])
                or replay['first'] != replay['rebuilt']):
            raise ValueError('Replay differs or omits restoration')
        trajectory = replay['first']
        if set(trajectory) != {'initial_backend', 'final_backend', 'result', 'frames'}:
            raise ValueError('Incomplete replay trajectory')
        for key in ('initial_backend', 'final_backend'):
            if not isinstance(trajectory[key], str) or not HASH.fullmatch(trajectory[key]):
                raise ValueError('Invalid trajectory hash')
        if trajectory['initial_backend'] != expected['initial_sha256']:
            raise ValueError('Replay did not start from the fixed backend')
        _dialogues.verify_scenario(expected, trajectory['result'])
        if (digest(trajectory['result']['initial_backend']) != trajectory['initial_backend']
                or digest(trajectory['result']['final_backend']) != trajectory['final_backend']):
            raise ValueError('Replay hashes disagree with fixed-oracle observations')
        frames = trajectory['frames']
        if not isinstance(frames, list) or not frames:
            raise ValueError('Missing full tool trajectory')
        for frame in frames:
            if (set(frame) != {'event', 'message', 'evidence', 'http_calls'}
                    or frame['event'] not in {'user', 'tool', 'result', 'reply'}
                    or any(not isinstance(frame[k], str) or not HASH.fullmatch(frame[k])
                           for k in ('message', 'evidence', 'http_calls'))):
                raise ValueError('Malformed trajectory frame')
        if ([f['event'] for f in frames].count('user') != len(expected['turns'])
                or [f['event'] for f in frames].count('reply') != len(expected['turns'])
                or [f['event'] for f in frames].count('tool') != [f['event'] for f in frames].count('result')):
            raise ValueError('Truncated trajectory')
        if replay['checkpoints'] != 2*len(expected['turns']) + sum(f['event'] == 'tool' for f in frames):
            raise ValueError('Restoration checkpoint count disagrees with trajectory')
        if sum(f['event'] == 'tool' for f in frames) != sum(len(t['tool_calls']) for t in trajectory['result']['turns']):
            raise ValueError('Tool frames disagree with native result inventory')
    faults = batch['faults']
    expected_faults = [(sid, kind, action, mode) for sid, kind, action in FAULT_CASES for mode in FAULT_MODES]
    if not isinstance(faults, list) or len(faults) != len(expected_faults):
        raise ValueError('Missing interruption scenario')
    for expected, row in zip(expected_faults, faults):
        sid, kind, action, mode = expected
        if (set(row) != {'id', 'kind', 'action', 'mode', 'sends', 'extra_sends', 'status',
                         'before', 'after', 'claim_code', 'investigation_reads', 'late_status'}
                or (row['id'], row['kind'], row['action'], row['mode']) != expected
                or type(row['sends']) is not int or row['sends'] != 1
                or type(row['extra_sends']) is not int or row['extra_sends'] != 0
                or row['before'] != row['after'] or not isinstance(row['before'], str)
                or not HASH.fullmatch(row['before'])
                or type(row['investigation_reads']) is not int or row['investigation_reads'] < 0
                or row['claim_code'] != ('handoff_claim_conflict' if kind == 'handoff' else 'write_already_claimed')):
            raise ValueError('Duplicate send, changed evidence or wrong claim guard')
        status = ('accepted' if kind == 'handoff' else 'succeeded') if mode == 'duplicate_receipt' else 'unknown'
        if row['status'] != status or row['late_status'] != status:
            raise ValueError('Duplicate/interrupted result was promoted or cleared')
        if mode == 'timeout_after_effect' and kind != 'handoff':
            if row['investigation_reads'] < 1:
                raise ValueError('Accepted Unknown investigation was not exercised')
        elif row['investigation_reads'] != 0:
            raise ValueError('Lost result or terminal handoff must not read')
    return deepcopy(batch)


def validate_batch(batch, manifest, *, allow_oracle_control=False):
    try:
        return _validate(batch, manifest, allow_oracle_control=allow_oracle_control)
    except (TypeError, KeyError, IndexError) as error:
        raise ValueError('Malformed replay evidence') from error


def trace_replays(report, manifest, *, allow_oracle_control=False):
    if 'replay_batch' not in report:
        if report['results'].get(WRAPPER) == 'passed':
            raise ValueError('Native replay wrapper passed but observations are missing')
        return None
    if report['results'].get(WRAPPER) != 'passed':
        raise ValueError('Replay observations require a passed native wrapper')
    batch = validate_batch(report['replay_batch'], manifest, allow_oracle_control=allow_oracle_control)
    execution = batch['execution']
    if execution['parent_run_id'] != report['run_id'] or execution['source_sha256'] != report['source_sha256']:
        raise ValueError('Replay provenance belongs to another run')
    return {'scope': SCOPE, 'execution': execution, 'fixture_sha256': batch['fixture_sha256'],
            'wrapper_test_id': WRAPPER, 'replay_pairs': len(batch['replays']),
            'restoration_checkpoints': sum(r['checkpoints'] for r in batch['replays']),
            'fault_scenarios': len(batch['faults']), 'complete_business_ats_executed': 0}
