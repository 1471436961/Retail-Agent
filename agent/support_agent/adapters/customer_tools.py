"""Tau2 retail tool boundaries adapted to the classroom REST contract."""

import ast
import json
import math
import operator
from urllib.parse import quote

from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase as _ClientAPIToolKitBase
from support_agent.adapters.customer_api import request_object, read_customer, verify_and_read_customer
from support_agent.config import DOMAIN
from support_agent.domain.preferences import RankingCriterion, rank_variants, ranking_criteria


def _address(address1, address2, city, state, country, zip):
    return {"address_line_1": address1, "address_line_2": address2 or None,
            "city": city, "region": state, "country": country, "postal_code": zip}


class CustomerTools(_ClientAPIToolKitBase):
    """Small REST adapters. No intent parsing or caller-supplied session state."""

    def use_tool(self, tool_name, /, **kwargs):
        # Environment otherwise recursively converts dict scalars to strings.
        result = super().use_tool(tool_name, **kwargs)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    def _request(self, method, path, body=None):
        # One request; no automatic retry of a non-idempotent operation.
        return request_object(self.client_api, method, path, body=body)

    @is_tool(ToolType.READ)
    def lookup_customer(self, customer_id: str, email: str = "") -> dict:
        """Original platform customer lookup: verify email before loading retail details.

        Args:
            customer_id: Claimed customer ID, or empty string to search by email.
            email: Email independently provided by the customer.
        """
        if DOMAIN == "retail_plus":
            return verify_and_read_customer(self.client_api, customer_id, email)
        return read_customer(self.client_api, customer_id)

    @is_tool(ToolType.READ)
    def find_user_id_by_email(self, email: str) -> dict:
        """Authenticate by the customer-supplied email. Returns customer_id.

        Args:
            email: Customer's email, extracted from their own messages.
        """
        return self._request("POST", "/v1/customers/search", {"email": email})

    @is_tool(ToolType.READ)
    def find_user_id_by_name_zip(self, first_name: str, last_name: str, zip: str) -> dict:
        """Authenticate by full name and postal code, without requiring email.

        Args:
            first_name: Customer's first name.
            last_name: Customer's last name.
            zip: Customer's postal code.
        """
        return self._request("POST", "/v1/customers/search",
                             {"first_name": first_name, "last_name": last_name, "postal_code": zip})

    @is_tool(ToolType.READ)
    def get_user_details(self, user_id: str) -> dict:
        """Read the authenticated customer's profile, saved methods and order IDs.

        Args:
            user_id: The customer_id obtained from a successful identity search.
        """
        return self._request("GET", f"/v1/customers/{quote(user_id, safe='')}")

    @is_tool(ToolType.READ)
    def get_order_details(self, order_id: str) -> dict:
        """Read an authenticated customer's order, including status and payments.

        Args:
            order_id: Exact owned order ID including its leading #.
        """
        return self._request("GET", f"/v1/orders/{quote(order_id, safe='')}")

    @is_tool(ToolType.READ)
    def list_all_product_types(self) -> dict:
        """List public product names and IDs for relevant catalog searches."""
        return self._request("GET", "/v1/catalog/products")

    @is_tool(ToolType.READ)
    def get_product_details(self, product_id: str) -> dict:
        """Read all variants, options, current prices and availability for a product.

        Args:
            product_id: Product ID from an order or catalog; not an item ID.
        """
        return self._request("GET", f"/v1/catalog/products/{quote(product_id, safe='')}")

    @is_tool(ToolType.READ)
    def get_item_details(self, item_id: str) -> dict:
        """Read one catalog variant. Its price is not the historical purchase price.

        Args:
            item_id: Exact variant item ID from an order or product.
        """
        return self._request("GET", f"/v1/catalog/items/{quote(item_id, safe='')}")

    @is_tool(ToolType.READ)
    def rank_preferred(self, order_id: str, item_id: str, allowed_options: dict[str, list[str] | None],
                       sort_by: list[RankingCriterion]) -> dict:
        """Rank same-product variants using the model's interpretation of customer priorities.

        Reads the order and catalog; does not modify anything. Allowed-option
        lists are hard constraints, not priority orders. Unmentioned original
        options stay unchanged; null explicitly removes a constraint. Sort keys
        execute in the exact order supplied, with no implicit price or ID tie
        breaker. Empty sort_by leaves all eligible candidates tied. The model
        extracts priorities from ordinary customer language, including conditional
        fallbacks, then uses actual catalog names/values in this tool.

        Args:
            order_id: Exact owned order ID, after customer authentication.
            item_id: Original purchased item ID from that order.
            allowed_options: Accepted values per changed option, using catalog strings;
                null only when the customer is indifferent. Unmentioned options retain original values.
            sort_by: Customer-derived criteria in decreasing priority. For price use
                field='price' and an explicit direction='ascending' or 'descending'.
                For an option use field='option', option=<catalog name>, values=<preferred
                values in order>; unlisted values tie last. Omit unstated criteria;
                use [] when there is no ranking preference. Never invent a priority.
        """
        criteria = ranking_criteria(sort_by)
        order = self.get_order_details(order_id)
        originals = [item for item in order["items"] if item["item_id"] == item_id]
        if not originals:
            raise ValueError("The original item is not present in this order")
        original = originals[0]
        if any(item["product_id"] != original["product_id"] or item["options"] != original["options"]
               for item in originals):
            raise ValueError("Repeated original item IDs have inconsistent product specifications")
        product = self.get_product_details(original["product_id"])
        if product["product_id"] != original["product_id"]:
            raise ValueError("The catalog response does not match the purchased product")
        ranking = rank_variants(original["options"], allowed_options, criteria, product["items"])
        for candidate in ranking["ranked_candidates"]:
            candidate["is_current_item"] = candidate["item_id"] == item_id
        return {
            "order_id": order_id,
            "item_id": item_id,
            "product_id": original["product_id"],
            "original_options": original["options"],
            "original_purchase_prices": [item["price"] for item in originals],
            **ranking,
        }

    @is_tool(ToolType.WRITE)
    def modify_user_address(self, user_id: str, address1: str, address2: str,
                            city: str, state: str, country: str, zip: str) -> dict:
        """Replace the complete default address after recap and explicit confirmation.

        Args:
            user_id: Authenticated customer_id.
            address1: First address line.
            address2: Second address line, or empty string if absent.
            city: City.
            state: State or region.
            country: Country.
            zip: Postal code.
        """
        return self._request("PUT", f"/v1/customers/{quote(user_id, safe='')}/default-shipping-address",
                             _address(address1, address2, city, state, country, zip))

    @is_tool(ToolType.WRITE)
    def modify_pending_order_address(self, order_id: str, address1: str, address2: str,
                                     city: str, state: str, country: str, zip: str) -> dict:
        """Replace a pending order's complete address after customer confirmation.

        Args:
            order_id: Owned pending order ID including #.
            address1: First address line.
            address2: Second address line, or empty string if absent.
            city: City.
            state: State or region.
            country: Country.
            zip: Postal code.
        """
        return self._request("PUT", f"/v1/orders/{quote(order_id, safe='')}/shipping-address",
                             _address(address1, address2, city, state, country, zip))

    @is_tool(ToolType.WRITE)
    def modify_pending_order_payment(self, order_id: str, payment_method_id: str) -> dict:
        """Switch a pending order to one different saved method after confirmation.

        Args:
            order_id: Owned pending order ID including #.
            payment_method_id: Saved method covering the whole charge; no split payment.
        """
        return self._request("PUT", f"/v1/orders/{quote(order_id, safe='')}/payment-method",
                             {"payment_method_id": payment_method_id})

    @is_tool(ToolType.WRITE)
    def cancel_pending_order(self, order_id: str, reason: str) -> dict:
        """Cancel a pending order after confirming its ID, reason and original refunds.

        Args:
            order_id: Owned pending order ID including #.
            reason: Exactly 'no longer needed' or 'ordered by mistake', chosen by the customer.
        """
        return self._request("POST", f"/v1/orders/{quote(order_id, safe='')}/cancellations", {"reason": reason})

    def _replace_items(self, order_id, item_ids, new_item_ids, payment_method_id, suffix):
        if not item_ids or len(item_ids) != len(new_item_ids):
            raise ValueError("Original and new item lists must have the same nonzero length")
        replacements = [{"existing_item_id": old, "replacement_item_id": new}
                        for old, new in zip(item_ids, new_item_ids)]
        return self._request("POST", f"/v1/orders/{quote(order_id, safe='')}/{suffix}",
                             {"replacements": replacements, "payment_method_id": payment_method_id})

    @is_tool(ToolType.WRITE)
    def modify_pending_order_items(self, order_id: str, item_ids: list[str],
                                    new_item_ids: list[str], payment_method_id: str) -> dict:
        """Submit ALL confirmed pending-item changes once. This locks later order changes.

        Args:
            order_id: Owned pending order ID including #.
            item_ids: Complete ordered original item IDs; preserve repeated occurrences.
            new_item_ids: Corresponding available variants of the same products, in matching order.
            payment_method_id: Saved method for the signed difference, including zero difference.
        """
        return self._replace_items(order_id, item_ids, new_item_ids, payment_method_id, "item-modifications")

    @is_tool(ToolType.WRITE)
    def exchange_delivered_order_items(self, order_id: str, item_ids: list[str],
                                       new_item_ids: list[str], payment_method_id: str) -> dict:
        """Submit ALL confirmed delivered-order exchanges once; no new order is needed.

        Args:
            order_id: Owned delivered order ID including #.
            item_ids: Complete ordered original item IDs, including repeated occurrences.
            new_item_ids: Corresponding available variants of the same products, in matching order.
            payment_method_id: Saved method for paying or receiving the signed price difference.
        """
        return self._replace_items(order_id, item_ids, new_item_ids, payment_method_id, "exchanges")

    @is_tool(ToolType.WRITE)
    def return_delivered_order_items(self, order_id: str, item_ids: list[str], payment_method_id: str) -> dict:
        """Request the confirmed return to the original method or an existing gift card.

        Args:
            order_id: Owned delivered order ID including #.
            item_ids: Complete confirmed original item list, retaining repeated occurrences.
            payment_method_id: Original method or gift card already saved at return-request opening.
        """
        return self._request("POST", f"/v1/orders/{quote(order_id, safe='')}/returns",
                             {"item_ids": item_ids, "refund_payment_method_id": payment_method_id})

    @is_tool(ToolType.WRITE, mutates_state=True)
    def transfer_to_human_agents(self, summary: str) -> dict:
        """Transfer when available actions cannot handle the request, or the user asks for a human.

        Args:
            summary: Factual request summary, completed work and unresolved issues. Do not retry.
        """
        conversation = self.client_api.context.conversation_id
        return self._request("POST", f"/v1/conversations/{quote(conversation, safe='')}/transfers", {"summary": summary})

    @is_tool(ToolType.THINK)
    def calculate(self, expression: str) -> str:
        """Evaluate numerical arithmetic and round to two decimal places.

        Args:
            expression: Numbers, +, -, *, / and parentheses; use original prices for refunds.
        """
        if len(expression) > 512:
            raise ValueError("Expression is too long")
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 128:
            raise ValueError("Expression is too complex")
        binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

        def evaluate(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = float(node.value)
            elif isinstance(node, ast.BinOp) and type(node.op) in binary:
                value = binary[type(node.op)](evaluate(node.left), evaluate(node.right))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            else:
                raise ValueError("Only numerical arithmetic is supported")
            if not math.isfinite(value):
                raise ValueError("Arithmetic must be finite")
            return value

        return str(round(evaluate(tree.body), 2))
