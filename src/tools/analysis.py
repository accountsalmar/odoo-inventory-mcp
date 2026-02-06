"""
Analysis tools - ABC/XYZ, turnover, aging analysis
"""

import json
from typing import Any
from dataclasses import asdict
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient
from ..config import DEFAULT_LOCATION_ID
from ..analysis import ABCXYZAnalyzer, TurnoverAnalyzer


def serialize_results(results: list) -> list[dict]:
    """Convert dataclass results to serializable dictionaries."""
    serialized = []
    for r in results:
        if hasattr(r, "__dataclass_fields__"):
            d = asdict(r)
            # Convert Enum values to strings
            for key, value in d.items():
                if hasattr(value, "value"):
                    d[key] = value.value
            serialized.append(d)
        else:
            serialized.append(r)
    return serialized


# ABC/XYZ Tools

def handle_analyze_abc_xyz(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Perform ABC/XYZ inventory classification."""
    analyzer = ABCXYZAnalyzer(client)
    results = analyzer.analyze(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids"),
        analysis_period_days=arguments.get("analysis_period_days", 365)
    )
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(serialize_results(results), indent=2)
        )]
    )


def handle_get_abc_xyz_summary(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get summary of ABC/XYZ analysis."""
    analyzer = ABCXYZAnalyzer(client)
    results = analyzer.analyze(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids")
    )
    summary = analyzer.get_analysis_summary(results)
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(summary, indent=2)
        )]
    )


# Turnover Tools

def handle_analyze_turnover(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Analyze inventory turnover ratios."""
    analyzer = TurnoverAnalyzer(client)
    results = analyzer.analyze_turnover(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids"),
        analysis_period_days=arguments.get("analysis_period_days", 365)
    )
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(serialize_results(results), indent=2)
        )]
    )


def handle_analyze_aging(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Analyze inventory aging."""
    analyzer = TurnoverAnalyzer(client)
    results = analyzer.analyze_aging(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids"),
        location_id=DEFAULT_LOCATION_ID  # WH/Stock
    )
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(serialize_results(results), indent=2)
        )]
    )


def handle_get_turnover_summary(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get summary of turnover analysis."""
    analyzer = TurnoverAnalyzer(client)
    results = analyzer.analyze_turnover(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids")
    )
    summary = analyzer.get_turnover_summary(results)
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(summary, indent=2)
        )]
    )


def handle_get_aging_summary(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get summary of aging analysis."""
    analyzer = TurnoverAnalyzer(client)
    results = analyzer.analyze_aging(
        product_ids=arguments.get("product_ids"),
        category_ids=arguments.get("category_ids")
    )
    summary = analyzer.get_aging_summary(results)
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(summary, indent=2)
        )]
    )


def handle_get_slow_moving_items(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get list of slow-moving and dead stock items."""
    analyzer = TurnoverAnalyzer(client)
    all_results = analyzer.analyze_turnover(
        category_ids=arguments.get("category_ids")
    )
    slow_items = analyzer.get_slow_moving_items(
        all_results,
        min_value=arguments.get("min_value", 0)
    )
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(serialize_results(slow_items), indent=2)
        )]
    )


def handle_get_high_risk_aging_items(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get items with high obsolescence risk."""
    analyzer = TurnoverAnalyzer(client)
    all_results = analyzer.analyze_aging(
        category_ids=arguments.get("category_ids")
    )
    high_risk = analyzer.get_high_risk_aging(
        all_results,
        min_value=arguments.get("min_value", 0)
    )
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(serialize_results(high_risk), indent=2)
        )]
    )
