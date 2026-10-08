"""Import only copied upload files; real SDK, synthetic failing transport."""
import argparse
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
from types import SimpleNamespace

parser=argparse.ArgumentParser()
parser.add_argument('--package',required=True)
args=parser.parse_args()
directory=Path(args.package).resolve(strict=True)
network=[]
guard_controls=[]
testing_guard=True
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo'}:
        (guard_controls if testing_guard else network).append(event)
        raise RuntimeError('Offline package probe forbids network')
sys.addaudithook(audit)
for event in ('socket.connect','socket.getaddrinfo'):
    try: sys.audit(event,None)
    except RuntimeError: pass
    else: raise AssertionError('Network guard positive control must fail')
assert guard_controls==['socket.connect','socket.getaddrinfo']
testing_guard=False
sys.path.insert(0,str(directory))
# -I removes PYTHONPATH and the worker directory; installed SDK remains a dependency.
assert not any(Path(p).name in {'tests','scripts'} for p in sys.path if p)
for path in sorted(directory.rglob('*.py')):
    parts=list(path.relative_to(directory).with_suffix('').parts)
    if parts[-1]=='__init__': parts.pop()
    if not parts: continue
    module=importlib.import_module('.'.join(parts))
    assert Path(module.__file__).resolve().is_relative_to(directory)

import agent
from tools import Tools
from support_agent.protocol import READ_TOOL_FIELDS, WORKFLOW_TOOL_NAMES
from support_agent.adapters.client_api import ClientAPIError
from tau2.hyper.client_api import ClientAPI, ClientAPIContext
from tau2.environment.toolkit import ToolType
from tau2.data_model.message import UserMessage, MultiToolMessage, ToolMessage

context=SimpleNamespace(conversation_id='isolated-context')
agent.get_agent_context=lambda:context
first,second=agent.create_agent(),agent.create_agent()
assert first is not second and first.context is context and second.context is context
assert first.model_adapter is not second.model_adapter
assert first.model_adapter.semantic_understanding is True
assert second.model_adapter.semantic_understanding is True
# Package isolation provides no model capability. The production factory must
# refuse interpretation rather than silently become the old regex agent.
unavailable,unused=first.generate_next_message(UserMessage(role='user',content='a@example.test'),first.get_init_state())
assert not unavailable.tool_calls and not unused['identity']['verified']
# Separately exercise transport sanitization through the low-level rule port.
# Actual factory/gateway/SDK round trips are covered by the M7 native worker.
from support_agent.application import CustomerAgent
transport_agent=CustomerAgent()
marker='M65_PRIVATE_ERROR_CANARY_0123456789'
calls=[]
def transport(request):
    calls.append(request)
    raise RuntimeError(marker)
toolkit=Tools(ClientAPI(transport,context=ClientAPIContext(conversation_id='isolated-context')))
assert set(toolkit.get_tools())==set(READ_TOOL_FIELDS)|WORKFLOW_TOOL_NAMES
assert all(toolkit.tool_type(n)==ToolType.READ for n in READ_TOOL_FIELDS)
assert all(toolkit.tool_type(n)==ToolType.WRITE for n in WORKFLOW_TOOL_NAMES)
message,state=transport_agent.generate_next_message(UserMessage(role='user',content='a@example.test'),transport_agent.get_init_state())
assert len(message.tool_calls)==1
call=message.tool_calls[0]
assert call.name=='lookup_customer'
try:
    toolkit.use_tool(call.name,**call.arguments)
except ClientAPIError as error:
    assert marker not in str(error)
else: raise AssertionError('Transport failure must not become success')
reply,state=transport_agent.generate_next_message(MultiToolMessage(role='tool',tool_messages=[
    ToolMessage(role='tool',id=call.id,content=marker,error=True)]),state)
assert not reply.tool_calls and marker not in (reply.content or '')
assert marker not in json.dumps(state)
assert len(calls)==1 and not network
print('M6_PACKAGE_JSON '+json.dumps({'sdk_version':version('tau2'),
    'module_origins_inside_package':True,'read_tools':len(READ_TOOL_FIELDS),
    'write_tools':len(WORKFLOW_TOOL_NAMES),'factory_fresh':True,
    'private_error_marker_absent':True,'network_attempts':len(network),
    'transport_calls':len(calls),'model_calls':0}))
print('M6_PACKAGE_PASSED; network attempts 0')
