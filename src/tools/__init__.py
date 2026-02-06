"""
Tools package for MCP server.
"""

from .definitions import get_tool_definitions
from .search import handle_search_categories, handle_search_products, handle_get_products_by_category
from .stock import handle_get_stock_levels, handle_get_reorder_alerts, handle_get_stock_summary, handle_get_reorder_rules
from .forecast import handle_get_stock_forecast, handle_forecast_demand, handle_get_forecast_summary
from .lead_time import handle_get_lead_time
from .analysis import (
    handle_analyze_abc_xyz,
    handle_get_abc_xyz_summary,
    handle_analyze_turnover,
    handle_analyze_aging,
    handle_get_turnover_summary,
    handle_get_aging_summary,
    handle_get_slow_moving_items,
    handle_get_high_risk_aging_items,
)

__all__ = [
    'get_tool_definitions',
    'handle_search_categories',
    'handle_search_products',
    'handle_get_products_by_category',
    'handle_get_stock_levels',
    'handle_get_reorder_alerts',
    'handle_get_stock_summary',
    'handle_get_reorder_rules',
    'handle_get_stock_forecast',
    'handle_forecast_demand',
    'handle_get_forecast_summary',
    'handle_get_lead_time',
    'handle_analyze_abc_xyz',
    'handle_get_abc_xyz_summary',
    'handle_analyze_turnover',
    'handle_analyze_aging',
    'handle_get_turnover_summary',
    'handle_get_aging_summary',
    'handle_get_slow_moving_items',
    'handle_get_high_risk_aging_items',
]
