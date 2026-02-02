"""
Odoo XML-RPC Client for inventory data access.
"""

import xmlrpc.client
from typing import Any, Optional
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class OdooConfig:
    """Odoo connection configuration."""
    url: str
    database: str
    username: str
    api_key: str  # API key for authentication (used instead of password)


class OdooClient:
    """Client for connecting to Odoo via XML-RPC."""

    def __init__(self, config: OdooConfig):
        self.config = config
        self._uid: Optional[int] = None
        self._common: Optional[xmlrpc.client.ServerProxy] = None
        self._models: Optional[xmlrpc.client.ServerProxy] = None

    def connect(self) -> bool:
        """Establish connection to Odoo and authenticate."""
        try:
            self._common = xmlrpc.client.ServerProxy(
                f"{self.config.url}/xmlrpc/2/common"
            )
            self._models = xmlrpc.client.ServerProxy(
                f"{self.config.url}/xmlrpc/2/object"
            )

            # Authenticate using API key
            # With API keys, we authenticate using the username and API key
            self._uid = self._common.authenticate(
                self.config.database,
                self.config.username,
                self.config.api_key,
                {}
            )

            return self._uid is not None and self._uid > 0
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Odoo: {e}")

    @property
    def uid(self) -> int:
        """Get authenticated user ID."""
        if self._uid is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._uid

    def execute(
        self,
        model: str,
        method: str,
        *args,
        **kwargs
    ) -> Any:
        """Execute a method on an Odoo model."""
        if self._models is None:
            raise RuntimeError("Not connected. Call connect() first.")

        return self._models.execute_kw(
            self.config.database,
            self.uid,
            self.config.api_key,
            model,
            method,
            args,
            kwargs
        )

    def search(
        self,
        model: str,
        domain: list,
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None
    ) -> list[int]:
        """Search for records matching domain."""
        kwargs = {"offset": offset}
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search", domain, **kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: Optional[list[str]] = None
    ) -> list[dict]:
        """Read records by IDs."""
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute(model, "read", ids, **kwargs)

    def search_read(
        self,
        model: str,
        domain: list,
        fields: Optional[list[str]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order: Optional[str] = None
    ) -> list[dict]:
        """Search and read records in one call."""
        kwargs = {"offset": offset}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain, **kwargs)

    def search_count(self, model: str, domain: list) -> int:
        """Count records matching domain."""
        return self.execute(model, "search_count", domain)

    # Inventory-specific helper methods

    def get_products(
        self,
        domain: Optional[list] = None,
        fields: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> list[dict]:
        """Get product records."""
        domain = domain or [("type", "in", ["product", "consu"])]
        fields = fields or [
            "id", "name", "default_code", "categ_id", "type",
            "qty_available", "virtual_available", "incoming_qty",
            "outgoing_qty", "reordering_min_qty", "reordering_max_qty",
            "standard_price", "list_price"
        ]
        return self.search_read("product.product", domain, fields, limit)

    def get_stock_quants(
        self,
        product_ids: Optional[list[int]] = None,
        location_ids: Optional[list[int]] = None
    ) -> list[dict]:
        """Get stock quant records (actual inventory quantities)."""
        domain = [("quantity", "!=", 0)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if location_ids:
            domain.append(("location_id", "in", location_ids))

        return self.search_read(
            "stock.quant",
            domain,
            ["product_id", "location_id", "quantity", "reserved_quantity", "lot_id"]
        )

    def get_stock_moves(
        self,
        product_ids: Optional[list[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        state: str = "done"
    ) -> list[dict]:
        """Get stock move records for historical analysis."""
        domain = [("state", "=", state)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))
        if date_from:
            domain.append(("date", ">=", date_from))
        if date_to:
            domain.append(("date", "<=", date_to))

        return self.search_read(
            "stock.move",
            domain,
            [
                "product_id", "product_uom_qty", "date",
                "location_id", "location_dest_id", "state",
                "picking_type_id", "origin"
            ],
            order="date asc"
        )

    def get_reorder_rules(
        self,
        product_ids: Optional[list[int]] = None
    ) -> list[dict]:
        """Get reordering rules (min/max stock rules)."""
        domain = [("active", "=", True)]
        if product_ids:
            domain.append(("product_id", "in", product_ids))

        return self.search_read(
            "stock.warehouse.orderpoint",
            domain,
            [
                "product_id", "warehouse_id", "location_id",
                "product_min_qty", "product_max_qty", "qty_multiple",
                "qty_on_hand", "qty_forecast"
            ]
        )

    def get_stock_locations(
        self,
        usage: Optional[str] = "internal"
    ) -> list[dict]:
        """Get stock locations."""
        domain = []
        if usage:
            domain.append(("usage", "=", usage))

        return self.search_read(
            "stock.location",
            domain,
            ["id", "name", "complete_name", "usage", "warehouse_id"]
        )

    def get_product_categories(self) -> list[dict]:
        """Get product categories."""
        return self.search_read(
            "product.category",
            [],
            ["id", "name", "complete_name", "parent_id"]
        )
