"""Shared internal-workflow wire budgets, separate from REST/model limits."""
import json

MAX_ADDRESS_ARGUMENT_BYTES = 256 * 1024
MAX_ADDRESS_RESULT_BYTES = 1024 * 1024


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def json_bytes(value):
    return len(compact_json(value).encode("utf-8"))


def check_address_argument(session_json):
    if not isinstance(session_json, str) or json_bytes({"session_json": session_json}) > MAX_ADDRESS_ARGUMENT_BYTES:
        raise ValueError("Address tool arguments exceed the internal UTF-8 budget")


class AddressResultTooLarge(ValueError):
    """Result delivery failed; never interpretable as a rejected business write."""
