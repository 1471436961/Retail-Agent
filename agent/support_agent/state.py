"""JSON state with original template fields and lossless SDK message history."""
from typing import Any, TypedDict

from pydantic import TypeAdapter
from tau2.data_model.message import Message, MultiToolMessage

_MESSAGE = TypeAdapter(Message)


class SessionState(TypedDict):
    turn: int
    pending_call_id: str | None
    customer_id: str | None
    messages: list[dict[str, Any]]
    finished: bool


def serialized_messages(history):
    result = []
    for item in history or ():
        message = _MESSAGE.validate_python(item)
        parts = message.tool_messages if isinstance(message, MultiToolMessage) else [message]
        result.extend(part.model_dump(mode="json") for part in parts)
    return result


def initial_state(message_history=None) -> SessionState:
    """Retain the original state fields; each conversation owns its own history."""
    return {"turn": 0, "pending_call_id": None, "customer_id": None,
            "messages": serialized_messages(message_history), "finished": False}


def restored_messages(state):
    """Restore real SDK messages without deriving calls or permissions from text."""
    return [_MESSAGE.validate_python(item) for item in state.get("messages", ())]
