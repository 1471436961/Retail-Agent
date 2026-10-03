"""Read-only tools; explicit verification arguments make new-instance replay safe."""
from support_agent.adapters import read_api
from tau2.environment.toolkit import ToolType, is_tool
from tau2.hyper.client_api import ClientAPIToolKitBase


class ReadTools(ClientAPIToolKitBase):
    @is_tool(ToolType.READ)
    def verify_customer(self, customer_id: str = "", email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """Verify independent email OR full name plus postal code before reading a profile."""
        return read_api.verify_customer(self.client_api, customer_id, email, first_name, last_name, postal_code)

    @is_tool(ToolType.READ)
    def read_customer_profile(self, customer_id: str, email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """Read only the session customer, revalidating the recorded independent inputs."""
        return read_api.verify_customer(self.client_api, customer_id, email, first_name, last_name, postal_code)

    @is_tool(ToolType.READ)
    def get_order(self, order_id: str, customer_id: str, email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """Read an order only if the verified profile lists it and returned owner matches."""
        return read_api.get_order(self.client_api, order_id, customer_id=customer_id, email=email, first_name=first_name, last_name=last_name, postal_code=postal_code)

    @is_tool(ToolType.READ)
    def list_customer_orders(self, customer_id: str, status: str = "", email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """List owned orders, optionally filtering one exact teaching status; no date inference."""
        return read_api.list_customer_orders(self.client_api, status, customer_id=customer_id, email=email, first_name=first_name, last_name=last_name, postal_code=postal_code)

    @is_tool(ToolType.READ)
    def list_products(self, customer_id: str, email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """List the public product kinds relevant to the verified customer's current request."""
        return read_api.list_products(self.client_api, customer_id=customer_id, email=email, first_name=first_name, last_name=last_name, postal_code=postal_code)

    @is_tool(ToolType.READ)
    def get_product(self, product_id: str, customer_id: str, email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """Read a public product's variants, current prices, options and availability."""
        return read_api.get_product(self.client_api, product_id, customer_id=customer_id, email=email, first_name=first_name, last_name=last_name, postal_code=postal_code)

    @is_tool(ToolType.READ)
    def get_item(self, item_id: str, customer_id: str, email: str = "", first_name: str = "", last_name: str = "", postal_code: str = "") -> dict:
        """Read one public variant; its current price is not an order's original price."""
        return read_api.get_item(self.client_api, item_id, customer_id=customer_id, email=email, first_name=first_name, last_name=last_name, postal_code=postal_code)
