"""One isolated integration check, counted by its main-suite subprocess wrapper."""
import sys
from pathlib import Path

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
print("M3_NETWORK_GUARD_CHECK_PASSED; 2 controlled audit probes; actual-path network attempts 0")
print("M3_SDK_CHECK_PASSED; network attempts 0; gateway fake")
