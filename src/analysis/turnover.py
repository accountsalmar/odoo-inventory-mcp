"""
Inventory Turnover and Aging Analysis.

Turnover Ratio = Cost of Goods Sold / Average Inventory Value
Days of Inventory = 365 / Turnover Ratio

Aging Analysis: Categorizes inventory by how long items have been in stock.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np

from ..odoo_client import OdooClient


class TurnoverCategory(str, Enum):
    """Turnover rate classification."""
    FAST_MOVING = "fast_moving"       # > 12 turns/year
    NORMAL = "normal"                  # 4-12 turns/year
    SLOW_MOVING = "slow_moving"        # 1-4 turns/year
    DEAD_STOCK = "dead_stock"          # < 1 turn/year or no movement


class AgingBucket(str, Enum):
    """Inventory aging buckets."""
    CURRENT = "0-30 days"
    AGING_30_60 = "31-60 days"
    AGING_60_90 = "61-90 days"
    AGING_90_180 = "91-180 days"
    AGING_180_365 = "181-365 days"
    OVER_YEAR = "Over 1 year"


@dataclass
class TurnoverResult:
    """Turnover analysis result for a product."""
    product_id: int
    product_name: str
    product_code: Optional[str]
    category: str
    current_stock_qty: float
    current_stock_value: float
    cost_of_goods_sold: float
    average_inventory_value: float
    turnover_ratio: float
    days_of_inventory: float
    turnover_category: TurnoverCategory
    last_movement_date: Optional[str]
    days_since_movement: Optional[int]


@dataclass
class AgingResult:
    """Aging analysis result for a product."""
    product_id: int
    product_name: str
    product_code: Optional[str]
    category: str
    total_qty: float
    total_value: float
    aging_breakdown: dict[str, dict]  # bucket -> {qty, value}
    oldest_stock_date: Optional[str]
    average_age_days: float
    obsolescence_risk: str  # "low", "medium", "high"


class TurnoverAnalyzer:
    """Inventory turnover and aging analyzer."""

    TURNOVER_THRESHOLDS = {
        "fast": 12,    # More than 12 turns/year
        "normal": 4,   # 4-12 turns/year
        "slow": 1      # 1-4 turns/year, below is dead stock
    }
    DEFAULT_LOCATION_ID = 8  # WH/Stock

    def __init__(self, odoo_client: OdooClient):
        self.client = odoo_client

    def analyze_turnover(
        self,
        product_ids: Optional[list[int]] = None,
        category_ids: Optional[list[int]] = None,
        analysis_period_days: int = 365,
        location_id: Optional[int] = None
    ) -> list[TurnoverResult]:
        """
        Analyze inventory turnover for products.

        Args:
            product_ids: Specific products to analyze
            category_ids: Filter by categories
            analysis_period_days: Period for COGS calculation
            location_id: Filter by location (default: WH/Stock)

        Returns:
            List of TurnoverResult sorted by turnover ratio
        """
        location_id = location_id or self.DEFAULT_LOCATION_ID
        # Get products with stock
        domain = [("type", "=", "product")]
        if product_ids:
            domain.append(("id", "in", product_ids))
        if category_ids:
            domain.append(("categ_id", "in", category_ids))

        # Note: standard_price removed due to permission restrictions
        products = self.client.search_read(
            "product.product",
            domain,
            [
                "id", "name", "default_code", "categ_id",
                "qty_available"
            ]
        )

        if not products:
            return []

        product_id_list = [p["id"] for p in products]

        # Get stock quantities from location
        quants = self.client.search_read(
            "stock.quant",
            [("location_id", "=", location_id), ("quantity", "!=", 0)],
            ["product_id", "quantity"]
        )
        quant_lookup = {}
        for q in quants:
            pid = q["product_id"][0]
            quant_lookup[pid] = quant_lookup.get(pid, 0) + q.get("quantity", 0)

        # Get COGS data (outgoing moves valued at cost)
        cogs_data = self._calculate_cogs(product_id_list, analysis_period_days, location_id)

        # Get average inventory values
        avg_inventory = self._calculate_average_inventory(
            product_id_list,
            analysis_period_days,
            location_id
        )

        # Get last movement dates
        last_movements = self._get_last_movement_dates(product_id_list, location_id)

        results = []
        today = datetime.now().date()

        for product in products:
            pid = product["id"]
            # Use location-specific quantity
            current_qty = quant_lookup.get(pid, 0)

            # Get quantity sold (COGS is qty-based since we don't have prices)
            qty_sold = cogs_data.get(pid, 0)
            avg_qty = avg_inventory.get(pid, current_qty)

            # Calculate turnover based on quantity
            if avg_qty > 0:
                turnover_ratio = qty_sold / avg_qty
            else:
                turnover_ratio = 0

            # Calculate days of inventory
            if turnover_ratio > 0:
                days_of_inventory = 365 / turnover_ratio
            else:
                days_of_inventory = 999  # Effectively infinite

            # Categorize turnover
            turnover_cat = self._categorize_turnover(turnover_ratio)

            # Last movement
            last_move = last_movements.get(pid)
            days_since = None
            if last_move:
                last_date = datetime.strptime(last_move[:10], "%Y-%m-%d").date()
                days_since = (today - last_date).days

            results.append(TurnoverResult(
                product_id=pid,
                product_name=product["name"],
                product_code=product.get("default_code"),
                category=product["categ_id"][1] if product.get("categ_id") else "Uncategorized",
                current_stock_qty=round(current_qty, 2),
                current_stock_value=0,  # Not available without price
                cost_of_goods_sold=round(qty_sold, 2),  # Actually qty sold
                average_inventory_value=round(avg_qty, 2),  # Actually avg qty
                turnover_ratio=round(turnover_ratio, 2),
                days_of_inventory=round(min(days_of_inventory, 9999), 1),
                turnover_category=turnover_cat,
                last_movement_date=last_move[:10] if last_move else None,
                days_since_movement=days_since
            ))

        # Sort by turnover ratio (ascending - slowest first for attention)
        results.sort(key=lambda x: x.turnover_ratio)

        return results

    def analyze_aging(
        self,
        product_ids: Optional[list[int]] = None,
        category_ids: Optional[list[int]] = None,
        location_id: Optional[int] = None
    ) -> list[AgingResult]:
        """
        Analyze inventory aging by tracking when stock was received.

        Args:
            product_ids: Specific products to analyze
            category_ids: Filter by categories
            location_id: Filter by location (default: WH/Stock)

        Returns:
            List of AgingResult
        """
        location_id = location_id or self.DEFAULT_LOCATION_ID

        # Get products
        domain = [("type", "=", "product")]
        if product_ids:
            domain.append(("id", "in", product_ids))
        if category_ids:
            domain.append(("categ_id", "in", category_ids))

        # Note: standard_price removed due to permission restrictions
        products = self.client.search_read(
            "product.product",
            domain,
            ["id", "name", "default_code", "categ_id", "qty_available"]
        )

        if not products:
            return []

        product_id_list = [p["id"] for p in products]

        # Get stock quants with lot info for aging from specific location
        quants = self._get_stock_quants_with_dates(product_id_list, location_id)

        results = []
        today = datetime.now()

        for product in products:
            pid = product["id"]
            product_quants = quants.get(pid, [])

            if not product_quants:
                # No quant data, skip this product
                continue

            # Calculate aging buckets (quantity-based, no value since no price access)
            aging = {bucket.value: {"qty": 0, "value": 0} for bucket in AgingBucket}
            ages = []
            oldest_date = None

            for quant in product_quants:
                qty = quant["quantity"]
                receipt_date = quant.get("in_date")

                if receipt_date:
                    receipt_dt = datetime.strptime(receipt_date[:10], "%Y-%m-%d")
                    age_days = (today - receipt_dt).days
                    ages.extend([age_days] * max(1, int(qty)))

                    if oldest_date is None or receipt_dt < oldest_date:
                        oldest_date = receipt_dt

                    bucket = self._get_aging_bucket(age_days)
                else:
                    bucket = AgingBucket.CURRENT
                    ages.extend([0] * max(1, int(qty)))

                aging[bucket.value]["qty"] += qty
                aging[bucket.value]["value"] = 0  # No value without price

            # Remove empty buckets
            aging = {k: v for k, v in aging.items() if v["qty"] > 0}

            # Round values
            for bucket in aging.values():
                bucket["qty"] = round(bucket["qty"], 2)

            total_qty = sum(b["qty"] for b in aging.values())
            avg_age = np.mean(ages) if ages else 0

            # Determine obsolescence risk
            risk = self._assess_obsolescence_risk(aging, avg_age)

            results.append(AgingResult(
                product_id=pid,
                product_name=product["name"],
                product_code=product.get("default_code"),
                category=product["categ_id"][1] if product.get("categ_id") else "Uncategorized",
                total_qty=round(total_qty, 2),
                total_value=0,  # No value without price
                aging_breakdown=aging,
                oldest_stock_date=oldest_date.strftime("%Y-%m-%d") if oldest_date else None,
                average_age_days=round(avg_age, 1),
                obsolescence_risk=risk
            ))

        # Sort by average age (oldest first)
        results.sort(key=lambda x: x.average_age_days, reverse=True)

        return results

    def _calculate_cogs(
        self,
        product_ids: list[int],
        days: int,
        location_id: int
    ) -> dict[int, float]:
        """Calculate quantity sold for products (used as turnover metric)."""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Get outgoing moves (sales) from specific location
        moves = self.client.search_read(
            "stock.move",
            [
                ("product_id", "in", product_ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id", "=", location_id),
                ("location_dest_id.usage", "=", "customer")
            ],
            ["product_id", "product_uom_qty"]
        )

        # Return quantity sold (not value, since we don't have price access)
        qty_sold = {}
        for move in moves:
            pid = move["product_id"][0]
            qty = move.get("product_uom_qty", 0)
            qty_sold[pid] = qty_sold.get(pid, 0) + qty

        return qty_sold

    def _calculate_average_inventory(
        self,
        product_ids: list[int],
        days: int,
        location_id: int
    ) -> dict[int, float]:
        """
        Calculate average inventory quantity over period.
        Simplified: uses (beginning + ending) / 2
        """
        # Get current inventory quantities from specific location
        quants = self.client.search_read(
            "stock.quant",
            [("location_id", "=", location_id), ("product_id", "in", product_ids)],
            ["product_id", "quantity"]
        )

        current_qty = {}
        for q in quants:
            pid = q["product_id"][0]
            current_qty[pid] = current_qty.get(pid, 0) + q.get("quantity", 0)

        # Get inventory changes to estimate beginning inventory
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Net change = incoming - outgoing for specific location
        incoming = self.client.search_read(
            "stock.move",
            [
                ("product_id", "in", product_ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_dest_id", "=", location_id)
            ],
            ["product_id", "product_uom_qty"]
        )

        outgoing = self.client.search_read(
            "stock.move",
            [
                ("product_id", "in", product_ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id", "=", location_id)
            ],
            ["product_id", "product_uom_qty"]
        )

        net_change = {}
        for move in incoming:
            pid = move["product_id"][0]
            net_change[pid] = net_change.get(pid, 0) + move.get("product_uom_qty", 0)
        for move in outgoing:
            pid = move["product_id"][0]
            net_change[pid] = net_change.get(pid, 0) - move.get("product_uom_qty", 0)

        # Calculate average quantities
        avg_qty = {}
        for pid in product_ids:
            end_qty = current_qty.get(pid, 0)
            change_qty = net_change.get(pid, 0)
            begin_qty = end_qty - change_qty
            avg_qty[pid] = (begin_qty + end_qty) / 2

        return avg_qty

    def _get_last_movement_dates(
        self,
        product_ids: list[int],
        location_id: int
    ) -> dict[int, str]:
        """Get the last stock movement date for each product from specific location."""
        # Get most recent move for each product from specific location
        last_dates = {}

        for pid in product_ids:
            moves = self.client.search_read(
                "stock.move",
                [
                    ("product_id", "=", pid),
                    ("state", "=", "done"),
                    "|",
                    ("location_id", "=", location_id),
                    ("location_dest_id", "=", location_id)
                ],
                ["date"],
                limit=1,
                order="date desc"
            )
            if moves:
                last_dates[pid] = moves[0]["date"]

        return last_dates

    def _get_stock_quants_with_dates(
        self,
        product_ids: list[int],
        location_id: int
    ) -> dict[int, list]:
        """Get stock quants with receipt dates for aging from specific location."""
        domain = [
            ("product_id", "in", product_ids),
            ("quantity", ">", 0),
            ("location_id", "=", location_id)
        ]

        quants = self.client.search_read(
            "stock.quant",
            domain,
            ["product_id", "quantity", "in_date", "lot_id"]
        )

        grouped = {}
        for q in quants:
            pid = q["product_id"][0]
            if pid not in grouped:
                grouped[pid] = []
            grouped[pid].append(q)

        return grouped

    def _categorize_turnover(self, ratio: float) -> TurnoverCategory:
        """Categorize turnover ratio."""
        if ratio >= self.TURNOVER_THRESHOLDS["fast"]:
            return TurnoverCategory.FAST_MOVING
        elif ratio >= self.TURNOVER_THRESHOLDS["normal"]:
            return TurnoverCategory.NORMAL
        elif ratio >= self.TURNOVER_THRESHOLDS["slow"]:
            return TurnoverCategory.SLOW_MOVING
        else:
            return TurnoverCategory.DEAD_STOCK

    def _get_aging_bucket(self, age_days: int) -> AgingBucket:
        """Determine aging bucket for given age."""
        if age_days <= 30:
            return AgingBucket.CURRENT
        elif age_days <= 60:
            return AgingBucket.AGING_30_60
        elif age_days <= 90:
            return AgingBucket.AGING_60_90
        elif age_days <= 180:
            return AgingBucket.AGING_90_180
        elif age_days <= 365:
            return AgingBucket.AGING_180_365
        else:
            return AgingBucket.OVER_YEAR

    def _assess_obsolescence_risk(
        self,
        aging: dict,
        avg_age: float
    ) -> str:
        """Assess obsolescence risk based on aging distribution."""
        # Calculate percentage of old stock
        total_value = sum(b["value"] for b in aging.values())
        if total_value == 0:
            return "low"

        old_buckets = [
            AgingBucket.AGING_90_180.value,
            AgingBucket.AGING_180_365.value,
            AgingBucket.OVER_YEAR.value
        ]
        old_value = sum(aging.get(b, {}).get("value", 0) for b in old_buckets)
        old_pct = old_value / total_value

        if old_pct > 0.5 or avg_age > 180:
            return "high"
        elif old_pct > 0.2 or avg_age > 90:
            return "medium"
        else:
            return "low"

    def get_turnover_summary(self, results: list[TurnoverResult]) -> dict:
        """Get summary of turnover analysis."""
        if not results:
            return {}

        category_counts = {cat.value: 0 for cat in TurnoverCategory}
        category_values = {cat.value: 0 for cat in TurnoverCategory}

        for r in results:
            category_counts[r.turnover_category.value] += 1
            category_values[r.turnover_category.value] += r.current_stock_value

        total_products = len(results)
        total_value = sum(r.current_stock_value for r in results)
        avg_turnover = np.mean([r.turnover_ratio for r in results])
        avg_days = np.mean([r.days_of_inventory for r in results if r.days_of_inventory < 9999])

        return {
            "total_products": total_products,
            "total_stock_value": round(total_value, 2),
            "average_turnover_ratio": round(avg_turnover, 2),
            "average_days_of_inventory": round(avg_days, 1) if avg_days else None,
            "category_distribution": {
                cat: {
                    "count": category_counts[cat],
                    "value": round(category_values[cat], 2),
                    "value_percentage": round(category_values[cat] / total_value * 100, 1) if total_value else 0
                }
                for cat in category_counts
            }
        }

    def get_aging_summary(self, results: list[AgingResult]) -> dict:
        """Get summary of aging analysis."""
        if not results:
            return {}

        bucket_totals = {bucket.value: {"qty": 0, "value": 0} for bucket in AgingBucket}
        risk_counts = {"low": 0, "medium": 0, "high": 0}

        for r in results:
            risk_counts[r.obsolescence_risk] += 1
            for bucket, data in r.aging_breakdown.items():
                bucket_totals[bucket]["qty"] += data["qty"]
                bucket_totals[bucket]["value"] += data["value"]

        total_value = sum(r.total_value for r in results)
        avg_age = np.mean([r.average_age_days for r in results])

        return {
            "total_products": len(results),
            "total_inventory_value": round(total_value, 2),
            "average_age_days": round(avg_age, 1),
            "aging_buckets": {
                bucket: {
                    "qty": round(data["qty"], 2),
                    "value": round(data["value"], 2),
                    "value_percentage": round(data["value"] / total_value * 100, 1) if total_value else 0
                }
                for bucket, data in bucket_totals.items()
                if data["qty"] > 0
            },
            "obsolescence_risk": risk_counts
        }

    def get_slow_moving_items(
        self,
        results: list[TurnoverResult],
        min_value: float = 0
    ) -> list[TurnoverResult]:
        """Get slow moving and dead stock items."""
        slow_categories = [TurnoverCategory.SLOW_MOVING, TurnoverCategory.DEAD_STOCK]
        return [
            r for r in results
            if r.turnover_category in slow_categories
            and r.current_stock_value >= min_value
        ]

    def get_high_risk_aging(
        self,
        results: list[AgingResult],
        min_value: float = 0
    ) -> list[AgingResult]:
        """Get items with high obsolescence risk."""
        return [
            r for r in results
            if r.obsolescence_risk == "high"
            and r.total_value >= min_value
        ]
