"""Read-only preference ranking through the actual SDK and synthetic catalog."""
import copy
import json
import unittest
from unittest.mock import patch

from test_agent import ROOT, setup_retail, function_call
from platform_contract import validate_request, validate_response
from tau2.data_model.message import AssistantMessage, MultiToolMessage, UserMessage
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools
from tau2.environment.environment import Environment
from tau2.environment.toolkit import ToolType, get_tool_types
from tau2.hyper.agent_context import activate_agent_context, build_agent_context
from tau2.hyper.client_api import ClientAPI
from tau2.hyper.client_api.runtime import ClientAPIRuntime
from tau2.utils.llm_utils import validate_message_history
from agent import create_agent
from tools import Tools


def ranking_backend():
    base, *_ = setup_retail()
    data = base.model_dump(mode="json")
    def variant(identifier, options, price, available=True):
        return {"item_id": identifier, "options": options, "price": price, "available": available}
    def keyboard(switch="clicky", light="RGB", size="full size"):
        return {"switch type": switch, "backlight": light, "size": size}
    keys = [variant("key-current", keyboard("linear"), 100.0),
            variant("ideal", keyboard(), 120.0, False),
            variant("fallback-dark", keyboard(light="none"), 110.0),
            variant("fallback-white", keyboard(light="white"), 80.0),
            variant("wrong-size", keyboard(size="80%"), 50.0),
            variant("wrong-switch", keyboard("tactile", "none"), 40.0)]
    thermostats = [variant("thermo-current", {"compatibility": "Apple HomeKit", "color": "black"}, 350.0),
                   variant("thermo-target", {"compatibility": "Google Assistant", "color": "black"}, 250.0),
                   variant("thermo-white", {"compatibility": "Google Assistant", "color": "white"}, 150.0)]
    data["products"] = {name: {"product_id": name, "name": name,
                                     "variants": {v["item_id"]: v for v in variants}}
                        for name, variants in (("keyboard", keys), ("thermostat", thermostats))}
    items = []
    for name, source, price in (("keyboard", keys[0], 90.0), ("thermostat", thermostats[0], 300.0)):
        items.append({"name": name, "product_id": name, "item_id": source["item_id"],
                      "options": source["options"], "price": price})
    data["orders"] = {"#D1": data["orders"]["#D1"]}
    data["orders"]["#D1"]["items"] = items
    data["orders"]["#D1"]["payment_history"][0]["amount"] = 390.0
    data["users"]["casey"]["orders"] = ["#D1"]
    db = RetailDB.model_validate(data)
    runtime = ClientAPIRuntime(Environment("retail_plus", "", RetailTools(db)), conversation_id="offline/ranking")
    requests = []
    def transport(request):
        validate_request(request)
        requests.append(copy.deepcopy(request))
        response = runtime.dispatch(request)
        validate_response(request, response)
        return response
    tools = Tools(ClientAPI(transport, context=runtime.context))
    return db, requests, tools, Environment("retail_plus", "", tools)


class PreferenceRankingTests(unittest.TestCase):
    def setUp(self):
        self.db, self.requests, self.tools, self.environment = ranking_backend()

    def rank(self, allowed=None, sort_by=None):
        return self.tools.rank_preferred(
            "#D1", "key-current",
            {"switch type": ["clicky"]} if allowed is None else allowed,
            [] if sort_by is None else sort_by,
        )

    def test_constraints_exclude_unavailable_or_unaccepted_specs_without_writes(self):
        before = self.db.model_dump(mode="json")
        result = self.rank()
        self.assertEqual(result["ranked_candidates"], [])
        self.assertEqual([r["item_id"] for r in result["unavailable_matches"]], ["ideal"])
        self.assertEqual(result["effective_constraints"],
                         {"switch type": ["clicky"], "backlight": ["RGB"], "size": ["full size"]})
        self.assertEqual(result["ranking_criteria"], [])
        self.assertEqual(self.db.model_dump(mode="json"), before)
        self.assertEqual([(r["method"], r["path"]) for r in self.requests],
                         [("GET", "/v1/orders/%23D1"), ("GET", "/v1/catalog/products/keyboard")])

    def test_same_catalog_follows_feature_first_or_price_first_as_supplied(self):
        self.db.products["keyboard"].variants["ideal"].available = True
        allowed = {"switch type": ["clicky"], "backlight": ["RGB", "none"]}
        feature = {"field": "option", "option": "backlight", "values": ["RGB", "none"]}
        price = {"field": "price", "direction": "ascending"}
        feature_first = self.rank(allowed, [feature, price])
        price_first = self.rank(allowed, [price, feature])
        self.assertEqual([r["item_id"] for r in feature_first["ranked_candidates"]], ["ideal", "fallback-dark"])
        self.assertEqual([r["item_id"] for r in price_first["ranked_candidates"]], ["fallback-dark", "ideal"])
        self.assertEqual(feature_first["ranking_criteria"], [feature, price])
        self.assertEqual(price_first["ranking_criteria"], [price, feature])

    def test_customer_can_reverse_option_preferences_without_changing_the_tool(self):
        self.db.products["keyboard"].variants["ideal"].available = True
        allowed = {"switch type": ["clicky"], "backlight": ["RGB", "none"]}
        for values, expected in ((["RGB", "none"], ["ideal", "fallback-dark"]),
                                 (["none", "RGB"], ["fallback-dark", "ideal"])):
            with self.subTest(values=values):
                result = self.rank(allowed, [{"field": "option", "option": "backlight", "values": values}])
                self.assertEqual([r["item_id"] for r in result["ranked_candidates"]], expected)

    def test_explicit_fallback_preference_preserves_other_hard_constraints(self):
        result = self.rank({"switch type": ["clicky"], "backlight": ["RGB", "none"]},
                           [{"field": "option", "option": "backlight", "values": ["RGB", "none"]}])
        self.assertEqual([r["item_id"] for r in result["ranked_candidates"]], ["fallback-dark"])
        self.assertEqual(result["ranked_candidates"][0]["options"],
                         {"switch type": "clicky", "backlight": "none", "size": "full size"})
        self.assertEqual(result["ranked_candidates"][0]["sort_values"], [1])

    def test_constraint_value_order_does_not_create_a_sort_priority(self):
        common = {"switch type": ["clicky"]}
        first = self.rank({**common, "backlight": ["none", "white"]})
        second = self.rank({**common, "backlight": ["white", "none"]})
        self.assertEqual(first["ranked_candidates"], second["ranked_candidates"])
        self.assertEqual({r["preference_rank"] for r in first["ranked_candidates"]}, {1})

    def test_no_criteria_means_ties_without_a_hidden_price_or_id_tiebreaker(self):
        allowed = {"switch type": ["clicky"], "backlight": ["none", "white"]}
        first = self.rank(allowed)
        variants = self.db.products["keyboard"].variants
        self.db.products["keyboard"].variants = dict(reversed(list(variants.items())))
        second = self.rank(allowed)
        ranks = lambda result: {r["item_id"]: r["preference_rank"] for r in result["ranked_candidates"]}
        self.assertEqual(ranks(first), {"fallback-dark": 1, "fallback-white": 1})
        self.assertEqual(ranks(first), ranks(second))
        self.assertTrue(all(r["sort_values"] == [] for r in first["ranked_candidates"]))

    def test_option_only_sort_keeps_differently_priced_identical_specs_tied(self):
        variants = self.db.products["keyboard"].variants
        variants["ideal"].available = True
        variants["aaa-expensive"] = variants["ideal"].model_copy(update={"item_id": "aaa-expensive", "price": 130.0})
        result = self.rank(sort_by=[{"field": "option", "option": "backlight", "values": ["RGB"]}])
        self.assertEqual({r["item_id"]: r["preference_rank"] for r in result["ranked_candidates"]},
                         {"ideal": 1, "aaa-expensive": 1})
        self.assertEqual([r["price"] for r in result["ranked_candidates"]], [120.0, 130.0])

    def test_price_direction_must_be_explicit_and_can_be_reversed(self):
        self.db.products["keyboard"].variants["ideal"].available = True
        allowed = {"switch type": ["clicky"], "backlight": None}
        ascending = self.rank(allowed, [{"field": "price", "direction": "ascending"}])
        descending = self.rank(allowed, [{"field": "price", "direction": "descending"}])
        self.assertEqual([r["item_id"] for r in ascending["ranked_candidates"]],
                         ["fallback-white", "fallback-dark", "ideal"])
        self.assertEqual([r["item_id"] for r in descending["ranked_candidates"]],
                         ["ideal", "fallback-dark", "fallback-white"])
        self.requests.clear()
        with self.assertRaises(ValueError):
            self.rank(allowed, [{"field": "price"}])
        self.assertEqual(self.requests, [])

    def test_thermostat_keeps_color_unless_customer_explicitly_removes_that_constraint(self):
        keep = self.tools.rank_preferred("#D1", "thermo-current", {"compatibility": ["Google Assistant"]},
                                         [{"field": "price", "direction": "ascending"}])
        any_color = self.tools.rank_preferred(
            "#D1", "thermo-current", {"compatibility": ["Google Assistant"], "color": None},
            [{"field": "price", "direction": "ascending"}])
        self.assertEqual([r["item_id"] for r in keep["ranked_candidates"]], ["thermo-target"])
        self.assertEqual([r["item_id"] for r in any_color["ranked_candidates"]], ["thermo-white", "thermo-target"])
        self.assertEqual(keep["original_purchase_prices"], [300.0])

    def test_structured_options_are_literal_and_vocabulary_is_returned_to_the_model(self):
        result = self.tools.rank_preferred("#D1", "thermo-current", {"compatibility": ["Google Home"]}, [])
        self.assertEqual(result["ranked_candidates"], [])
        self.assertEqual(result["catalog_option_values"]["compatibility"], ["Apple HomeKit", "Google Assistant"])

    def test_ranking_keeps_all_historical_purchase_prices(self):
        order = self.db.orders["#D1"]
        order.items.append(order.items[0].model_copy(update={"price": 92.0}, deep=True))
        result = self.rank({"switch type": ["clicky"], "backlight": ["none"]})
        self.assertEqual(result["original_purchase_prices"], [90.0, 92.0])
        self.assertEqual(len(result["ranked_candidates"]), 1)
        self.assertEqual(order.status, "delivered")

    def test_sdk_declares_explicit_criteria_and_a_read_only_tool(self):
        self.assertEqual(get_tool_types(self.tools)["rank_preferred"], ToolType.READ)
        fields = self.tools.get_tools()["rank_preferred"].params.model_fields
        self.assertEqual(set(fields), {"order_id", "item_id", "allowed_options", "sort_by"})
        self.assertTrue(fields["sort_by"].is_required())
        with self.assertRaisesRegex(ValueError, "not present"):
            self.tools.rank_preferred("#D1", "not-purchased", {"size": ["M"]}, [])
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_native_model_supplies_priorities_and_gets_ranking_before_confirmed_bulk_exchange(self):
        context = build_agent_context(domain="retail_plus", tools=list(self.tools.get_tools().values()),
                                      resource_root=ROOT / "agent", model_configs=[{"model": "offline/ranking"}])
        with activate_agent_context(context):
            application = create_agent()
        criterion = {"field": "option", "option": "backlight", "values": ["RGB", "none"]}
        call = function_call("rank_preferred", {
            "order_id": "#D1", "item_id": "key-current",
            "allowed_options": {"switch type": ["clicky"], "backlight": ["RGB", "none"]},
            "sort_by": [criterion],
        })
        thermostat_call = function_call("rank_preferred", {
            "order_id": "#D1", "item_id": "thermo-current",
            "allowed_options": {"compatibility": ["Google Assistant"]}, "sort_by": [],
        }, "thermostat-ranking")
        call.tool_calls.extend(thermostat_call.tool_calls)
        with patch("tau2.hyper.agent_context.generate", return_value=call):
            reply, state = application.generate_next_message(
                UserMessage(role="user", content="Clicky, full size, preferably RGB; only if unavailable use no backlight. Also change the thermostat to Google compatibility, keeping black."),
                application.get_init_state())
        outcomes = [self.environment.get_response(tool_call) for tool_call in reply.tool_calls]
        self.assertTrue(all(not outcome.error for outcome in outcomes))
        observed = []
        def provider(**kwargs):
            validate_message_history(kwargs["messages"])
            observed.extend(kwargs["messages"])
            return AssistantMessage(role="assistant", content="Exchange the full-size clicky keyboard without backlight and the black Google-compatible thermostat, a $30 refund difference via PayPal. Is that everything, and may I proceed?")
        with patch("tau2.hyper.agent_context.generate", side_effect=provider):
            reply, state = application.generate_next_message(MultiToolMessage(role="tool", tool_messages=outcomes), state)
        ranking = json.loads(observed[-2].content)
        self.assertEqual(ranking["ranked_candidates"][0]["item_id"], "fallback-dark")
        self.assertEqual(ranking["ranking_criteria"], [criterion])
        self.assertEqual(observed[-2].id, call.tool_calls[0].id)
        self.assertEqual(json.loads(observed[-1].content)["ranked_candidates"][0]["item_id"], "thermo-target")
        self.assertEqual(self.db.orders["#D1"].status, "delivered")
        self.assertTrue(all(r["method"] == "GET" for r in self.requests))
        exchange = function_call("exchange_delivered_order_items", {
            "order_id": "#D1", "item_ids": ["key-current", "thermo-current"],
            "new_item_ids": ["fallback-dark", "thermo-target"], "payment_method_id": "paypal_test",
        }, "exchange")
        with patch("tau2.hyper.agent_context.generate", return_value=exchange):
            reply, state = application.generate_next_message(
                UserMessage(role="user", content="Yes, exchange both as agreed using PayPal."), state)
        outcome = self.environment.get_response(reply.tool_calls[0])
        self.assertFalse(outcome.error, outcome.content)
        posts = [r for r in self.requests if r["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["body"]["replacements"], [
            {"existing_item_id": "key-current", "replacement_item_id": "fallback-dark"},
            {"existing_item_id": "thermo-current", "replacement_item_id": "thermo-target"},
        ])
        final = AssistantMessage(role="assistant", content="The exchange request for both items was recorded; this does not confirm refund settlement.")
        with patch("tau2.hyper.agent_context.generate", return_value=final):
            reply, state = application.generate_next_message(MultiToolMessage(role="tool", tool_messages=[outcome]), state)
        self.assertEqual(reply.content, final.content)
        self.assertFalse(reply.tool_calls)
        self.assertEqual(len([r for r in self.requests if r["method"] == "POST"]), 1)
        self.assertEqual(self.db.orders["#D1"].exchange_price_difference, -30.0)
        json.dumps(state, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
