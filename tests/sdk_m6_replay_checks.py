"""Native M6.3 worker. Real SDK, synthetic transport, blocked network.

Imports the existing offline worker so its audit hook guards this process too.
The original fixed fixtures are inputs, never rewritten from observations.
"""
import sdk_m6_checks as native
import argparse
from copy import deepcopy
import json
from importlib.metadata import version
from unittest.mock import Mock

from local_replay_batch import FAULT_CASES, FAULT_MODES, SCOPE, digest, execution_metadata, validate_batch, message_data
from support_agent.state import clone_state, initial_state
from support_agent.amount_summary import summarize_amounts
from support_agent.workflow_registry import WORKFLOW_KINDS

EVIDENCE_KEYS = ('history', 'identity', 'identity_evidence', 'proposals', 'tasks', 'operations',
                 'handoff', 'pending_calls', 'customer_record',
                 *(k+'_pending' for k in WORKFLOW_KINDS))


def evidence(state):
    return {key: deepcopy(state[key]) for key in EVIDENCE_KEYS}


def restore(state, backend):
    before = deepcopy(backend.calls)
    copied = clone_state(json.loads(json.dumps(state, allow_nan=False)))
    rebuilt = initial_state(deepcopy(state['history']))
    assert copied == state and evidence(rebuilt) == evidence(state)
    assert backend.calls == before
    return copied


def replay(scenario, *, rebuilt):
    frames = []
    checkpoints = 0
    def observe(event, message, data, toolkit, backend):
        nonlocal checkpoints
        if event == 'restore':
            checkpoints += 1
            return
        frames.append({'event': event, 'message': digest(message_data(message.model_dump(mode='json'))),
                       'evidence': digest(data), 'http_calls': digest(backend.calls)})
    result = native.execute(scenario, observer=observe, restore=rebuilt)
    return {'initial_backend': native.digest(result['initial_backend']),
            'final_backend': digest(result['final_backend']), 'result': result, 'frames': frames}, checkpoints


class Rig:
    """New toolkit/agent per resume; the claim store stays with this backend."""
    def __init__(self, scenario):
        self.scenario = scenario
        self.backend = native.MatrixBackend()
        self.initial = native.apply_patches(native.backend_snapshot(self.backend), scenario['setup'])
        self.reset_backend()
        assert native.digest(self.initial) == scenario['initial_sha256']
        self.claims = native.SessionClaims()
        self.timeout = False
        self.model = Mock()
        self.model.decide.side_effect = AssertionError('Replay unexpectedly called a model')
        self.agent = native.CustomerAgent(model_adapter=self.model)
        self.state = self.agent.get_init_state()
        self.rebuild()

    def reset_backend(self):
        for key, value in self.initial.items():
            setattr(self.backend, key, deepcopy(value))

    def rebuild(self):
        def transport(request):
            response = self.backend.request(request['method'], request['path'], body=request.get('body'))
            if self.timeout and request['method'] in {'PUT', 'POST'} and request['path'] != '/v1/customers/search':
                raise TimeoutError('synthetic timeout after effect')
            return {'status_code': response.status_code, 'body': response.body, 'headers': {}, 'elapsed_seconds': 0.0}
        self.toolkit = native.Tools(native.ClientAPI(transport, context=native.ClientAPIContext(
            conversation_id=self.scenario['context']['conversation_id'])), claims=self.claims)
        self.agent = native.CustomerAgent(model_adapter=self.model)
        self.state = restore(self.state, self.backend)

    def sends(self):
        return [c for c in self.backend.calls if c[0] in {'POST', 'PUT'} and c[1] != '/v1/customers/search']

    def deliver(self, call, payload, *, error=False):
        message, self.state = self.agent.generate_next_message(native.MultiToolMessage(role='tool', tool_messages=[
            native.ToolMessage(role='tool', id=call.id, content=json.dumps(payload), error=error)]), self.state)
        return message

    def user(self, text, *, stop_execute=False):
        message, self.state = self.agent.generate_next_message(native.UserMessage(role='user', content=text), self.state)
        steps = 0
        while message.tool_calls:
            native.tool_step_allowed(steps, len(message.tool_calls)); steps += 1
            call = message.tool_calls[0]
            pending = [self.state[k+'_pending'] for k in WORKFLOW_KINDS if self.state[k+'_pending'] is not None]
            if stop_execute and (call.name == 'handoff_workflow' or any(p['mode'] == 'execute' for p in pending)):
                return call
            payload = getattr(self.toolkit, call.name)(**call.arguments)
            message = self.deliver(call, payload)
        return message

    def execute_snapshot(self):
        for turn in self.scenario['turns']:
            candidate = self.user(turn['user'], stop_execute=True)
            if hasattr(candidate, 'name'):
                return candidate
        raise AssertionError('Fixed scenario did not reach an execute dispatch')


def operation_evidence(state):
    # Include complete operations, not just status; identity/consent and every
    # write receipt/readback index must survive the duplicate/investigation.
    return {key: deepcopy(state[key]) for key in ('operations', 'identity', 'identity_evidence')}


def fault(scenario, kind, action, mode):
    rig = Rig(scenario)
    call = rig.execute_snapshot()
    snapshot = deepcopy(rig.state)
    assert not rig.sends()
    rig.rebuild()  # Recovery before send may send once after original consent.
    rig.timeout = mode == 'timeout_after_effect'
    payload = getattr(rig.toolkit, call.name)(**call.arguments)
    assert len(rig.sends()) == 1
    if kind != 'handoff':
        writes = [o for o in payload['state']['operations'] if o['mutates']]
        assert len(writes) == 1 and writes[0]['spec']['action'] == action
        assert writes[0]['status'] == ('unknown' if rig.timeout else 'succeeded')
    else:
        assert payload['state']['handoff']['status'] == ('unknown' if rig.timeout else 'accepted')
    if mode == 'lost_execute_result':
        rig.deliver(call, {}, error=True)
        status = rig.state['handoff']['status'] if kind == 'handoff' else rig.state[kind+'_pending']['status']
        assert status == 'unknown'
        assert not [o for o in rig.state['operations'] if o['mutates']]
    else:
        rig.deliver(call, payload)
        status = rig.state['handoff']['status'] if kind == 'handoff' else next(o['status'] for o in rig.state['operations'] if o['mutates'])
    rig.timeout = False
    rig.rebuild()
    stable = operation_evidence(rig.state)
    before = digest(stable)
    count = len(rig.backend.calls)
    amounts = summarize_amounts(rig.state, ['#TEST1']) if kind != 'handoff' else None
    rig.deliver(call, payload)  # Duplicate or late valid bundle cannot repair loss.
    assert not rig.state.get('session_block')
    assert operation_evidence(rig.state) == stable
    after = digest(operation_evidence(rig.state))
    if amounts is not None:
        assert summarize_amounts(rig.state, ['#TEST1']) == amounts
    assert len(rig.backend.calls) == count
    late_status = rig.state['handoff']['status'] if kind == 'handoff' else (
        rig.state[kind+'_pending']['status'] if mode == 'lost_execute_result' else
        next(o['status'] for o in rig.state['operations'] if o['mutates']))
    assert late_status == status
    investigation = 0
    if mode != 'duplicate_receipt':
        rig.rebuild()
        before_calls = len(rig.backend.calls)
        rig.user('show my profile')
        investigation = len(rig.backend.calls)-before_calls
        assert operation_evidence(rig.state) == stable or (mode == 'timeout_after_effect' and kind != 'handoff'
            and [o for o in rig.state['operations'] if o['mutates']] == [o for o in stable['operations'] if o['mutates']])
        # A bare yes after an investigation is an ordinary unresolved request,
        # and may reach an explicitly injected model. Exercise a real business
        # request instead; lost bundles and terminal handoffs still block yes.
        follow_up = (scenario['turns'][-2]['user'] if mode == 'timeout_after_effect'
                     and kind != 'handoff' else 'yes')
        rig.user(follow_up)
        assert len(rig.sends()) == 1
        assert [o for o in rig.state['operations'] if o['mutates']] == [o for o in stable['operations'] if o['mutates']]
        if mode == 'lost_execute_result':
            assert (rig.state['handoff']['status'] if kind == 'handoff' else rig.state[kind+'_pending']['status']) == 'unknown'
        elif kind == 'handoff':
            assert rig.state['handoff']['status'] == 'unknown'
    # Remove the *backend* status/fact gate, retaining the actual shared store:
    # a second toolkit must reach the claim guard on the old execute snapshot.
    rig.reset_backend()
    rig.rebuild()
    sent_before = len(rig.sends())
    retry = getattr(rig.toolkit, call.name)(**call.arguments)
    if kind == 'handoff':
        claim_code = retry['state']['history'][-2]['handoff_event']['error_code']
    else:
        codes = [r['code'] for r in retry['assessment']['details']['records']]
        assert 'write_already_claimed' in codes, codes
        claim_code = 'write_already_claimed'
    assert len(rig.sends()) == sent_before == 1
    assert json.loads(call.arguments['session_json']) == snapshot
    rig.model.decide.assert_not_called()
    return {'id': scenario['id'], 'kind': kind, 'action': action, 'mode': mode,
            'sends': sent_before, 'extra_sends': len(rig.sends())-sent_before,
            'status': status, 'before': before, 'after': after,
            'claim_code': claim_code, 'investigation_reads': investigation, 'late_status': late_status}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-run-id', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    manifest = native.load_manifest()
    replays = []
    for scenario in manifest['scenarios']:
        first, original_checkpoints = replay(scenario, rebuilt=False)
        rebuilt, checkpoints = replay(scenario, rebuilt=True)
        assert first == rebuilt, scenario['id']
        # Each user boundary, each tool dispatch, and each terminal reply has a
        # real JSON/history restore. Count these actual calls, not HTTP reads.
        assert original_checkpoints == 0
        assert checkpoints == 2*len(scenario['turns']) + sum(f['event'] == 'tool' for f in rebuilt['frames'])
        replays.append({'id': scenario['id'], 'first': first, 'rebuilt': rebuilt, 'checkpoints': checkpoints})
    scenarios = {s['id']: s for s in manifest['scenarios']}
    faults = []
    for sid, kind, action in FAULT_CASES:
        for mode in FAULT_MODES:
            try:
                faults.append(fault(scenarios[sid], kind, action, mode))
            except Exception:
                print('M6_REPLAY_FAULT_FAILED '+sid+' '+mode, file=native.sys.stderr)
                raise
    batch = {'schema_version': 1, 'scope': SCOPE, 'fixture_sha256': digest(manifest),
             'execution': execution_metadata(args.parent_run_id, args.source_sha256, sdk_version=version('tau2')),
             'network_attempts': len(native.network_attempts), 'replays': replays, 'faults': faults}
    validate_batch(batch, manifest)
    print('M6_REPLAY_JSON='+json.dumps(batch, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    print('M6_REPLAY_SDK_CHECK_PASSED; rebuilt toolkits, fixed backend, duplicate and interrupted outcomes; network attempts 0')


if __name__ == '__main__':
    main()
