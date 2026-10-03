"""JSON rule decisions. Eligibility is never identity or write authorization."""
from __future__ import annotations

import json


def result(decision: str, code: str, message: str, *rules: str, details=None) -> dict:
    if not isinstance(decision, str) or decision not in {"allow", "deny", "needs_information"}:
        raise ValueError("Unknown rule decision")
    if details is None:
        details = {}
    elif not isinstance(details, dict):
        raise TypeError("Rule details must be a dictionary or None")
    # Own the returned facts and reject non-JSON/nonfinite values.
    return json.loads(json.dumps({"decision": decision, "code": code, "message": message,
                                 "rules": list(rules), "details": details}, allow_nan=False))


def allow(code, message, *rules, details=None):
    return result("allow", code, message, *rules, details=details)


def deny(code, message, *rules, details=None):
    return result("deny", code, message, *rules, details=details)


def need(code, message, *rules, details=None):
    return result("needs_information", code, message, *rules, details=details)


def input_error(code, message, *rules):
    """Reject malformed candidate arguments, distinct from missing business facts.

    Callers must repair their request construction; this is not a customer policy
    refusal or authorization to retry a business write.
    """
    return deny(code, message, *rules, details={"input_error": True})


def identifier(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def options(value) -> bool:
    return isinstance(value, dict) and all(identifier(k) and isinstance(v, str) for k, v in value.items())
