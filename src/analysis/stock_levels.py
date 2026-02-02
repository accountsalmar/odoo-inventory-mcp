"""
Stock Levels and Reorder Points Analysis.
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum

import pandas as pd
import numpy as np

from ..odoo_client import OdooClient


class StockStatus(str, Enum):
    """Stock status classification."""
    OUT_OF_STOCK = "out_of_stock"
    CRITICAL = "critical"
    LOW = "low"
    NORMAL = "normal"
    OVERSTOCK = "overstock"


@dataclass
class StockLevelResult:
    """Result of stock level analysis for a product."""
    product_id: int
    product_name: str
    product_code: Optional[str]
    category: str
    qty_on_hand: float
    qty_available: float
    qty_incoming: float
    qty_outgoing: float
    qty_forecast: float
    reorder_min: float
    reorder_max: float
    status: StockStatus
    days_of_stock: Optional[float]
    reorder_qty_suggested: float


class StockLevelAnalyzer:
    """Analyzer for stock levels and reorder points."""

    # Default WH/Stock location ID
    DEFAULT_LOCATION_ID = 8  # WH/Stock

    def __init__(self, odoo_client: OdooClient):
        self.client = odoo_client

    def get_stock_levels(
        self,
        product_ids: Optional[list[int]] = None,
        category_ids: Optional[list[int]] = None,
        warehouse_id: Optional[int] = None,
        location_id: Optional[int] = None,
        include_zero_stock: bool = False
    ) -> list[StockLevelResult]:
        """
        Get current stock levels for products.

        Args:
            product_ids: Filter by specific product IDs
            category_ids: Filter by product category IDs
            warehouse_id: Filter by warehouse
            location_id: Filter by specific location (default: WH/Stock = 8)
            include_zero_stock: Include products with zero stock

        Returns:
            List of StockLevelResult objects
        """
        # Use default location if not specified
        location_id = location_id or self.DEFAULT_LOCATION_ID

        # Get stock quants for the specific location
        quant_domain = [("location_id", "=", location_id), ("quantity", "!=", 0)]
        if product_ids:
            quant_domain.append(("product_id", "in", product_ids))

        quants = self.client.search_read(
            "stock.quant",
            quant_domain,
            ["product_id", "quantity", "reserved_quantity"]
        )

        # Get unique product IDs from quants
        quant_product_ids = list(set(q["product_id"][0] for q in quants))

        if not quant_product_ids and not include_zero_stock:
            return []

        # Build product domain
        domain = [("type", "=", "product")]
        if product_ids:
            domain.append(("id", "in", product_ids))
        elif quant_product_ids and not include_zero_stock:
            domain.append(("id", "in", quant_product_ids))
        if category_ids:
            domain.append(("categ_id", "in", category_ids))

        # Fetch products (avoiding standard_price due to permission issues)
        products = self.client.search_read(
            "product.product",
            domain,
            [
                "id", "name", "default_code", "categ_id",
                "qty_available", "virtual_available",
                "incoming_qty", "outgoing_qty"
            ]
        )

        if not products:
            return []

        # Build quant lookup by product_id (sum quantities for same product)
        quant_lookup = {}
        for q in quants:
            pid = q["product_id"][0]
            if pid not in quant_lookup:
                quant_lookup[pid] = {"quantity": 0, "reserved": 0}
            quant_lookup[pid]["quantity"] += q.get("quantity", 0)
            quant_lookup[pid]["reserved"] += q.get("reserved_quantity", 0)

        # Get reorder rules
        product_id_list = [p["id"] for p in products]
        reorder_rules = self._get_reorder_rules_map(product_id_list, warehouse_id)

        # Calculate average daily consumption
        consumption_rates = self._calculate_consumption_rates(product_id_list, location_id=location_id)

        results = []
        for product in products:
            pid = product["id"]
            rule = reorder_rules.get(pid, {})
            consumption = consumption_rates.get(pid, 0)

            # Use location-specific quantity from quants
            quant_data = quant_lookup.get(pid, {"quantity": 0, "reserved": 0})
            qty_on_hand = quant_data["quantity"]
            qty_available = qty_on_hand - quant_data["reserved"]

            # Skip products with zero stock if not including them
            if not include_zero_stock and qty_on_hand == 0:
                continue

            qty_forecast = qty_available + product.get("incoming_qty", 0) - product.get("outgoing_qty", 0)
            reorder_min = rule.get("product_min_qty", 0)
            reorder_max = rule.get("product_max_qty", 0)

            # Calculate status
            status = self._calculate_status(
                qty_on_hand, qty_forecast, reorder_min, reorder_max
            )

            # Calculate days of stock
            days_of_stock = None
            if consumption > 0:
                days_of_stock = round(qty_on_hand / consumption, 1)

            # Calculate suggested reorder quantity
            reorder_suggested = 0.0
            if qty_forecast < reorder_min and reorder_max > 0:
                reorder_suggested = reorder_max - qty_forecast

            results.append(StockLevelResult(
                product_id=pid,
                product_name=product["name"],
                product_code=product.get("default_code"),
                category=product["categ_id"][1] if product.get("categ_id") else "Uncategorized",
                qty_on_hand=qty_on_hand,
                qty_available=qty_available,
                qty_incoming=product.get("incoming_qty", 0),
                qty_outgoing=product.get("outgoing_qty", 0),
                qty_forecast=qty_forecast,
                reorder_min=reorder_min,
                reorder_max=reorder_max,
                status=status,
                days_of_stock=days_of_stock,
                reorder_qty_suggested=reorder_suggested
            ))

        return results

    def get_reorder_alerts(
        self,
        threshold_days: int = 7,
        warehouse_id: Optional[int] = None,
        location_id: Optional[int] = None
    ) -> list[StockLevelResult]:
        """
        Get products that need reordering.

        Args:
            threshold_days: Alert when days of stock is below this
            warehouse_id: Filter by warehouse
            location_id: Filter by location (default: WH/Stock)

        Returns:
            List of products needing reorder
        """
        all_levels = self.get_stock_levels(
            warehouse_id=warehouse_id,
            location_id=location_id,
            include_zero_stock=True
        )

        alerts = []
        for level in all_levels:
            needs_alert = (
                level.status in [StockStatus.OUT_OF_STOCK, StockStatus.CRITICAL, StockStatus.LOW]
                or (level.days_of_stock is not None and level.days_of_stock < threshold_days)
            )
            if needs_alert:
                alerts.append(level)

        # Sort by urgency (out of stock first, then by days of stock)
        def sort_key(x):
            status_priority = {
                StockStatus.OUT_OF_STOCK: 0,
                StockStatus.CRITICAL: 1,
                StockStatus.LOW: 2,
                StockStatus.NORMAL: 3,
                StockStatus.OVERSTOCK: 4
            }
            return (status_priority[x.status], x.days_of_stock or 0)

        alerts.sort(key=sort_key)
        return alerts

    def get_stock_summary(
        self,
        warehouse_id: Optional[int] = None,
        location_id: Optional[int] = None
    ) -> dict:
        """
        Get summary statistics of stock levels.

        Args:
            warehouse_id: Filter by warehouse
            location_id: Filter by location (default: WH/Stock)

        Returns:
            Dictionary with summary statistics
        """
        all_levels = self.get_stock_levels(
            warehouse_id=warehouse_id,
            location_id=location_id,
            include_zero_stock=True
        )

        if not all_levels:
            return {
                "total_products": 0,
                "total_value": 0,
                "status_breakdown": {},
                "avg_days_of_stock": 0,
                "products_needing_reorder": 0
            }

        # Calculate totals
        status_counts = {}
        days_list = []
        reorder_count = 0
        total_qty = 0

        for level in all_levels:
            # Status count
            status_counts[level.status.value] = status_counts.get(level.status.value, 0) + 1

            # Total quantity
            total_qty += level.qty_on_hand

            # Days of stock
            if level.days_of_stock is not None:
                days_list.append(level.days_of_stock)

            # Reorder count
            if level.reorder_qty_suggested > 0:
                reorder_count += 1

        return {
            "total_products": len(all_levels),
            "total_quantity": round(total_qty, 2),
            "status_breakdown": status_counts,
            "avg_days_of_stock": round(np.mean(days_list), 1) if days_list else None,
            "products_needing_reorder": reorder_count
        }

    def _get_reorder_rules_map(
        self,
        product_ids: list[int],
        warehouse_id: Optional[int] = None
    ) -> dict[int, dict]:
        """Get reorder rules mapped by product ID."""
        domain = [
            ("active", "=", True),
            ("product_id", "in", product_ids)
        ]
        if warehouse_id:
            domain.append(("warehouse_id", "=", warehouse_id))

        rules = self.client.search_read(
            "stock.warehouse.orderpoint",
            domain,
            ["product_id", "product_min_qty", "product_max_qty", "qty_multiple"]
        )

        return {
            r["product_id"][0]: r for r in rules
        }

    def _calculate_consumption_rates(
        self,
        product_ids: list[int],
        days: int = 30,
        location_id: Optional[int] = None
    ) -> dict[int, float]:
        """Calculate average daily consumption rate for products."""
        from datetime import datetime, timedelta

        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        location_id = location_id or self.DEFAULT_LOCATION_ID

        # Get outgoing moves from the specific location
        moves = self.client.search_read(
            "stock.move",
            [
                ("product_id", "in", product_ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id", "=", location_id),
                ("location_dest_id.usage", "in", ["customer", "production"])
            ],
            ["product_id", "product_uom_qty"]
        )

        # Sum quantities by product
        consumption = {}
        for move in moves:
            pid = move["product_id"][0]
            qty = move.get("product_uom_qty", 0)
            consumption[pid] = consumption.get(pid, 0) + qty

        # Convert to daily rate
        return {pid: qty / days for pid, qty in consumption.items()}

    def _calculate_status(
        self,
        qty_on_hand: float,
        qty_forecast: float,
        reorder_min: float,
        reorder_max: float
    ) -> StockStatus:
        """Determine stock status based on quantities and reorder rules."""
        if qty_on_hand <= 0:
            return StockStatus.OUT_OF_STOCK

        if reorder_min > 0:
            if qty_forecast <= 0:
                return StockStatus.CRITICAL
            elif qty_forecast < reorder_min * 0.5:
                return StockStatus.CRITICAL
            elif qty_forecast < reorder_min:
                return StockStatus.LOW
            elif reorder_max > 0 and qty_on_hand > reorder_max * 1.5:
                return StockStatus.OVERSTOCK

        return StockStatus.NORMAL
