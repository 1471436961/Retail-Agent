"""Business API transport: no private DB, external endpoint, or credentials."""

from urllib.parse import quote

from support_agent.adapters.client_api import request_object
from support_agent.adapters.read_api import verify_customer


def verify_and_read_customer(client_api, customer_id: str, email: str) -> dict:
    """Keep the t1 interface; use the same strict verification as every M2 read."""
    return verify_customer(client_api, customer_id=customer_id, email=email)


def read_customer(client_api, customer_id: str) -> dict:
    """Read one customer through the injected environment API."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ValueError("customer_id is required")
    return request_object(client_api, "GET", f"/v1/customers/{quote(customer_id, safe='')}")
