"""Isolated native SDK execution of fixed M6.1 synthetic dialogue batches."""
import os
import sys
from pathlib import Path

os.environ.update(PYTHON_DOTENV_DISABLED='1', HF_HUB_OFFLINE='1',
                  LITELLM_TELEMETRY='False', LITELLM_LOCAL_MODEL_COST_MAP='True')
network_attempts = []
probe = True
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        if not probe:
            network_attempts.append(event)
        raise RuntimeError('Offline M6 network guard')
sys.addaudithook(audit)
# Positive control never opens a socket or contacts a service.
try:
    sys.audit('socket.connect', None, ('127.0.0.1', 0))
except RuntimeError:
    pass
else:
    raise AssertionError('Network guard is ineffective')
probe = False
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'agent'))
sys.path.insert(0, str(root/'scripts'))

import json
import argparse
from importlib.metadata import version
from copy import deepcopy
from tau2.data_model.message import UserMessage, AssistantMessage, MultiToolMessage, ToolMessage
from tau2.hyper.client_api import ClientAPI, ClientAPIContext
from tau2.environment.toolkit import ToolType
from tools import Tools
from support_agent.application import CustomerAgent
from support_agent.adapters.write_runtime import SessionClaims
from support_agent.adapters.client_api import ClientAPIError
from support_agent.protocol import READ_TOOL_FIELDS, WORKFLOW_TOOL_NAMES
from test_m5_matrix import MatrixBackend
from local_dialogue_batch import load_manifest, apply_patches, digest, verify_scenario, validate_batch, SCOPE, tool_step_allowed, execution_metadata


def backend_snapshot(api):
    return deepcopy({'customers': api.customers, 'orders': api.orders, 'products': api.products})


def execute(scenario, *, observer=None, restore=False, backend_factory=MatrixBackend, verifier=verify_scenario):
    backend = backend_factory()
    snapshot = apply_patches(backend_snapshot(backend), scenario['setup'])
    for key, value in snapshot.items():
        setattr(backend, key, value)
    initial = backend_snapshot(backend)
    def transport(request):
        response = backend.request(request['method'], request['path'], body=request.get('body'))
        return {'status_code': response.status_code, 'body': response.body, 'headers': {}, 'elapsed_seconds': 0.0}
    conversation = scenario['context']['conversation_id']
    claims = SessionClaims()
    def new_toolkit():
        return Tools(ClientAPI(transport, context=ClientAPIContext(conversation_id=conversation)), claims=claims)
    toolkit = new_toolkit()
    assert set(toolkit.get_tools()) == set(READ_TOOL_FIELDS) | WORKFLOW_TOOL_NAMES
    for name in WORKFLOW_TOOL_NAMES:
        assert toolkit.tool_type(name) == ToolType.WRITE
    agent = CustomerAgent()
    state = agent.get_init_state()
    def checkpoint(current):
        from support_agent.state import clone_state, initial_state
        before_calls = deepcopy(backend.calls)
        copied = clone_state(json.loads(json.dumps(current, allow_nan=False)))
        restored = initial_state(deepcopy(current['history']))
        # Derived evidence must be identical. Per-request counters are checked
        # by clone_state; history restoration does not invent runtime counters.
        for key in ('history', 'identity', 'identity_evidence', 'proposals', 'tasks',
                    'operations', 'handoff', 'pending_calls', 'customer_record',
                    'address_pending', 'payment_pending', 'cancellation_pending',
                    'items_pending', 'returns_pending', 'exchange_pending'):
            assert restored[key] == current[key], ('restored evidence mismatch', key)
        assert copied == current and backend.calls == before_calls
        if observer is not None:
            observer('restore', None, copied, toolkit, backend)
        return copied
    turns = []
    for turn in scenario['turns']:
        if restore:
            state, agent, toolkit = checkpoint(state), CustomerAgent(), new_toolkit()
        before = len(backend.calls)
        source = len(state['history'])
        message, state = agent.generate_next_message(UserMessage(role='user', content=turn['user']), state)
        if observer is not None:
            observer('user', message, state, toolkit, backend)
        tools = []
        while message.tool_calls:
            if restore:
                state, agent, toolkit = checkpoint(state), CustomerAgent(), new_toolkit()
            tool_step_allowed(len(tools), len(message.tool_calls))
            call = message.tool_calls[0]
            if call.name not in set(READ_TOOL_FIELDS) | WORKFLOW_TOOL_NAMES:
                raise AssertionError('Unexpected SDK tool')
            error = False
            try:
                payload = getattr(toolkit, call.name)(**call.arguments)
            except ClientAPIError:
                # Platform-style failed tool outcome, never private diagnostics.
                payload, error = {}, True
            tools.append({'name':call.name, 'arguments_sha256':digest(call.arguments), 'error':error})
            if observer is not None:
                observer('tool', call, payload, toolkit, backend)
            message, state = agent.generate_next_message(MultiToolMessage(role='tool', tool_messages=[
                ToolMessage(role='tool', id=call.id, content=json.dumps(payload), error=error)]), state)
            if observer is not None:
                observer('result', message, state, toolkit, backend)
        assert isinstance(message, AssistantMessage) and message.content is not None
        # The diagnostic must originate after this actual user, never a prior turn.
        assessments = [{'kind': key.removesuffix('_assessment'), 'code': value['code']}
                       for entry in state['history'][source:] for key, value in entry.items()
                       if key.endswith('_assessment')]
        turns.append({'user':turn['user'], 'http_calls':[{'method':m,'path':p,'body':b} for m,p,b in backend.calls[before:]],
                      'tool_calls':tools, 'reply':message.content, 'assessment':assessments[-1] if assessments else None,
                      'identity':state['identity']['verified']})
        if observer is not None:
            observer('reply', message, state, toolkit, backend)
        if restore:
            state = checkpoint(state)
    result = {'id':scenario['id'], 'at_ids':scenario['at_ids'], 'status':'passed', 'context':deepcopy(scenario['context']), 'initial_backend':initial,
              'turns':turns, 'final_backend':backend_snapshot(backend),
              'journal':[{'action':o['spec']['action'],'status':o['status']} for o in state['operations'] if o['mutates']],
              'handoff':state['handoff']['status']}
    verifier(scenario, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-run-id', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    manifest = load_manifest()
    results = []
    for scenario in manifest['scenarios']:
        try:
            results.append(execute(scenario))
        except Exception:
            print('M6_DIALOGUE_FAILED '+scenario['id'], file=sys.stderr)
            raise
    batch = {'schema_version':2, 'scope':SCOPE, 'fixture_sha256':digest(manifest),
             'execution':execution_metadata(args.parent_run_id, args.source_sha256, sdk_version=version('tau2')),
             'network_attempts':len(network_attempts), 'results':results}
    validate_batch(batch, manifest)
    print('M6_DIALOGUE_JSON='+json.dumps(batch, ensure_ascii=False, allow_nan=False, separators=(',',':')))
    print('M6_DIALOGUE_SDK_CHECK_PASSED; native SDK/default turns; fixed call and full-backend oracles; network attempts 0')
