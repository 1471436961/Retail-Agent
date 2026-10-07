"""Explicit trusted sequential-session port; never installed by the factory.

The host/toolkit owns the Client API and one SessionClaims per live backend.
Sharing that store across runtime instances protects stale snapshots in this
process. A new backend replay starts a new store. This is not a database, CAS,
or a guarantee across arbitrary workers/crashes. No network client is created.
"""
import json
from threading import RLock
from urllib.parse import quote

from support_agent.adapters.client_api import request_object
from support_agent.domain.catalog import resolve_replacements
from support_agent.domain.policies import settlement_method_rule
from support_agent.domain.rules import allow, need
from support_agent.proposals import _scope_facts, check_confirmation
from support_agent.state import clone_state
from support_agent.write_session import WriteRuntime, WriteClaimConflict, claim_identity


class SessionClaims:
    def __init__(self):
        self.lock = RLock()
        self.sessions = {}
        self.dispatched = set()
        self.handoffs = {}  # Trusted conversation barrier, including stale business snapshots.


def ensure_business_active(client_api, claims):
    """Reject stale internal workflow snapshots before even refreshing facts."""
    conversation = getattr(getattr(client_api, "context", None), "conversation_id", None)
    with claims.lock:
        if claims.handoffs.get(conversation, {}).get("status") in {"sent", "unknown", "accepted"}:
            raise ValueError("Conversation transfer blocks business workflow calls")


class SessionWriteRuntime(WriteRuntime):
    def __init__(self, client_api, *, claims, requested_options=None):
        super().__init__(client_api)
        conversation = getattr(getattr(client_api, "context", None), "conversation_id", None)
        if not isinstance(conversation, str) or not conversation or not isinstance(claims, SessionClaims):
            raise ValueError("Trusted Client API conversation and session-owned claim store are required")
        self.conversation = conversation
        self.claims = claims
        self.requested_options = requested_options
        self._claimed_id = None

    def assess_submission(self, state, version, spec):
        # Explicit caller is the trusted host workflow. SDK user roles and the
        # returned recap/state are the classroom boundary; no reading receipt or
        # signature is invented. Full journal/consent consistency is rechecked.
        if any(o["mutates"] and o["version"] == version and o["spec"] == spec for o in state["operations"]):
            clone_state(state)  # Reconciliation validates the original journal, not new post-write consent.
            return allow("original_submission_checked", "The original submitted journal is internally consistent.", "CF-01")
        return check_confirmation(state, version, spec)

    def assess_business(self, state, spec):
        facts = _scope_facts(state["history"], spec)
        action, order = spec["action"], facts["order"]
        if action == "cancel" and any(p["transaction_type"] == "refund" for p in order["payments"]):
            return need("cancellation_refund_history_review", "Historical refunds require review; the known upstream loop can refund them again.", "RF-01")
        if action == "payment_method":
            payments = order["payments"]
            if len(payments) != 1 or payments[0]["transaction_type"] != "payment":
                return need("current_payment_basis_unsupported", "This SDK supports payment switching only for one original payment; do not net historical rows.", "PY-02")
            if payments[0]["amount"] != spec["amount"]["value"]:
                return need("order_charge_mismatch", "The proposed full charge does not match the original payment.", "MO-01")
            return settlement_method_rule(action, facts["customer"]["payment_methods"],
                    spec["parameters"]["payment_method_id"], spec["amount"]["value"],
                    current_payment_method_id=payments[0]["payment_method_id"])
        if action in {"modify_items", "exchange"}:
            if self.requested_options is None:
                return need("requested_options_required", "The trusted producer must supply the requested attribute changes; confirmation is not their validation.", "IT-01")
            products = {}
            for row in facts["catalog"]:
                product_id = row["source"].get("product_id")
                if product_id is None:
                    return need("product_membership_required", "Read the target product envelope to establish membership.", "IT-01")
                products.setdefault(product_id, {"product_id": product_id, "name": "accepted product", "items": []})["items"].append(row["item"])
            # One catalog entry per variant, even when multiple units use it.
            for product in products.values():
                product["items"] = list({i["item_id"]: i for i in product["items"]}.values())
            return resolve_replacements(order["items"], spec["parameters"]["replacements"],
                                        list(products.values()), requested_options=self.requested_options,
                                        sequential_matching=action == "modify_items", allow_same_variant=action == "exchange")
        return allow("complete_parameters_checked", "Accepted facts bind the complete confirmed parameters; no settlement is asserted.", "CF-01")

    def claim_sent(self, state, call_id):
        state = clone_state(state)
        identity = claim_identity(state, call_id)
        op = next(o for o in state["operations"] if o["call_id"] == call_id)
        if op["status"] != "sent" or op["persistence_unresolved"]:
            raise WriteClaimConflict("Only a consistent original sent event can be claimed")
        with self.claims.lock:
            if self.claims.handoffs.get(self.conversation, {}).get("status") in {"sent", "unknown", "accepted"}:
                raise WriteClaimConflict("Conversation transfer blocks business claims")
            session = self.claims.sessions.setdefault(self.conversation, {})
            visible = {claim_identity(state, o["call_id"]) for o in state["operations"] if o["mutates"]}
            if identity in session or not set(session) <= visible:
                raise WriteClaimConflict("Duplicate identity or stale journal")
            if any(o["spec"]["target"] == op["spec"]["target"] and
                   (o["status"] in {"sent", "unknown", "acknowledged"} or o["persistence_unresolved"])
                   for o in session.values()):
                raise WriteClaimConflict("Unresolved record claim")
            session[identity] = json.loads(json.dumps(op))
            self._claimed_id = identity
            return True

    def checkpoint(self, state):
        state = clone_state(state)
        with self.claims.lock:
            session = self.claims.sessions.get(self.conversation, {})
            visible = {claim_identity(state, o["call_id"]) for o in state["operations"] if o["mutates"]}
            if not set(session) <= visible:
                raise WriteClaimConflict("Checkpoint omits claimed operations")
            for op in state["operations"]:
                if op["mutates"]:
                    identity = claim_identity(state, op["call_id"])
                    if identity not in session or session[identity]["spec"] != op["spec"]:
                        raise WriteClaimConflict("Checkpoint lacks its original claim")
                    previous = session[identity]
                    if previous["status"] != "sent" and previous["status"] != op["status"] and not (
                            previous["status"] == "acknowledged" and op["status"] == "succeeded"):
                        raise WriteClaimConflict("Checkpoint cannot regress outcome")
                    if previous["persistence_unresolved"] and not op["persistence_unresolved"]:
                        raise WriteClaimConflict("Checkpoint cannot erase uncertainty")
                    session[identity] = json.loads(json.dumps(op))

    def send(self, spec):
        with self.claims.lock:
            if self.claims.handoffs.get(self.conversation, {}).get("status") in {"sent", "unknown", "accepted"}:
                raise WriteClaimConflict("Conversation transfer blocks business sending")
            identity = self._claimed_id
            op = self.claims.sessions.get(self.conversation, {}).get(identity)
            dispatch = (self.conversation, identity)
            if op is None or op["status"] != "sent" or op["spec"] != spec or dispatch in self.claims.dispatched:
                raise WriteClaimConflict("An unused original send claim is required")
            self.claims.dispatched.add(dispatch)
        action, target = spec["action"], spec["target"]
        endpoints = {"default_shipping_address": ("PUT", "customers", "customer_id", "default-shipping-address"),
                     "shipping_address": ("PUT", "orders", "order_id", "shipping-address"),
                     "payment_method": ("PUT", "orders", "order_id", "payment-method"),
                     "cancel": ("POST", "orders", "order_id", "cancellations"),
                     "modify_items": ("POST", "orders", "order_id", "item-modifications"),
                     "exchange": ("POST", "orders", "order_id", "exchanges"),
                     "return": ("POST", "orders", "order_id", "returns")}
        method, collection, key, suffix = endpoints[action]
        path = f"/v1/{collection}/{quote(target[key], safe='')}/{suffix}"
        # Amount is proposal/display evidence only. Never invent a refund API
        # or send the estimated refund/full quote as an extra backend field.
        return request_object(self.client_api, method, path, body=spec["parameters"], mutates=True)
