"""Pure t1 turn reducer; later workflows can reuse its state and call gates."""

from support_agent.config import DOMAIN
from support_agent.domain.customer import customer_reply, find_customer_id, find_email
from support_agent.protocol import Decision, ToolAction, TurnInput
from support_agent.state import clone_state, consume_lookup_results, finish_pending, record_lookup_call, result_history


def _respond(state: dict, text: str) -> tuple[Decision, dict]:
    state["history"].append({"role": "assistant", "content": text})
    return Decision(text=text), state


def advance(turn: TurnInput, state: dict) -> tuple[Decision, dict]:
    """Consume one user or tool turn without any platform or API dependency."""
    next_state = clone_state(state)
    next_state["turn"] += 1

    if turn.kind == "tools":
        next_state["history"].append(result_history(turn.outcomes))
        status, content = consume_lookup_results(next_state, turn.outcomes)
        if status == "none":
            return _respond(next_state, "No customer lookup is pending.")
        if status == "unknown":
            return _respond(next_state, "The customer lookup result was missing or ambiguous. Please try again.")
        if status == "failed":
            return _respond(next_state, "I could not verify the customer because the lookup failed. Please check the details or try again.")
        if status == "mismatch":
            return _respond(next_state, "The customer lookup did not match the verification details.")
        return _respond(next_state, customer_reply(content))

    text = turn.content if isinstance(turn.content, str) else ""
    if next_state["pending_call_id"]:
        # Never replay a prior call just because a new user message arrived.
        finish_pending(next_state, "unknown")
    next_state["history"].append({"role": "user", "content": text})
    next_state["tool_calls_since_user"] = 0
    next_state["identity"] = {"verified": False, "customer_id": None}
    customer_id = find_customer_id(text) or next_state["customer_id"]
    email = find_email(text)
    next_state["customer_id"] = customer_id
    if DOMAIN == "retail_plus" and not email:
        return _respond(next_state, "Please provide your email to verify your identity before I access your profile. A customer ID alone is not verification.")
    if not customer_id and DOMAIN != "retail_plus":
        return _respond(next_state, "This example supports customer lookup. Please provide your customer ID.")
    # t1 emits one lookup and always answers after its result. Multi-step
    # workflows must add a real cumulative budget before chaining tool calls.
    call_id = f"lookup-{next_state['turn']}"
    action = ToolAction(id=call_id, name="lookup_customer", arguments={"customer_id": customer_id or "", "email": email or ""})
    decision = Decision(calls=(action,))
    record_lookup_call(next_state, action)
    next_state["history"].append({"role": "assistant", "content": "", "tool_call_ids": [call_id],
                                  "tool_calls": [{"id": call_id, "name": action.name, "arguments": dict(action.arguments)}]})
    return decision, next_state
