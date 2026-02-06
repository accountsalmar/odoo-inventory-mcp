"""
Tool definitions (schemas) for all MCP tools.
"""

from mcp.types import Tool


def get_tool_definitions() -> list[Tool]:
    """Return all tool definitions."""
    return [
        # Search Tools
        Tool(
            name="search_categories",
            description="Search for product categories by name. Use this to find category IDs before querying stock levels or other analysis. Returns category ID, name, and parent category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Category name to search for (partial match supported)"
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="search_products",
            description="Search for products by name or code. Use this to find product IDs before querying stock levels or other analysis. Returns product ID, name, code, category, and current stock.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Product name or code to search for (partial match supported)"
                    },
                    "product_id": {
                        "type": "integer",
                        "description": "Product ID to search for (exact match)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Optional category name to filter products"
                    }
                }
            }
        ),
        Tool(
            name="get_products_by_category",
            description="Get all products in a category by category name. Returns product list with ID, name, code, on_hand, minimum stock, pending_forecast, and require (quantity to order).",
            inputSchema={
                "type": "object",
                "properties": {
                    "category_name": {
                        "type": "string",
                        "description": "Category name to search for (e.g., 'Colour / Durasafe')"
                    },
                    "include_subcategories": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include products from subcategories"
                    }
                },
                "required": ["category_name"]
            }
        ),

        # Stock Tools
        Tool(
            name="get_reorder_rules",
            description="Get minimum stock levels (reorder points) for products. Shows product min/max quantities, reorder rules, and current stock vs minimum threshold.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Product name to search for (partial match)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Category name to filter products"
                    },
                    "only_below_minimum": {
                        "type": "boolean",
                        "default": False,
                        "description": "Only show products below minimum stock level"
                    }
                }
            }
        ),
        Tool(
            name="get_stock_levels",
            description="Get current stock levels for products with status classification (out of stock, critical, low, normal, overstock). Shows quantities on hand, incoming, outgoing, and forecast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs to filter"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs to filter"
                    },
                    "warehouse_id": {
                        "type": "integer",
                        "description": "Optional warehouse ID to filter"
                    },
                    "include_zero_stock": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include products with zero stock"
                    }
                }
            }
        ),
        Tool(
            name="get_reorder_alerts",
            description="Get products that need reordering based on stock levels and reorder rules. Returns items that are out of stock, critical, low, or have less than threshold days of stock.",
            inputSchema={
                "type": "object",
                "properties": {
                    "threshold_days": {
                        "type": "integer",
                        "default": 7,
                        "description": "Alert when days of stock is below this value"
                    },
                    "warehouse_id": {
                        "type": "integer",
                        "description": "Optional warehouse ID to filter"
                    }
                }
            }
        ),
        Tool(
            name="get_stock_summary",
            description="Get summary statistics of stock levels including total products, total value, status breakdown, and products needing reorder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "warehouse_id": {
                        "type": "integer",
                        "description": "Optional warehouse ID to filter"
                    }
                }
            }
        ),

        # Forecast Tools
        Tool(
            name="get_stock_forecast",
            description="Get pending stock forecast for products showing scheduled incoming and outgoing moves for a specific number of weeks. Shows what stock will be after pending moves.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Product name to search for (partial match)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Category name to filter products"
                    },
                    "weeks": {
                        "type": "integer",
                        "default": 4,
                        "description": "Number of weeks to forecast (1-12)"
                    }
                }
            }
        ),
        Tool(
            name="forecast_demand",
            description="Forecast future demand for products using time series analysis. Supports moving average, exponential smoothing, linear regression, and Holt-Winters methods.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs (default: all products with history, max 100)"
                    },
                    "periods": {
                        "type": "integer",
                        "default": 30,
                        "description": "Number of periods to forecast"
                    },
                    "period_type": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "default": "day",
                        "description": "Granularity of forecast"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "moving_average", "exponential_smoothing", "linear_regression", "holt_winters"],
                        "default": "auto",
                        "description": "Forecasting method (auto selects best)"
                    },
                    "historical_days": {
                        "type": "integer",
                        "default": 365,
                        "description": "Days of historical data to use"
                    }
                }
            }
        ),
        Tool(
            name="get_forecast_summary",
            description="Get summary of demand forecasts including total forecasted demand, trend breakdown, and accuracy metrics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "periods": {
                        "type": "integer",
                        "default": 30,
                        "description": "Number of periods to forecast"
                    },
                    "period_type": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "default": "day"
                    }
                }
            }
        ),

        # Lead Time Tool
        Tool(
            name="get_lead_time",
            description="Get supplier lead time for products. Lead time is the number of days from order to delivery. Returns product name, code, supplier name, and lead time in days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Product name to search for (partial match)"
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Category name to filter products (e.g., 'Durasafe', 'Laminex')"
                    }
                }
            }
        ),

        # Analysis Tools
        Tool(
            name="analyze_abc_xyz",
            description="Perform ABC/XYZ inventory classification. ABC classifies by value (A=high, B=medium, C=low). XYZ classifies by demand variability (X=stable, Y=variable, Z=unpredictable).",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    },
                    "analysis_period_days": {
                        "type": "integer",
                        "default": 365,
                        "description": "Historical period for analysis"
                    }
                }
            }
        ),
        Tool(
            name="get_abc_xyz_summary",
            description="Get summary of ABC/XYZ analysis including distribution matrices and value breakdowns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
        Tool(
            name="analyze_turnover",
            description="Analyze inventory turnover ratios. Classifies items as fast-moving (>12/year), normal (4-12/year), slow-moving (1-4/year), or dead stock (<1/year).",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    },
                    "analysis_period_days": {
                        "type": "integer",
                        "default": 365,
                        "description": "Period for COGS calculation"
                    }
                }
            }
        ),
        Tool(
            name="analyze_aging",
            description="Analyze inventory aging by tracking how long items have been in stock at WH/Stock location. Categorizes into buckets: 0-30, 31-60, 61-90, 91-180, 181-365, and over 1 year.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
        Tool(
            name="get_turnover_summary",
            description="Get summary of turnover analysis including average turnover ratio, days of inventory, and category distribution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
        Tool(
            name="get_aging_summary",
            description="Get summary of aging analysis including total inventory value, average age, aging bucket breakdown, and obsolescence risk counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of product IDs"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
        Tool(
            name="get_slow_moving_items",
            description="Get list of slow-moving and dead stock items that may need attention (discounts, liquidation, or discontinuation).",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_value": {
                        "type": "number",
                        "default": 0,
                        "description": "Minimum stock value to include"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
        Tool(
            name="get_high_risk_aging_items",
            description="Get items with high obsolescence risk based on aging analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_value": {
                        "type": "number",
                        "default": 0,
                        "description": "Minimum stock value to include"
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of category IDs"
                    }
                }
            }
        ),
    ]
