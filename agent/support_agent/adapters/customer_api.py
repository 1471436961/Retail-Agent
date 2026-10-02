"""Business API transport: no private DB, external endpoint, or credentials."""

from urllib.parse import quote

from support_agent.adapters.client_api import request_object


def verify_and_read_customer(client_api, customer_id: str, email: str) -> dict:
    """Retail: independent search must match the claimed ID before any detail read."""
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Provide your email to verify identity; customer ID alone is insufficient")
    search = request_object(client_api, "POST", "/v1/customers/search", body={"email": email})
    found = search.get("customer_id")
    if not isinstance(found, str) or not found or (customer_id and found != customer_id):
        raise ValueError("Identity verification failed; no customer details were loaded")
    customer = read_customer(client_api, found)
    if customer.get("customer_id", found) != found or not isinstance(customer.get("email"), str) or customer["email"].casefold() != email.casefold():
        raise ValueError("Identity verification failed; no customer details were loaded")
    return customer


def read_customer(client_api, customer_id: str) -> dict:
    """Read one customer through the injected environment API."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ValueError("customer_id is required")
    return request_object(client_api, "GET", f"/v1/customers/{quote(customer_id, safe='')}")
