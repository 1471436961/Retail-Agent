"""One isolated integration check, counted by its main-suite subprocess wrapper."""
import sys
import os
from pathlib import Path

# Standalone invocation has the same offline/no-dotenv boundary as the wrapper.
os.environ.update(PYTHON_DOTENV_DISABLED="1", HF_HUB_OFFLINE="1",
                  LITELLM_TELEMETRY="False",
                  LITELLM_LOCAL_MODEL_COST_MAP="True")

network_attempts = []
guard_probe_events = []
guard_probe_active = True
def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        (guard_probe_events if guard_probe_active else network_attempts).append(event)
        raise RuntimeError("Network is forbidden in offline M3 SDK check")
sys.addaudithook(audit)
# Prove the guard can fail, without contacting a service: literal loopback
# address resolution and a synthetic connect audit event. Keep these controls
# separate from attempts made by the actual SDK/planning/recovery paths.
import socket
for probe in (lambda: socket.getaddrinfo("127.0.0.1", 0),
              lambda: sys.audit("socket.connect", None, ("127.0.0.1", 0))):
    try:
        probe()
    except RuntimeError as exc:
        assert str(exc) == "Network is forbidden in offline M3 SDK check"
    else:
        raise AssertionError("Network audit guard did not reject its positive control")
assert guard_probe_events == ["socket.getaddrinfo", "socket.connect"]
guard_probe_active = False
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import json
from copy import deepcopy
from tau2.data_model.message import AssistantMessage, UserMessage
from support_agent.application import CustomerAgent
from support_agent.protocol import WORKFLOW_TOOL_NAMES
from support_agent.adapters.model_gateway import ModelAdapter
from support_agent.proposals import ACK, confirmation_matches
from test_m3_proposals import specification, verified_state
from sdk_m2_checks import Gateway, context

state, api = verified_state()
reads_before = len(api.calls)
agent = CustomerAgent()
presentation, proposed = agent.present_proposal(state, specification())
assert isinstance(presentation, AssistantMessage) and not presentation.tool_calls
reply, confirmed = agent.generate_next_message(UserMessage(role="user", content="yes, please"), json.loads(json.dumps(proposed)))
assert isinstance(reply, AssistantMessage) and reply.content == ACK and not reply.tool_calls
assert confirmation_matches(confirmed, 1, specification())
assert agent.get_init_state(confirmed["history"])["proposals"] == confirmed["proposals"]
gateway = Gateway(AssistantMessage(role="assistant", content="Please clarify your read request."))
adapter = ModelAdapter(context(gateway), model="offline/read-model")
adapter.decide(confirmed)
sent = gateway.calls[0]["messages"]
assert any(isinstance(m, UserMessage) and m.content == "yes, please" for m in sent)
assert any(isinstance(m, AssistantMessage) and m.content == presentation.content for m in sent)
serialized = json.dumps([m.model_dump() for m in sent])
assert '"presentation_index"' not in serialized and '"fingerprint"' not in serialized
assert '"proposal_ack"' not in serialized

# The platform boundary turns damaged JSON evidence into a terminal guard,
# retaining the original record and never attempting the model or API again.
damaged = deepcopy(confirmed)
damaged["proposals"][0]["status"] = "invented"
snapshot = deepcopy(damaged)
guarded_agent = CustomerAgent(model_adapter=adapter)
reply, blocked = guarded_agent.generate_next_message(UserMessage(role="user", content="Read order #TEST1"), damaged)
assert isinstance(reply, AssistantMessage) and reply.content and not reply.tool_calls
assert blocked["session_block"] == {"code": "invalid_state", "evidence_retained": True}
assert blocked["quarantined_state"] == snapshot and damaged == snapshot
for operation in (
        lambda: guarded_agent.generate_next_message(UserMessage(role="user", content="yes"), blocked),
        lambda: guarded_agent.present_proposal(blocked, specification())):
    reply, still_blocked = operation()
    assert not reply.tool_calls and still_blocked == blocked
assert len(gateway.calls) == 1
reply, blocked_presentation = guarded_agent.present_proposal(damaged, specification())
assert not reply.tool_calls and blocked_presentation["quarantined_state"] == snapshot
reply, non_json_guard = guarded_agent.generate_next_message(UserMessage(role="user", content="yes"), {"schema_version":2, "bad":object()})
assert not reply.tool_calls and non_json_guard["session_block"]["evidence_retained"] is False
json.dumps(non_json_guard, allow_nan=False)

bad_history = deepcopy(proposed["history"])
bad_history[-1]["proposal"]["version"] = 99
blocked_history = agent.get_init_state(bad_history)
assert blocked_history["session_block"]["code"] == "invalid_history"
assert blocked_history["quarantined_state"]["unrestored_history"] == bad_history
invalid_spec = specification()
del invalid_spec["parameters"]["postal_code"]
reply, unchanged = agent.present_proposal(state, invalid_spec)
assert not reply.tool_calls and not unchanged["proposals"]
assert unchanged["identity_evidence"] == state["identity_evidence"]
assert unchanged["history"][:-1] == state["history"]
assert len(api.calls) == reads_before and not network_attempts

# M3.3 uses the same platform boundary and main-suite wrapper. This block is
# additional integration coverage, not extra main-suite test cases.
specs = [specification(), specification("payment_method")]
presentation, proposed = agent.present_proposals(state, specs)
assert isinstance(presentation, AssistantMessage) and not presentation.tool_calls
reply, scoped = agent.generate_next_message(UserMessage(role="user", content="confirm only operation 1"), proposed)
assert not reply.tool_calls and confirmation_matches(scoped, 1, specs[0])
assert not confirmation_matches(scoped, 2, specs[1])
reply, scoped = agent.generate_next_message(UserMessage(role="user", content="yes"), scoped)
assert not confirmation_matches(scoped, 2, specs[1])
assert agent.get_init_state(scoped["history"])["proposals"] == scoped["proposals"]
adapter.decide(scoped)
serialized = json.dumps([m.model_dump() for m in gateway.calls[-1]["messages"]])
assert "confirm only operation 1" in serialized and "Operation 2:" in serialized
assert all('"' + field + '"' not in serialized for field in ("proposal_set", "proposal_set_ack", "set_index", "reuse_version"))
reply, withdrawn = agent.generate_next_message(UserMessage(role="user", content="withdraw operation 1"), scoped)
assert not reply.tool_calls and not confirmation_matches(withdrawn, 1, specs[0])
presentation, proposed = agent.present_proposals(withdrawn, specs)
reply, conditional = agent.generate_next_message(UserMessage(role="user", content="yes if cheaper"), proposed)
assert not reply.tool_calls and all(p["status"] == "needs_review" for p in conditional["proposals"][-2:])
damaged = deepcopy(scoped); damaged["proposals"][1]["status"] = "confirmed"
reply, blocked = guarded_agent.present_proposals(damaged, specs)
assert not reply.tool_calls and blocked["quarantined_state"] == damaged
reply, still_blocked = guarded_agent.present_proposals(blocked, specs)
assert not reply.tool_calls and still_blocked == blocked
assert len(api.calls) == reads_before and not network_attempts

# M3.4 task planning uses the same SDK wrapper; it never adds a write tool.
from support_agent.tasks import inspect_task_plan
from support_agent.state import clone_state
from test_m3_tasks import request
plan_message, planned = agent.plan_tasks(state, [request("modify_items"), request()])
assert isinstance(plan_message, AssistantMessage) and not plan_message.tool_calls
assert not planned["proposals"] and len(planned["tasks"]) == 2
assert agent.get_init_state(planned["history"])["tasks"] == planned["tasks"]
presentation, proposed = agent.present_proposals(planned, [specification("modify_items"), specification()])
reply, confirmed_tasks = agent.generate_next_message(UserMessage(role="user", content="yes"), proposed)
task_view = inspect_task_plan(confirmed_tasks)
assert [n["assessment"]["code"] for n in task_view["details"]["tasks"]] == ["dependency_result_required", "preflight_candidate"]
assert not task_view["details"]["write_authorized"]
recovered_tasks = agent.get_init_state(confirmed_tasks["history"])
cloned_tasks = clone_state(json.loads(json.dumps(confirmed_tasks)))
assert recovered_tasks["tasks"] == cloned_tasks["tasks"] == confirmed_tasks["tasks"]
assert inspect_task_plan(recovered_tasks) == inspect_task_plan(cloned_tasks) == task_view
adapter.decide(confirmed_tasks)
serialized = json.dumps([m.model_dump() for m in gateway.calls[-1]["messages"]])
assert plan_message.content in [m.content for m in gateway.calls[-1]["messages"] if isinstance(m, AssistantMessage)]
assert '"task_plan"' not in serialized and '"depends_on"' not in serialized
damaged = deepcopy(confirmed_tasks); damaged["tasks"][0]["depends_on"] = []
reply, blocked = guarded_agent.plan_tasks(damaged, [request()])
assert not reply.tool_calls and blocked["quarantined_state"] == damaged
reply, still_blocked = guarded_agent.plan_tasks(blocked, [request()])
assert not reply.tool_calls and still_blocked == blocked
invalid, valid_state = agent.plan_tasks(state, [request("cancel", "#TEST2")])
assert not invalid.tool_calls and not valid_state["tasks"]
assert valid_state["identity_evidence"] == state["identity_evidence"]
assert len(api.calls) == reads_before and not network_attempts
# M3.5 has a disabled default port and a fake-only injected lifecycle. The
# actual SDK Agent wrapper must preserve the journal, quarantine tampering,
# and project bounded outcomes without treating journal metadata as tools.
from test_m3_writes import confirmed as write_confirmed, FakeRuntime, writes
write_state, write_api, write_spec = write_confirmed()
result, unchanged = agent.execute_operation(write_state, 1, write_spec)
assert result["code"] == "write_runtime_required" and unchanged == write_state
runtime = FakeRuntime(write_api)
result, written = agent.execute_operation(write_state, 1, write_spec, runtime)
assert result["code"] == "write_verified" and len(runtime.sends) == 1
assert agent.get_init_state(written["history"])["operations"] == written["operations"]
adapter.decide(written)
serialized = json.dumps([m.model_dump() for m in gateway.calls[-1]["messages"]])
assert "Recorded operation outcome: succeeded" in serialized
assert '"write_event"' not in serialized and '"verified_read_ids"' not in serialized
damaged = deepcopy(written); writes(damaged)[0]["status"] = "unknown"
result, blocked = agent.execute_operation(damaged, 1, write_spec, runtime)
assert result["code"] == "invalid_state" and blocked["quarantined_state"] == damaged
result, still_blocked = agent.reconcile_operation(blocked, writes(written)[0]["call_id"], runtime)
assert result["code"] == "invalid_state" and still_blocked == blocked
assert len(runtime.sends) == 1 and not network_attempts

# Concrete sequential session adapter, formal SDK presentation -> real user
# message -> complete returned text/state. Transport remains a local fake.
from test_m3_completion import transport, return_spec
from support_agent.adapters.write_runtime import SessionWriteRuntime, SessionClaims
return_state, return_api = verified_state(status="delivered")
recap, return_state = agent.present_proposal(return_state, return_spec())
assert isinstance(recap, AssistantMessage) and recap.content == return_state["history"][-1]["content"]
reply, return_state = agent.generate_next_message(UserMessage(role="user", content="yes"), return_state)
return_sends = transport(return_api)
reply, returned = agent.submit_operation(return_state, 1, return_spec(), SessionWriteRuntime(return_api, claims=SessionClaims()))
assert isinstance(reply, AssistantMessage) and not reply.tool_calls
assert "accepted and verified" in reply.content and "does not confirm refund settlement" in reply.content
assert reply.content == returned["history"][-1]["content"]
assert writes(returned)[0]["status"] == "succeeded" and len(return_sends) == 1
assert agent.get_init_state(returned["history"])["operations"] == returned["operations"]

# Context budget is our engineering limit. A derived model-only summary cannot
# replace actual user evidence or prune the original state ledger.
from support_agent.model_context import project_messages
from support_agent.protocol import InvalidAction
from support_agent.state import initial_state
long_history = deepcopy(state["history"])
for index in range(20):
    long_history.extend([{"role":"user", "content":f"Historical note {index}: " + "example " * 300},
                         {"role":"assistant", "content":"This is an earlier conversation note."}])
long_history.append({"role":"user", "content":"Please explain the available support."})
long_state = initial_state(long_history)
before = deepcopy(long_state)
projected = project_messages(long_state, max_characters=6000)
assert sum(len(json.dumps(m.model_dump(), ensure_ascii=False, allow_nan=False)) for m in projected) <= 6000
assert "derived_session_context" in projected[1].content and projected[-1].content == long_history[-1]["content"]
assert len(projected) < len(long_history) and long_state == before
assert long_state["identity_evidence"] == state["identity_evidence"]
assert not initial_state([m.model_dump() for m in projected])["identity"]["verified"]
too_long = initial_state(long_history + [{"role":"user", "content":"x" * 7000}])
try:
    project_messages(too_long, max_characters=6000)
    raise AssertionError("Oversized current request must not produce a truncated model request")
except InvalidAction:
    pass
pending_state = deepcopy(state)
decision, pending_state = agent.generate_next_message(UserMessage(role="user", content="Read order #TEST1"), pending_state)
try:
    project_messages(pending_state)
    raise AssertionError("Pending results must prevent projection")
except InvalidAction:
    pass
assert not network_attempts
# M4.1's real SDK message/tool surface. Native ClientAPI serializes a local
# fake transport; both address writes require actual user consent and readback.
from tau2.hyper.client_api import ClientAPI, ClientAPIContext
from tau2.data_model.message import MultiToolMessage, ToolMessage
from test_m4_addresses import AddressBackend, NEW
from tools import Tools
backend = AddressBackend()
def address_transport(payload):
    response = backend.request(payload["method"], payload["path"], body=payload.get("body"))
    return {"status_code": response.status_code, "body": response.body, "headers": {}, "elapsed_seconds": 0.0}
address_api = ClientAPI(address_transport, context=ClientAPIContext(conversation_id="offline-address-sdk"))
address_tools = Tools(address_api)
address_agent = CustomerAgent()
address_state = address_agent.get_init_state([])
def address_turn(text):
    global address_state
    outgoing, address_state = address_agent.generate_next_message(UserMessage(role="user", content=text), address_state)
    if outgoing.tool_calls:
        if outgoing.tool_calls[0].name == "address_workflow":
            try:
                project_messages(address_state)
                raise AssertionError("An outstanding address tool cannot enter model projection")
            except InvalidAction:
                pass
        results = [ToolMessage(role="tool", id=c.id, content=json.dumps(getattr(address_tools, c.name)(**c.arguments)), error=False)
                   for c in outgoing.tool_calls]
        outgoing, address_state = address_agent.generate_next_message(MultiToolMessage(role="tool", tool_messages=results), address_state)
    return outgoing
address_turn("a@example.test")
recap = address_turn("Change default and order #TEST1 address: " + json.dumps(NEW))
assert isinstance(recap, AssistantMessage) and not recap.tool_calls
assert "Order: #TEST1" in recap.content and "Update the customer's default shipping address" in recap.content
assert not any(c[0] == "PUT" for c in backend.calls)
result = address_turn("yes")
assert result.content == address_state["history"][-1]["content"]
assert result.content.count("accepted and independently verified") == 2
assert [c[1] for c in backend.calls if c[0] == "PUT"] == ["/v1/orders/%23TEST1/shipping-address", "/v1/customers/customer_a/default-shipping-address"]
assert backend.orders["#TEST1"]["shipping_address"] == backend.customers["customer_a"]["default_shipping_address"] == NEW
assert address_agent.get_init_state(address_state["history"])["operations"] == address_state["operations"]
# A failed read-only preparation must not quarantine model projection. Only
# actual host messages control this recovery; a later result cannot restore it.
outgoing, address_state = address_agent.generate_next_message(UserMessage(role="user", content="Change order #TEST1 address; suite: Suite 9"), address_state)
prepare_call = outgoing.tool_calls[0]
outgoing, address_state = address_agent.generate_next_message(MultiToolMessage(role="tool", tool_messages=[ToolMessage(role="tool", id=prepare_call.id, content="", error=True)]), address_state)
assert address_state["address_pending"] is None
assert address_state["history"][-1]["address_assessment"]["code"] == "address_prepare_abandoned"
assert project_messages(address_state)
from support_agent.adapters.model_gateway import READ_POLICY
assert "deterministic host" in READ_POLICY and "read-only model" in READ_POLICY
assert not network_attempts
print("M4_ADDRESS_SDK_CHECK_PASSED; native ClientAPI local fake; 2 independently verified address writes; network attempts 0")
from test_m4_payments import PaymentBackend
from support_agent.protocol import READ_TOOL_FIELDS
payment_backend = PaymentBackend()
def payment_transport(payload):
    response = payment_backend.request(payload["method"],payload["path"],body=payload.get("body"))
    return {"status_code":response.status_code,"body":response.body,"headers":{},"elapsed_seconds":0.0}
payment_api = ClientAPI(payment_transport,context=ClientAPIContext(conversation_id="offline-payment-sdk"))
payment_tools, payment_agent = Tools(payment_api), CustomerAgent()
payment_state = payment_agent.get_init_state([])
def payment_turn(text):
    global payment_state
    outgoing,payment_state = payment_agent.generate_next_message(UserMessage(role="user",content=text),payment_state)
    for _ in range(3):
        if not outgoing.tool_calls: return outgoing
        if outgoing.tool_calls[0].name == "payment_workflow":
            try:
                project_messages(payment_state)
                raise AssertionError("Outstanding payment workflow cannot enter model projection")
            except InvalidAction: pass
        messages = [ToolMessage(role="tool",id=c.id,content=json.dumps(getattr(payment_tools,c.name)(**c.arguments)),error=False) for c in outgoing.tool_calls]
        outgoing,payment_state = payment_agent.generate_next_message(MultiToolMessage(role="tool",tool_messages=messages),payment_state)
    raise AssertionError("Unexpected repeated internal workflow dispatch")
payment_turn("a@example.test")
recap = payment_turn("Switch order #TEST1 payment to PayPal")
assert not recap.tool_calls and "Full order charge: 12.5" in recap.content
assert not any(c[0]=="PUT" for c in payment_backend.calls)
result = payment_turn("yes")
assert "accepted and independently verified" in result.content and "Order remains pending" in result.content
assert [c for c in payment_backend.calls if c[0]=="PUT"] == [("PUT","/v1/orders/%23TEST1/payment-method",{"payment_method_id":"paypal_a"})]
assert payment_agent.get_init_state(payment_state["history"])["operations"] == payment_state["operations"]
assert set(payment_tools.get_tools()) == set(READ_TOOL_FIELDS) | WORKFLOW_TOOL_NAMES
assert not network_attempts
print("M4_PAYMENT_SDK_CHECK_PASSED; native ClientAPI local fake; confirmed full charge/refund/readback; network attempts 0")
from test_m4_cancellations import CancellationBackend
cancel_backend = CancellationBackend()
def cancel_transport(payload):
    response = cancel_backend.request(payload["method"],payload["path"],body=payload.get("body"))
    return {"status_code":response.status_code,"body":response.body,"headers":{},"elapsed_seconds":0.0}
cancel_api = ClientAPI(cancel_transport, context=ClientAPIContext(conversation_id="offline-cancellation-sdk"))
cancel_tools, cancel_agent = Tools(cancel_api), CustomerAgent()
cancel_state = cancel_agent.get_init_state([])
def cancel_turn(text):
    global cancel_state
    outgoing, cancel_state = cancel_agent.generate_next_message(UserMessage(role="user",content=text),cancel_state)
    for _ in range(3):
        if not outgoing.tool_calls: return outgoing
        if outgoing.tool_calls[0].name == "cancellation_workflow":
            try:
                project_messages(cancel_state)
                raise AssertionError("Outstanding cancellation cannot enter model projection")
            except InvalidAction: pass
        messages = [ToolMessage(role="tool",id=c.id,content=json.dumps(getattr(cancel_tools,c.name)(**c.arguments)),error=False) for c in outgoing.tool_calls]
        outgoing,cancel_state = cancel_agent.generate_next_message(MultiToolMessage(role="tool",tool_messages=messages),cancel_state)
    raise AssertionError("Unexpected cancellation dispatch loop")
cancel_turn("a@example.test")
recap = cancel_turn("Cancel order #TEST1 because I don't want it anymore")
assert not recap.tool_calls and "Original charge total" in recap.content and "12.50" in recap.content
assert not any(c[1].endswith("/cancellations") for c in cancel_backend.calls)
result = cancel_turn("yes")
assert "accepted and independently verified" in result.content and "do not prove settlement or arrival" in result.content
assert [c for c in cancel_backend.calls if c[1].endswith("/cancellations")] == [("POST","/v1/orders/%23TEST1/cancellations",{"reason":"no longer needed"})]
assert cancel_agent.get_init_state(cancel_state["history"])["operations"] == cancel_state["operations"]
assert set(cancel_tools.get_tools()) == set(READ_TOOL_FIELDS) | WORKFLOW_TOOL_NAMES
assert not network_attempts
print("M4_CANCELLATION_SDK_CHECK_PASSED; native ClientAPI local fake; confirmed cancellation/per-charge refund/readback; network attempts 0")
print("M3_NETWORK_GUARD_CHECK_PASSED; 2 controlled audit probes; actual-path network attempts 0")
print("M3_SDK_CHECK_PASSED; network attempts 0; gateway fake")
