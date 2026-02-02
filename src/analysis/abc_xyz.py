"""
ABC/XYZ Inventory Classification Analysis.

ABC Analysis: Classifies items by annual consumption value
  - A: High value (top 80% of value, ~20% of items)
  - B: Medium value (next 15% of value, ~30% of items)
  - C: Low value (remaining 5% of value, ~50% of items)

XYZ Analysis: Classifies items by demand variability
  - X: Stable demand (CV < 0.5)
  - Y: Variable demand (0.5 <= CV < 1.0)
  - Z: Highly variable demand (CV >= 1.0)
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np

from ..odoo_client import OdooClient


class ABCClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class XYZClass(str, Enum):
    X = "X"
    Y = "Y"
    Z = "Z"


@dataclass
class ABCXYZResult:
    """Result of ABC/XYZ analysis for a product."""
    product_id: int
    product_name: str
    product_code: Optional[str]
    category: str
    abc_class: ABCClass
    xyz_class: XYZClass
    combined_class: str  # e.g., "AX", "BY", "CZ"
    annual_value: float
    annual_quantity: float
    unit_cost: float
    value_percentage: float
    cumulative_percentage: float
    demand_cv: float  # Coefficient of variation
    avg_monthly_demand: float
    demand_std: float
    recommendation: str


class ABCXYZAnalyzer:
    """ABC/XYZ inventory classification analyzer."""

    # Default thresholds
    ABC_THRESHOLDS = {"A": 0.80, "B": 0.95}  # Cumulative value percentages
    XYZ_THRESHOLDS = {"X": 0.5, "Y": 1.0}    # CV thresholds
    DEFAULT_LOCATION_ID = 8  # WH/Stock

    def __init__(self, odoo_client: OdooClient):
        self.client = odoo_client

    def analyze(
        self,
        product_ids: Optional[list[int]] = None,
        category_ids: Optional[list[int]] = None,
        analysis_period_days: int = 365,
        abc_thresholds: Optional[dict] = None,
        xyz_thresholds: Optional[dict] = None,
        location_id: Optional[int] = None
    ) -> list[ABCXYZResult]:
        """
        Perform ABC/XYZ analysis on inventory.

        Args:
            product_ids: Specific products to analyze
            category_ids: Filter by categories
            analysis_period_days: Historical period for analysis
            abc_thresholds: Custom ABC thresholds {"A": 0.80, "B": 0.95}
            xyz_thresholds: Custom XYZ thresholds {"X": 0.5, "Y": 1.0}
            location_id: Filter by location (default: WH/Stock)

        Returns:
            List of ABCXYZResult sorted by value (descending)
        """
        abc_thresh = abc_thresholds or self.ABC_THRESHOLDS
        xyz_thresh = xyz_thresholds or self.XYZ_THRESHOLDS
        location_id = location_id or self.DEFAULT_LOCATION_ID

        # Get products
        domain = [("type", "=", "product")]
        if product_ids:
            domain.append(("id", "in", product_ids))
        if category_ids:
            domain.append(("categ_id", "in", category_ids))

        # Note: standard_price removed due to permission restrictions
        # ABC analysis based on consumption quantity only
        products = self.client.search_read(
            "product.product",
            domain,
            ["id", "name", "default_code", "categ_id"]
        )

        if not products:
            return []

        # Get consumption data for all products
        product_id_list = [p["id"] for p in products]
        consumption_data = self._get_consumption_data(
            product_id_list,
            analysis_period_days,
            location_id
        )

        # Calculate metrics for each product
        # Note: Using quantity-based ABC since we don't have access to standard_price
        product_metrics = []
        for product in products:
            pid = product["id"]
            cons = consumption_data.get(pid, {})

            annual_qty = cons.get("total_quantity", 0)
            # Use quantity as proxy for value since price not available
            annual_value = annual_qty

            monthly_demands = cons.get("monthly_demands", [])
            if monthly_demands:
                avg_demand = np.mean(monthly_demands)
                std_demand = np.std(monthly_demands)
                cv = std_demand / avg_demand if avg_demand > 0 else 0
            else:
                avg_demand = 0
                std_demand = 0
                cv = 0

            product_metrics.append({
                "product": product,
                "annual_value": annual_value,  # Actually quantity-based
                "annual_quantity": annual_qty,
                "unit_cost": 0,  # Not available
                "avg_monthly_demand": avg_demand,
                "demand_std": std_demand,
                "demand_cv": cv
            })

        # Sort by annual quantity (descending) for ABC classification
        product_metrics.sort(key=lambda x: x["annual_quantity"], reverse=True)

        # Calculate total value and cumulative percentages
        total_value = sum(p["annual_value"] for p in product_metrics)
        if total_value == 0:
            total_value = 1  # Avoid division by zero

        cumulative = 0
        results = []

        for pm in product_metrics:
            product = pm["product"]
            value_pct = pm["annual_value"] / total_value
            cumulative += value_pct

            # ABC Classification
            abc_class = self._classify_abc(cumulative, abc_thresh)

            # XYZ Classification
            xyz_class = self._classify_xyz(pm["demand_cv"], xyz_thresh)

            # Combined class
            combined = f"{abc_class.value}{xyz_class.value}"

            # Generate recommendation
            recommendation = self._generate_recommendation(abc_class, xyz_class)

            results.append(ABCXYZResult(
                product_id=product["id"],
                product_name=product["name"],
                product_code=product.get("default_code"),
                category=product["categ_id"][1] if product.get("categ_id") else "Uncategorized",
                abc_class=abc_class,
                xyz_class=xyz_class,
                combined_class=combined,
                annual_value=round(pm["annual_value"], 2),
                annual_quantity=round(pm["annual_quantity"], 2),
                unit_cost=round(pm["unit_cost"], 2),
                value_percentage=round(value_pct * 100, 2),
                cumulative_percentage=round(cumulative * 100, 2),
                demand_cv=round(pm["demand_cv"], 3),
                avg_monthly_demand=round(pm["avg_monthly_demand"], 2),
                demand_std=round(pm["demand_std"], 2),
                recommendation=recommendation
            ))

        return results

    def _get_consumption_data(
        self,
        product_ids: list[int],
        days: int,
        location_id: int
    ) -> dict[int, dict]:
        """Get consumption data for products over specified period."""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Get outgoing stock moves from specific location
        moves = self.client.search_read(
            "stock.move",
            [
                ("product_id", "in", product_ids),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id", "=", location_id),
                ("location_dest_id.usage", "in", ["customer", "production"])
            ],
            ["product_id", "product_uom_qty", "date"],
            order="date asc"
        )

        # Aggregate by product
        consumption = {}
        for move in moves:
            pid = move["product_id"][0]
            qty = move.get("product_uom_qty", 0)

            if pid not in consumption:
                consumption[pid] = {
                    "total_quantity": 0,
                    "moves": []
                }

            consumption[pid]["total_quantity"] += qty
            consumption[pid]["moves"].append({
                "date": move["date"],
                "quantity": qty
            })

        # Calculate monthly demands for XYZ analysis
        for pid, data in consumption.items():
            if data["moves"]:
                df = pd.DataFrame(data["moves"])
                df["date"] = pd.to_datetime(df["date"])
                df["month"] = df["date"].dt.to_period("M")
                monthly = df.groupby("month")["quantity"].sum().tolist()
                data["monthly_demands"] = monthly
            else:
                data["monthly_demands"] = []

        return consumption

    def _classify_abc(self, cumulative_pct: float, thresholds: dict) -> ABCClass:
        """Classify product into ABC category."""
        if cumulative_pct <= thresholds["A"]:
            return ABCClass.A
        elif cumulative_pct <= thresholds["B"]:
            return ABCClass.B
        else:
            return ABCClass.C

    def _classify_xyz(self, cv: float, thresholds: dict) -> XYZClass:
        """Classify product into XYZ category based on demand variability."""
        if cv < thresholds["X"]:
            return XYZClass.X
        elif cv < thresholds["Y"]:
            return XYZClass.Y
        else:
            return XYZClass.Z

    def _generate_recommendation(
        self,
        abc: ABCClass,
        xyz: XYZClass
    ) -> str:
        """Generate inventory management recommendation."""
        recommendations = {
            # AX: High value, stable demand - best candidates for JIT
            ("A", "X"): "High priority. Use JIT inventory, tight control, frequent reviews. Consider vendor-managed inventory.",
            # AY: High value, variable demand - needs buffer stock
            ("A", "Y"): "High priority. Maintain safety stock, regular forecasting, flexible supply contracts.",
            # AZ: High value, unpredictable - difficult to manage
            ("A", "Z"): "High priority but unpredictable. Higher safety stock, multiple suppliers, close monitoring.",

            # BX: Medium value, stable - moderate attention
            ("B", "X"): "Medium priority. Standard reorder point system, periodic reviews.",
            # BY: Medium value, variable
            ("B", "Y"): "Medium priority. Balance safety stock with carrying costs, regular forecasting.",
            # BZ: Medium value, unpredictable
            ("B", "Z"): "Medium priority. Consider make-to-order or higher safety stock for critical items.",

            # CX: Low value, stable - simple systems
            ("C", "X"): "Low priority. Simple min-max system, bulk ordering to reduce costs.",
            # CY: Low value, variable
            ("C", "Y"): "Low priority. Periodic ordering, may benefit from consignment.",
            # CZ: Low value, unpredictable - consider eliminating
            ("C", "Z"): "Low priority. Review necessity, consider dropping or make-to-order."
        }

        return recommendations.get((abc.value, xyz.value), "Review inventory policy.")

    def get_analysis_summary(self, results: list[ABCXYZResult]) -> dict:
        """Get summary statistics of ABC/XYZ analysis."""
        if not results:
            return {}

        # ABC distribution
        abc_counts = {"A": 0, "B": 0, "C": 0}
        abc_values = {"A": 0.0, "B": 0.0, "C": 0.0}

        # XYZ distribution
        xyz_counts = {"X": 0, "Y": 0, "Z": 0}

        # Combined matrix
        matrix = {}

        for r in results:
            abc_counts[r.abc_class.value] += 1
            abc_values[r.abc_class.value] += r.annual_value
            xyz_counts[r.xyz_class.value] += 1

            if r.combined_class not in matrix:
                matrix[r.combined_class] = {"count": 0, "value": 0}
            matrix[r.combined_class]["count"] += 1
            matrix[r.combined_class]["value"] += r.annual_value

        total_products = len(results)
        total_value = sum(r.annual_value for r in results)

        return {
            "total_products": total_products,
            "total_annual_value": round(total_value, 2),
            "abc_distribution": {
                "A": {
                    "count": abc_counts["A"],
                    "percentage": round(abc_counts["A"] / total_products * 100, 1),
                    "value": round(abc_values["A"], 2),
                    "value_percentage": round(abc_values["A"] / total_value * 100, 1) if total_value else 0
                },
                "B": {
                    "count": abc_counts["B"],
                    "percentage": round(abc_counts["B"] / total_products * 100, 1),
                    "value": round(abc_values["B"], 2),
                    "value_percentage": round(abc_values["B"] / total_value * 100, 1) if total_value else 0
                },
                "C": {
                    "count": abc_counts["C"],
                    "percentage": round(abc_counts["C"] / total_products * 100, 1),
                    "value": round(abc_values["C"], 2),
                    "value_percentage": round(abc_values["C"] / total_value * 100, 1) if total_value else 0
                }
            },
            "xyz_distribution": {
                "X": {
                    "count": xyz_counts["X"],
                    "percentage": round(xyz_counts["X"] / total_products * 100, 1)
                },
                "Y": {
                    "count": xyz_counts["Y"],
                    "percentage": round(xyz_counts["Y"] / total_products * 100, 1)
                },
                "Z": {
                    "count": xyz_counts["Z"],
                    "percentage": round(xyz_counts["Z"] / total_products * 100, 1)
                }
            },
            "combined_matrix": {
                k: {
                    "count": v["count"],
                    "value": round(v["value"], 2)
                }
                for k, v in sorted(matrix.items())
            }
        }

    def get_category_breakdown(
        self,
        results: list[ABCXYZResult]
    ) -> dict[str, list[ABCXYZResult]]:
        """Group results by combined ABC/XYZ class."""
        breakdown = {}
        for r in results:
            if r.combined_class not in breakdown:
                breakdown[r.combined_class] = []
            breakdown[r.combined_class].append(r)

        return dict(sorted(breakdown.items()))
