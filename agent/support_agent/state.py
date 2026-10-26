"""JSON state with original template fields and lossless SDK message history."""
from typing import Any, TypedDict

from pydantic import TypeAdapter
from tau2.data_model.message import AssistantMessage, Message, MultiToolMessage

_MESSAGE = TypeAdapter(Message)
_FINISH_CONTROL = {"version": 1, "action": "finish_response"}


def is_finished_message(message):
    """Recognize application control metadata, never customer or tool prose."""
    return (isinstance(message, AssistantMessage) and not message.tool_calls
            and isinstance(message.content, str) and bool(message.content.strip())
            and isinstance(message.raw_data, dict)
            and message.raw_data.get("retail_agent_control") == _FINISH_CONTROL)


def finished_message(response, content):
    """Keep the completion decision through SDK serialization and restoration."""
    return response.model_copy(update={
        "content": content, "tool_calls": None,
        "raw_data": {**(response.raw_data or {}), "retail_agent_control": dict(_FINISH_CONTROL)},
    })


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
    history = serialized_messages(message_history)
    finished = bool(history and is_finished_message(_MESSAGE.validate_python(history[-1])))
    return {"turn": 0, "pending_call_id": None, "customer_id": None,
            "messages": history, "finished": finished}


def restored_messages(state):
    """Restore real SDK messages without deriving calls or permissions from text."""
    return [_MESSAGE.validate_python(item) for item in state.get("messages", ())]
