"""Independent verification inputs and session-bound customer matching."""
from __future__ import annotations

import re

from support_agent.domain.customer import find_email

PROOF_FIELDS = ("email", "first_name", "last_name", "postal_code")


def normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def verification_inputs(email="", first_name="", last_name="", postal_code="") -> dict[str, str]:
    values = dict(zip(PROOF_FIELDS, (email, first_name, last_name, postal_code)))
    if any(not isinstance(v, str) for v in values.values()):
        raise ValueError("Verification fields must be strings")
    values = {k: v.strip() for k, v in values.items()}
    if values["email"]:
        if find_email(values["email"]) != values["email"] or any(values[k] for k in PROOF_FIELDS[1:]):
            raise ValueError("Provide email alone, or a complete name and postal code")
    elif not all(values[k] for k in PROOF_FIELDS[1:]):
        raise ValueError("Provide email, or first name, last name and postal code")
    return values


def search_body(proof: dict) -> dict:
    checked = verification_inputs(**proof)
    return {k: v for k, v in checked.items() if v}


def matches_customer(record: dict, proof: dict, expected_id: str = "") -> bool:
    try:
        proof = verification_inputs(**proof)
    except (TypeError, ValueError):
        return False
    if not isinstance(record, dict) or not isinstance(record.get("customer_id"), str) or not record["customer_id"]:
        return False
    if expected_id and record["customer_id"] != expected_id:
        return False
    if proof["email"]:
        return isinstance(record.get("email"), str) and normalized(record["email"]) == normalized(proof["email"])
    name, address = record.get("name"), record.get("default_shipping_address")
    return (isinstance(name, dict) and isinstance(address, dict)
            and all(isinstance(name.get(k), str) and normalized(name[k]) == normalized(proof[k]) for k in ("first_name", "last_name"))
            and isinstance(address.get("postal_code"), str)
            and normalized(address["postal_code"]) == normalized(proof["postal_code"]))


def fields_from_text(text: str) -> dict[str, str]:
    """Extract independently supplied fields without requiring one-turn completion."""
    email = find_email(text)
    if email:
        return {"email": email}
    values = {}
    labels = {"first_name": r"first[_ ]name|名", "last_name": r"last[_ ]name|姓",
              "postal_code": r"postal[_ ]code|zip(?: code)?|邮编"}
    for key, label in labels.items():
        match = re.search(rf"(?:{label})\s*[:：=]\s*([^;,，；\n]+)", text, re.I)
        values[key] = match.group(1).strip() if match else ""
    if not values["first_name"] or not values["last_name"]:
        match = re.search(r"my name is\s+([^,;\n]+?)(?=\s+(?:and\s+)?(?:my\s+)?(?:zip|postal)|[,;]|$)", text, re.I)
        parts = match.group(1).strip().split() if match else []
        if len(parts) == 2:
            values["first_name"], values["last_name"] = parts
        postal = re.search(r"(?:zip|postal(?: code)?|邮编)\s*(?:code\s*)?(?:is\s*)?[:：=]?\s*([A-Za-z0-9][A-Za-z0-9 -]*)(?:[.,;]|$)", text, re.I)
        if postal:
            values["postal_code"] = postal.group(1).strip()
    return {k: v for k, v in values.items() if v}


def proof_from_text(text: str) -> dict | None:
    """Parse complete explicit fields; ambiguous names prompt for clarification."""
    try:
        return verification_inputs(**fields_from_text(text))
    except ValueError:
        return None


def supplied_by_user(proof: dict, history: list) -> bool:
    """Profile/tool content is never an independent verification source."""
    user_text = "\n".join(e.get("content", "") for e in history if e.get("role") == "user")
    try:
        proof = verification_inputs(**proof)
    except (ValueError, TypeError):
        return False
    if proof["email"]:
        return any(normalized(proof["email"]) == normalized(v) for v in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", user_text))
    return all(re.search(r"(?<!\w)" + re.escape(normalized(v)) + r"(?!\w)", normalized(user_text)) for v in proof.values() if v)
