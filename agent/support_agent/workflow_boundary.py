"""Shared replayable internal-workflow transport; never consent authority.

Address, payment, cancellation and items use the same identity/proposal/write journal. The
kind is a closed trusted-code selector, never a tool parameter or model choice.
"""
import json
from copy import deepcopy
from support_agent.protocol import Decision, InvalidAction, ToolAction
from support_agent.domain.rules import result as rule_result
from support_agent.workflow_limits import check_workflow_argument, compact_json


class WorkflowBoundary:
    def __init__(self, kind, result_limit):
        if kind not in {"address", "payment", "cancellation", "items"}:
            raise ValueError("Unsupported internal workflow")
        self.kind, self.result_limit = kind, result_limit
        self.tool = kind + "_workflow"
        self.actions = frozenset({"address": {"shipping_address", "default_shipping_address"}, "payment": {"payment_method"}, "cancellation": {"cancel"}, "items": {"modify_items"}}[kind])
        self.rule = {"address": "AD-01", "payment": "PY-01", "cancellation": "CA-01", "items": "IT-01"}[kind]
        self.control_keys = frozenset(kind + "_" + suffix for suffix in ("dispatch", "result", "unknown", "abandoned"))

    def validate_assessment(self, entry):
        assessment = entry[f"{self.kind}_assessment"]
        if (entry["role"] != "assistant" or not isinstance(assessment, dict)
                or set(assessment) != {"decision", "code", "message", "rules", "details"}
                or assessment["decision"] not in {"allow", "deny", "needs_information"}
                or not isinstance(assessment["code"], str) or not assessment["code"]
                or assessment["message"] != entry["content"]
                or not isinstance(assessment["rules"], list) or any(not isinstance(r, str) for r in assessment["rules"])
                or not isinstance(assessment["details"], dict) or assessment["details"].get("write_authorized") is not False
                or not isinstance(assessment["details"].get("records"), list)):
            raise ValueError("Malformed workflow diagnostic; it is never write authority")
        for record in assessment["details"]["records"]:
            if (not isinstance(record, dict) or set(record) - {"action", "target", "decision", "code", "version", "status"}
                    or not {"action", "target", "decision", "code"} <= set(record)
                    or record["action"] not in self.actions or not isinstance(record["target"], dict)
                    or record["decision"] not in {"allow", "deny", "needs_information"}
                    or not isinstance(record["code"], str) or not record["code"]):
                raise ValueError("Malformed per-record workflow diagnostic")


    def tag(self, decision, state, code, *, decision_kind="needs_information", records=(), **details):
        state["history"][-1][f"{self.kind}_assessment"] = rule_result(
            decision_kind, code, decision.text, self.rule, "CF-01",
            details={**details, "records": list(records), "write_authorized": False})
        return decision, state


    def reply(self, state, code, text, **details):
        from support_agent.read_session import reply
        decision, state = reply(state, text)
        return self.tag(decision, state, code, **details)


    def control(self, state, event, index):
        key = next(iter(self.control_keys & set(event)))
        data = event[key]
        if (set(event) != {"role", "content", key} or event["role"] != "assistant"
                or event["content"] != f"{self.kind.title()} workflow: " + json.dumps(data, sort_keys=True)
                or not isinstance(data, dict)):
            raise ValueError("Malformed workflow evidence")
        pending = state.get(f"{self.kind}_pending")
        if key == f"{self.kind}_dispatch":
            if (any(state.get(k + "_pending") is not None for k in ("address", "payment", "cancellation", "items")) or set(data) != {"call_id", "mode"} or data["mode"] not in {"prepare", "execute"}
                    or data["call_id"] != f"{self.kind}:{index}" or index == 0):
                raise ValueError("Repeated or invalid workflow dispatch")
            state[f"{self.kind}_pending"] = {**data, "index": index, "status": "pending"}
        else:
            if pending is None or set(data) != {"call_id"} or data["call_id"] != pending["call_id"]:
                raise ValueError("Workflow outcome lacks its original dispatch")
            if key == f"{self.kind}_abandoned":
                if pending["mode"] != "prepare":
                    raise ValueError("Only a read-only preparation can be abandoned")
                state[f"{self.kind}_pending"] = None
            elif key == f"{self.kind}_unknown":
                state[f"{self.kind}_pending"] = {**pending, "status": "unknown"}
            elif pending["status"] != "pending":
                raise ValueError("Uncertain dispatch cannot be cleared by a marker")
            else:
                state[f"{self.kind}_pending"] = None


    def restore(self, state, index):
        self.control(state, state["history"][index], index)


    def validate(self, state):
        replay = {f"{self.kind}_pending": None}
        for index, entry in enumerate(state["history"]):
            if f"{self.kind}_assessment" in entry:
                self.validate_assessment(entry)
            if self.control_keys & set(entry):
                self.control(replay, entry, index)
        if replay[f"{self.kind}_pending"] != state.get(f"{self.kind}_pending"):
            raise ValueError("Workflow pending slot differs from history")


    def event(self, state, key, data):
        state["history"].append({"role": "assistant", "content": f"{self.kind.title()} workflow: " + json.dumps(data, sort_keys=True), key: data})
        self.restore(state, len(state["history"]) - 1)


    def dispatch(self, state, mode):
        from support_agent.state import clone_state
        state = clone_state(state)
        original = deepcopy(state)
        if any(state.get(k + "_pending") is not None for k in ("address", "payment", "cancellation", "items")) or state["pending_calls"] or state["handoff"]["status"] not in {"not_requested", "rejected"}:
            raise InvalidAction("An idle internal workflow is required")
        if not state["identity"]["verified"] or not state["identity_evidence"]:
            raise InvalidAction("Internal workflow requires original identity evidence")
        call_id = f"{self.kind}:{len(state['history'])}"
        self.event(state, f"{self.kind}_dispatch", {"call_id": call_id, "mode": mode})
        session_json = compact_json(state)
        try:
            check_workflow_argument(session_json)
        except ValueError:
            return self.reply(original, f"{self.kind}_argument_budget_exceeded", f"The complete {self.kind} evidence exceeds this tool's transport budget. No new {self.kind} operation was sent; I will not trim identity, consent or unresolved-write evidence.")
        call = ToolAction(call_id, self.tool, {"session_json": session_json})
        return Decision(calls=(call,)), state


    def accept(self, state, outcomes):
        """Accept a complete matching bundle atomically; no raw rejected body."""
        from support_agent.state import clone_state
        pending = state[f"{self.kind}_pending"]
        abandoned = {e[f"{self.kind}_abandoned"]["call_id"] for e in state["history"] if f"{self.kind}_abandoned" in e}
        if outcomes and all(o.id in abandoned for o in outcomes):
            # Keep a newer dispatch's exact prefix unchanged; an ephemeral stale
            # delivery diagnostic is not new consent or business evidence.
            return Decision(text="An abandoned read-only preparation result was ignored. It cannot replace the current request or proposal."), state
        try:
            if pending is None or pending["status"] != "pending" or len(outcomes) != 1:
                raise ValueError("Wrong workflow batch")
            outcome = outcomes[0]
            if outcome.id != pending["call_id"] or outcome.error:
                raise ValueError("Workflow result missing or failed")
            if len(outcome.content.encode("utf-8")) > self.result_limit:
                raise ValueError("Workflow result transport budget exceeded")
            payload = json.loads(outcome.content)
            if not isinstance(payload, dict) or set(payload) != {"reply", "state", "assessment"}:
                raise ValueError("Invalid workflow bundle")
            candidate = clone_state(payload["state"])
            prefix = state["history"]
            suffix = candidate["history"][len(prefix):]
            if (len(prefix) != pending["index"] + 1 or candidate["history"][:len(prefix)] != prefix
                    or not suffix
                    or any(e["role"] == "user" for e in suffix)
                    or candidate["identity"] != state["identity"] or candidate["identity_evidence"] != state["identity_evidence"]
                    or not isinstance(payload["reply"], str) or not payload["reply"]
                    or candidate["history"][-1]["content"] != payload["reply"]
                    or candidate["history"][-1].get(f"{self.kind}_assessment") != payload["assessment"]):
                raise ValueError("Workflow bundle does not extend its original trusted prefix")
            all_controls = {kind + "_" + suffix for kind in ("address", "payment", "cancellation", "items") for suffix in ("dispatch", "result", "unknown", "abandoned")}
            terminal = [(i, e) for i, e in enumerate(suffix) if all_controls & set(e)]
            if len(terminal) != 1:
                raise ValueError("Workflow bundle requires exactly one terminal control event")
            position, event = terminal[0]
            if event.get(f"{self.kind}_result") == {"call_id": pending["call_id"]}:
                if candidate[f"{self.kind}_pending"] is not None or (pending["mode"] == "prepare" and position != 0):
                    raise ValueError("Workflow result has invalid lifecycle order")
            elif (pending["mode"] == "execute" and event.get(f"{self.kind}_unknown") == {"call_id": pending["call_id"]}
                  and candidate[f"{self.kind}_pending"] == {**pending, "status": "unknown"}
                  and payload["assessment"]["code"] == f"{self.kind}_execution_uncertain"):
                pass  # Preserve completed earlier records plus the uncertain batch.
            else:
                raise ValueError("Uncertain execution cannot be cleared or reclassified")
            new_writes = [o for o in candidate["operations"] if o["mutates"]
                          and o["call_id"] not in {p["call_id"] for p in state["operations"] if p["mutates"]}]
            if pending["mode"] == "prepare" and new_writes:
                raise ValueError("Preparation cannot create a business write")
            from support_agent.proposals import _current_records
            selected = {p["version"]: p["spec"] for p in _current_records(state)
                        if p["status"] == "confirmed" and p["spec"]["action"] in self.actions}
            if any(o["version"] not in selected or o["spec"] != selected[o["version"]] for o in new_writes):
                raise ValueError("Workflow execution cannot submit unselected operations")
            candidate["turn"] = max(state["turn"], candidate["turn"])
            return Decision(text=payload["reply"]), candidate
        except (TypeError, ValueError, KeyError):
            # A tool error may have occurred after sending. Keep a persistent
            # unresolved reservation even when no business journal was returned.
            if pending is not None and pending["mode"] == "prepare":
                self.event(state, f"{self.kind}_abandoned", {"call_id": pending["call_id"]})
                return self.reply(state, f"{self.kind}_prepare_abandoned", f"The read-only {self.kind} preparation result was not accepted. No write can be sent by preparation; you can retry preparation or continue with another request.")
            if pending is not None and pending["status"] == "pending":
                self.event(state, f"{self.kind}_unknown", {"call_id": pending["call_id"]})
            return self.reply(state, f"{self.kind}_workflow_unresolved", f"The {self.kind} workflow result is unresolved. I cannot report success or safely repeat it; the original operation needs review.")



def validate_workflows(state):
    replay = {kind + "_pending": None for kind in ("address", "payment", "cancellation", "items")}
    boundaries = [WorkflowBoundary(kind, 1024 * 1024) for kind in ("address", "payment", "cancellation", "items")]
    for index, entry in enumerate(state["history"]):
        for boundary in boundaries:
            if boundary.kind + "_assessment" in entry:
                boundary.validate_assessment(entry)
            if boundary.control_keys & set(entry):
                boundary.control(replay, entry, index)
    if any(replay[key] != state.get(key) for key in replay):
        raise ValueError("Workflow pending slots differ from original history")


def unfinished_other_tasks(state, actions):
    """Only verified journal completion permits replacing a foreign plan."""
    if not any(n["action"] not in actions for n in state["tasks"]):
        return False
    from support_agent.tasks import inspect_task_plan
    assessment = inspect_task_plan(state)
    return any(n["action"] not in actions and n["assessment"]["code"] != "task_completed"
               for n in assessment["details"].get("tasks", [])) or "tasks" not in assessment["details"]
