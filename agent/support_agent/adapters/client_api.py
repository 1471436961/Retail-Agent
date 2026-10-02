"""Shared response validation for the injected classroom Client API.

This layer classifies one request.  It never retries, especially after a
state-changing request whose outcome may be unknown.
"""

from __future__ import annotations


HTTP_KINDS = {
    400: "invalid_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "state_conflict",
    413: "request_too_large",
    422: "business_rule",
    502: "response_too_large",
}


class ClientAPIError(ValueError):
    def __init__(self, kind: str, *, status_code: int | None = None, code: str | None = None, outcome_unknown: bool = False):
        self.kind = kind
        self.status_code = status_code
        self.code = code
        self.outcome_unknown = outcome_unknown
        super().__init__(f"{kind}: {code or status_code or 'transport error'}")


def _error_code(body) -> str | None:
    if not isinstance(body, dict):
        return None
    detail = body.get("error")
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else None


def request_object(client_api, method: str, path: str, *, body=None, expected_status: int = 200, mutates: bool = False) -> dict:
    """Make exactly one request and require an object response.

    A transport exception, 5xx error, or unusable success response after a
    write is deliberately marked unknown.  The caller must never infer a safe
    retry from this function's exception. Writes require an integer HTTP status;
    only legacy read stubs may omit it when they provide raise_for_status().
    """
    try:
        if body is None:
            response = client_api.request(method, path)
        else:
            response = client_api.request(method, path, body=body)
    except Exception as exc:
        raise ClientAPIError("transport", outcome_unknown=mutates) from exc

    status = getattr(response, "status_code", None)
    checker = getattr(response, "raise_for_status", None)
    has_status = type(status) is int
    if mutates and not has_status:
        raise ClientAPIError("invalid_response", outcome_unknown=True)
    if has_status and status != expected_status:
        raise ClientAPIError(
            HTTP_KINDS.get(status, "unexpected_status"),
            status_code=status,
            code=_error_code(getattr(response, "body", None)),
            outcome_unknown=mutates and (status >= 500 or 200 <= status < 300),
        )
    if callable(checker):
        # Preserve legacy read errors; a successful checker cannot validate a
        # noninteger status or waive the explicit-status requirement for writes.
        try:
            checker()
        except Exception as exc:
            if mutates:
                raise ClientAPIError("invalid_response", status_code=status if has_status else None, outcome_unknown=True) from exc
            raise
    if not has_status and (status is not None or not callable(checker)):
        raise ClientAPIError("invalid_response", outcome_unknown=mutates)
    result = getattr(response, "body", None)
    if not isinstance(result, dict):
        raise ClientAPIError("invalid_response", status_code=status if has_status else None, outcome_unknown=mutates)
    return result
