"""M4.5: the same failure semantics across five actual default write endpoints.

Subtests are endpoint scenarios, not extra unittest or complete public ATs.
"""
import json
import unittest
from copy import deepcopy

from fakes import FakeResponse
from test_m4_addresses import NEW
from test_m4_handoffs import HandoffConversation, TRANSFER_NOTICE
from support_agent.protocol import ToolOutcome, TurnInput
from support_agent.turns import advance

ENDPOINTS = {
    "default": ("PUT", "/v1/customers/customer_a/default-shipping-address"),
    "order": ("PUT", "/v1/orders/%23TEST1/shipping-address"),
    "payment": ("PUT", "/v1/orders/%23TEST1/payment-method"),
    "cancel": ("POST", "/v1/orders/%23TEST1/cancellations"),
    "handoff": ("POST", "/v1/conversations/synthetic-address-session/transfers"),
}


def prepare(flow, kind):
    if kind == "default": return flow.change(target="default")
    if kind == "order": return flow.change()
    if kind == "payment": return flow.switch()
    if kind == "cancel": return flow.cancel()
    return flow.user("转人工", consume=False)


def submit(flow, kind, dispatch):
    return flow.consume(dispatch) if kind == "handoff" else flow.user("yes")


def endpoint_calls(flow, kind):
    return [c for c in flow.api.calls if c[:2] == ENDPOINTS[kind]]


class FiveEndpointMatrixTests(unittest.TestCase):
    def assert_outcome(self, flow, kind, status):
        if kind == "handoff":
            self.assertEqual(flow.state["handoff"]["status"], {"succeeded":"accepted", "failed":"rejected", "unknown":"unknown"}[status])
            self.assertEqual(flow.handoff_code(), {"succeeded":"handoff_accepted", "failed":"handoff_rejected", "unknown":"handoff_result_unknown"}[status])
        else:
            writes = [o for o in flow.state["operations"] if o["mutates"]]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]["status"], status)
            assessments = [e[k + "_assessment"] for e in flow.state["history"] for k in ("address", "payment", "cancellation") if k + "_assessment" in e]
            latest = assessments[-1]
            codes = [r["code"] for r in latest["details"].get("records", [])] or [latest["code"]]
            self.assertIn({"succeeded":"write_verified", "failed":"write_rejected", "unknown":"write_result_unknown"}[status], codes)

    def test_all_five_endpoints_have_one_normal_send_exact_body_and_verified_or_accepted_result(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); dispatch = prepare(flow, kind)
                self.assertEqual(endpoint_calls(flow, kind), [])
                submit(flow, kind, dispatch)
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)
                self.assert_outcome(flow, kind, "succeeded")
                body = endpoint_calls(flow, kind)[0][2]
                expected = {"default":set(NEW), "order":set(NEW), "payment":{"payment_method_id"}, "cancel":{"reason"}, "handoff":{"summary"}}[kind]
                self.assertEqual(set(body), expected)

    def test_409_is_definite_failure_on_each_endpoint_and_never_automatically_retries(self):
        self._rejection(409)

    def test_422_is_definite_failure_on_each_endpoint_and_never_automatically_retries(self):
        self._rejection(422)

    def _rejection(self, status):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind, http=status):
                flow = HandoffConversation(); dispatch = prepare(flow, kind)
                original = flow.api.request
                before_orders, before_customers = deepcopy(flow.api.orders), deepcopy(flow.api.customers)
                def request(method, path, body=None):
                    if (method, path) == ENDPOINTS[kind]:
                        flow.api.calls.append((method, path, deepcopy(body)))
                        return FakeResponse(status, {"error":{"code":"synthetic_rejection", "message":"private_matrix_marker"}})
                    return original(method, path, body)
                flow.api.request = request
                submit(flow, kind, dispatch)
                self.assert_outcome(flow, kind, "failed")
                self.assertEqual(flow.api.orders, before_orders); self.assertEqual(flow.api.customers, before_customers)
                flow.api.request = original; flow.user("yes"); flow.user("retry")
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)
                self.assertNotIn("private_matrix_marker", json.dumps(flow.state))

    def test_timeout_after_backend_effect_is_unknown_on_each_endpoint_without_retry(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); dispatch = prepare(flow, kind); original = flow.api.request
                def request(method, path, body=None):
                    result = original(method, path, body)
                    if (method, path) == ENDPOINTS[kind]: raise TimeoutError("private_matrix_timeout")
                    return result
                flow.api.request = request; submit(flow, kind, dispatch)
                self.assert_outcome(flow, kind, "unknown")
                flow.api.request = original; flow.user("yes"); flow.user("retry")
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)
                self.assertNotIn("private_matrix_timeout", json.dumps(flow.state))

    def test_missing_success_field_is_unknown_for_each_endpoint_even_when_effect_happened(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); dispatch = prepare(flow, kind); original = flow.api.request
                def request(method, path, body=None):
                    result = original(method, path, body)
                    if (method, path) == ENDPOINTS[kind]:
                        broken = deepcopy(result.body)
                        del broken[{"default":"customer_id", "order":"order_id", "payment":"payments", "cancel":"cancellation", "handoff":"transfer_id"}[kind]]
                        return FakeResponse(result.status_code, broken)
                    return result
                flow.api.request = request; result = submit(flow, kind, dispatch)
                self.assert_outcome(flow, kind, "unknown")
                self.assertNotIn("accepted and independently verified", result.text)
                self.assertNotIn(TRANSFER_NOTICE, result.text)
                flow.api.request = original; flow.user("yes")
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)

    def test_lost_tool_result_after_real_send_is_unknown_and_not_zero_send_for_all_endpoints(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); dispatch = prepare(flow, kind)
                if kind != "handoff": dispatch = flow.user("yes", consume=False)
                call = dispatch.calls[0]; getattr(flow.toolkit, call.name)(**call.arguments)
                _, flow.state = advance(TurnInput("tools", outcomes=()), flow.state)
                if kind == "handoff": self.assertEqual(flow.state["handoff"]["status"], "unknown")
                else:
                    pending = flow.state[{"default":"address", "order":"address", "payment":"payment", "cancel":"cancellation"}[kind] + "_pending"]
                    self.assertEqual(pending["status"], "unknown")
                flow.user("yes"); flow.user("retry")
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)

    def test_wrong_tool_result_id_cannot_accept_any_of_the_five_successes(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); dispatch = prepare(flow, kind)
                if kind != "handoff": dispatch = flow.user("yes", consume=False)
                call = dispatch.calls[0]; payload = getattr(flow.toolkit, call.name)(**call.arguments)
                result, flow.state = advance(TurnInput("tools", outcomes=(ToolOutcome("wrong-id", json.dumps(payload)),)), flow.state)
                self.assertNotIn(TRANSFER_NOTICE, result.text)
                self.assertNotIn("accepted and independently verified", result.text)
                self.assertEqual(len(endpoint_calls(flow, kind)), 1)
                self.assertEqual([o for o in flow.state["operations"] if o["mutates"]], [])

    def test_changed_address_payment_or_reason_needs_fresh_full_confirmation(self):
        for kind in ("default", "order", "payment", "cancel"):
            with self.subTest(endpoint=kind):
                flow = HandoffConversation(); prepare(flow, kind)
                old = deepcopy(flow.state["proposals"][-1])
                if kind in {"default", "order"}: flow.user("city: Revised City")
                elif kind == "payment": flow.user("Use Visa instead")
                else: flow.user("reason: ordered by mistake")
                new = flow.state["proposals"][-1]
                self.assertGreater(new["version"], old["version"]); self.assertIsNone(new["confirmation"])
                self.assertNotEqual(new["spec"], old["spec"])
                self.assertEqual(endpoint_calls(flow, kind), [])
                flow.user("yes"); self.assert_outcome(flow, kind, "succeeded")
                self.assertEqual(endpoint_calls(flow, kind)[0][2], new["spec"]["parameters"])

    def test_transfer_withdrawal_after_dispatch_is_unknown_not_a_guessed_unsent_result(self):
        flow = HandoffConversation(); flow.user("转人工", consume=False)
        flow.user("do not transfer me")
        self.assertEqual(flow.state["handoff"]["status"], "unknown")
        self.assertEqual(flow.transfers(), [])
        flow.user("转人工"); self.assertEqual(flow.transfers(), [])

    def test_policy_or_input_denial_is_zero_send_on_all_five_endpoint_families(self):
        for kind in ENDPOINTS:
            with self.subTest(endpoint=kind):
                flow = HandoffConversation()
                if kind == "default": flow.user('Change default address: {"city":"Incomplete"}')
                elif kind == "order": flow.api.orders["#TEST1"]["status"] = "processed"; flow.change()
                elif kind == "payment": flow.switch(query="card_a")
                elif kind == "cancel": flow.cancel(reason="shipping is slow")
                else: flow.user("transfer me to a human if cheaper")
                diagnostic = next(e for e in reversed(flow.state["history"]) if any(k.endswith("_assessment") for k in e))
                result = next(v for k, v in diagnostic.items() if k.endswith("_assessment"))
                self.assertNotEqual(result["decision"], "allow")
                self.assertEqual(result["code"], {"default":"address_fields_required", "order":"address_state_not_allowed", "payment":"same_payment_method", "cancel":"clarify_cancellation_reason", "handoff":"handoff_request_clarification"}[kind])
                self.assertEqual(endpoint_calls(flow, kind), [])


if __name__ == "__main__": unittest.main()
