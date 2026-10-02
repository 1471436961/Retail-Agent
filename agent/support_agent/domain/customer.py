"""Minimal lookup rules. Extend with policies from the business materials."""

from __future__ import annotations

import json
import re

CUSTOMER_ID = re.compile(
    r"\b(?:developer_(?:traveler|pending|delivered)_\d+|customer_[A-Za-z0-9_-]+)\b"
)


def find_email(text: str) -> str | None:
    """Read independently supplied verification information, not profile data."""
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group() if match else None


def find_customer_id(text: str) -> str | None:
    """Extract an explicitly supplied demo ID; never invent a customer identity."""
    match = CUSTOMER_ID.search(text)
    return match.group() if match else None


def customer_reply(content: str, error: bool = False) -> str:
    """Format a customer record, with defensive malformed-response handling.

    ``error=True`` is retained for direct callers and the template regression
    tests. The current turn reducer handles lookup failures before calling
    this function, and passes only verified successful content here.
    """
    if error:
        return "I could not find that customer. Please check the customer ID."
    try:
        customer = json.loads(content)
    except (ValueError, TypeError):
        return "The customer service returned an invalid response. Please try again."
    if not isinstance(customer, dict):
        return "The customer service returned an invalid response. Please try again."
    email = customer.get("email")
    if not isinstance(email, str) or not email.strip():
        return "The customer record has no email address available."
    return f"The customer email is {email}."


def verified_lookup_result(content: str, arguments: dict) -> str | None:
    """Match one recorded lookup result to its independently supplied inputs."""
    try:
        record = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(arguments, dict):
        return None
    expected_email = arguments.get("email")
    expected_id = arguments.get("customer_id")
    actual_email = record.get("email")
    actual_id = record.get("customer_id")
    if not isinstance(expected_email, str) or not expected_email or not isinstance(actual_email, str) or actual_email.casefold() != expected_email.casefold():
        return None
    if not isinstance(actual_id, str) or not actual_id:
        return None
    if isinstance(expected_id, str) and expected_id and actual_id != expected_id:
        return None
    return actual_id
