"""
MCP Server for Odoo Inventory Analysis.

This server exposes inventory analysis tools via the Model Context Protocol.
Supports both stdio (local) and HTTP/SSE (remote) transports.
"""

import asyncio
import json
import os
from typing import Any
from dataclasses import asdict

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
)

from .odoo_client import OdooClient, OdooConfig
from .analysis import (
    StockLevelAnalyzer,
    DemandForecaster,
    ABCXYZAnalyzer,
    TurnoverAnalyzer,
)
from .analysis.forecasting import ForecastMethod


# Initialize MCP server
app = Server("inventory-analysis")

# Default WH/Stock location ID
DEFAULT_LOCATION_ID = 8


def get_odoo_client() -> OdooClient:
    """Create and connect Odoo client from environment variables."""
    config = OdooConfig(
        url=os.environ.get("ODOO_URL", "https://duracubeonline.com.au").rstrip("/"),
        database=os.environ.get("ODOO_DB", "live"),
        username=os.environ.get("ODOO_USERNAME", "accounting@qagroup.com.au"),
        api_key=os.environ.get("ODOO_API_KEY", ""),
    )
    client = OdooClient(config)
    client.connect()
    return client


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


# Define available tools
@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available inventory analysis tools."""
    return [
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


# Tool implementations
@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Handle tool calls."""
    try:
        client = get_odoo_client()

        # Search Tools
        if name == "search_categories":
            search_name = arguments.get("name", "")
            categories = client.search_read(
                'product.category',
                [('name', 'ilike', search_name)],
                ['id', 'name', 'complete_name', 'parent_id'],
                limit=50
            )
            results = []
            for cat in categories:
                results.append({
                    'id': cat['id'],
                    'name': cat['name'],
                    'full_path': cat.get('complete_name', cat['name']),
                    'parent': cat['parent_id'][1] if cat.get('parent_id') else None
                })
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(results, indent=2)
                )]
            )

        elif name == "search_products":
            search_name = arguments.get("name")
            product_id = arguments.get("product_id")
            category_name = arguments.get("category_name")

            # Build domain based on search criteria
            domain = [('type', '=', 'product')]

            if product_id:
                # Search by ID (exact match)
                domain.append(('id', '=', product_id))
            elif search_name:
                # Search by name or code (partial match)
                domain.insert(0, '|')
                domain.insert(1, ('name', 'ilike', search_name))
                domain.insert(2, ('default_code', 'ilike', search_name))

            # If category name provided, find category first
            if category_name:
                categories = client.search_read(
                    'product.category',
                    [('complete_name', 'ilike', category_name)],
                    ['id'],
                    limit=10
                )
                if categories:
                    cat_ids = [c['id'] for c in categories]
                    domain.append(('categ_id', 'child_of', cat_ids))

            products = client.search_read(
                'product.product',
                domain,
                ['id', 'name', 'default_code', 'categ_id', 'qty_available', 'virtual_available', 'minimum', 'pending_forecast', 'require'],
                limit=50
            )
            results = []
            for prod in products:
                results.append({
                    'id': prod['id'],
                    'name': prod['name'],
                    'code': prod.get('default_code') or 'N/A',
                    'category': prod['categ_id'][1] if prod.get('categ_id') else None,
                    'on_hand': prod.get('qty_available', 0),
                    'forecasted': prod.get('virtual_available', 0),
                    'minimum': prod.get('minimum', 0),
                    'pending_forecast': prod.get('pending_forecast', 0),
                    'require': prod.get('require', 0)
                })
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(results, indent=2)
                )]
            )

        elif name == "get_products_by_category":
            category_name = arguments.get("category_name", "")
            include_subcategories = arguments.get("include_subcategories", True)

            # Find category by name
            categories = client.search_read(
                'product.category',
                [('complete_name', 'ilike', category_name)],
                ['id', 'name', 'complete_name'],
                limit=10
            )

            if not categories:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=json.dumps({"error": f"No category found matching '{category_name}'"}, indent=2)
                    )]
                )

            # Use the first matching category
            category = categories[0]
            cat_id = category['id']

            # Get products
            if include_subcategories:
                product_domain = [('categ_id', 'child_of', cat_id), ('type', '=', 'product')]
            else:
                product_domain = [('categ_id', '=', cat_id), ('type', '=', 'product')]

            products = client.search_read(
                'product.product',
                product_domain,
                ['id', 'name', 'default_code', 'categ_id', 'qty_available', 'virtual_available', 'incoming_qty', 'outgoing_qty', 'minimum', 'pending_forecast', 'require'],
                order='default_code'
            )

            results = {
                'category': {
                    'id': category['id'],
                    'name': category['name'],
                    'full_path': category.get('complete_name', category['name'])
                },
                'product_count': len(products),
                'products': []
            }

            for prod in products:
                results['products'].append({
                    'id': prod['id'],
                    'name': prod['name'],
                    'code': prod.get('default_code') or 'N/A',
                    'on_hand': prod.get('qty_available', 0),
                    'forecasted': prod.get('virtual_available', 0),
                    'incoming': prod.get('incoming_qty', 0),
                    'outgoing': prod.get('outgoing_qty', 0),
                    'minimum': prod.get('minimum', 0),
                    'pending_forecast': prod.get('pending_forecast', 0),
                    'require': prod.get('require', 0)
                })

            # Add summary
            results['summary'] = {
                'total_on_hand': sum(p['on_hand'] for p in results['products']),
                'total_forecasted': sum(p['forecasted'] for p in results['products']),
                'total_incoming': sum(p['incoming'] for p in results['products']),
                'total_outgoing': sum(p['outgoing'] for p in results['products']),
                'total_minimum': sum(p['minimum'] for p in results['products']),
                'total_pending_forecast': sum(p['pending_forecast'] for p in results['products']),
                'total_require': sum(p['require'] for p in results['products'])
            }

            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(results, indent=2)
                )]
            )

        elif name == "get_reorder_rules":
            product_name = arguments.get("product_name")
            category_name = arguments.get("category_name")
            only_below_minimum = arguments.get("only_below_minimum", False)

            # Build domain for orderpoints
            orderpoint_domain = []

            # Get product IDs if filtering by name or category
            product_ids = None
            if product_name or category_name:
                product_domain = [('type', '=', 'product')]
                if product_name:
                    product_domain.append('|')
                    product_domain.append(('name', 'ilike', product_name))
                    product_domain.append(('default_code', 'ilike', product_name))
                if category_name:
                    categories = client.search_read(
                        'product.category',
                        [('complete_name', 'ilike', category_name)],
                        ['id'],
                        limit=10
                    )
                    if categories:
                        cat_ids = [c['id'] for c in categories]
                        product_domain.append(('categ_id', 'child_of', cat_ids))

                products = client.search_read(
                    'product.product',
                    product_domain,
                    ['id'],
                    limit=200
                )
                product_ids = [p['id'] for p in products]
                if product_ids:
                    orderpoint_domain.append(('product_id', 'in', product_ids))

            # Get reorder rules (orderpoints)
            orderpoints = client.search_read(
                'stock.warehouse.orderpoint',
                orderpoint_domain,
                ['product_id', 'product_min_qty', 'product_max_qty', 'qty_to_order', 'trigger', 'location_id'],
                limit=200
            )

            # Get current stock for these products
            op_product_ids = list(set([op['product_id'][0] for op in orderpoints if op.get('product_id')]))

            products_data = {}
            if op_product_ids:
                products = client.search_read(
                    'product.product',
                    [('id', 'in', op_product_ids)],
                    ['id', 'name', 'default_code', 'qty_available', 'virtual_available']
                )
                products_data = {p['id']: p for p in products}

            results = []
            for op in orderpoints:
                if not op.get('product_id'):
                    continue

                prod_id = op['product_id'][0]
                prod = products_data.get(prod_id, {})
                on_hand = prod.get('qty_available', 0)
                min_qty = op.get('product_min_qty', 0)

                # Skip if not below minimum and filter is enabled
                if only_below_minimum and on_hand >= min_qty:
                    continue

                results.append({
                    'product_id': prod_id,
                    'product_name': op['product_id'][1],
                    'product_code': prod.get('default_code') or 'N/A',
                    'on_hand': on_hand,
                    'forecasted': prod.get('virtual_available', 0),
                    'min_qty': min_qty,
                    'max_qty': op.get('product_max_qty', 0),
                    'qty_to_order': op.get('qty_to_order', 0),
                    'trigger': op.get('trigger', 'auto'),
                    'location': op['location_id'][1] if op.get('location_id') else None,
                    'below_minimum': on_hand < min_qty,
                    'shortage': max(0, min_qty - on_hand)
                })

            # Sort by shortage (most critical first)
            results.sort(key=lambda x: x['shortage'], reverse=True)

            summary = {
                'total_rules': len(results),
                'below_minimum_count': sum(1 for r in results if r['below_minimum']),
                'total_shortage': sum(r['shortage'] for r in results)
            }

            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps({'summary': summary, 'reorder_rules': results}, indent=2)
                )]
            )

        elif name == "get_stock_forecast":
            from datetime import datetime, timedelta

            product_name = arguments.get("product_name")
            category_name = arguments.get("category_name")
            weeks = min(max(arguments.get("weeks", 4), 1), 12)  # 1-12 weeks

            # Get products
            product_domain = [('type', '=', 'product')]
            if product_name:
                product_domain.append('|')
                product_domain.append(('name', 'ilike', product_name))
                product_domain.append(('default_code', 'ilike', product_name))
            if category_name:
                categories = client.search_read(
                    'product.category',
                    [('complete_name', 'ilike', category_name)],
                    ['id'],
                    limit=10
                )
                if categories:
                    cat_ids = [c['id'] for c in categories]
                    product_domain.append(('categ_id', 'child_of', cat_ids))

            products = client.search_read(
                'product.product',
                product_domain,
                ['id', 'name', 'default_code', 'qty_available'],
                limit=100
            )

            if not products:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=json.dumps({"error": "No products found matching criteria"}, indent=2)
                    )]
                )

            product_ids = [p['id'] for p in products]
            products_dict = {p['id']: p for p in products}

            today = datetime.now().date()

            # Initialize results
            results = {
                'forecast_period': f"{today} to {today + timedelta(weeks=weeks)}",
                'weeks': weeks,
                'products': []
            }

            for prod_id, prod in products_dict.items():
                product_forecast = {
                    'product_id': prod_id,
                    'name': prod['name'],
                    'code': prod.get('default_code') or 'N/A',
                    'current_on_hand': prod.get('qty_available', 0),
                    'weekly_forecast': []
                }

                running_stock = prod.get('qty_available', 0)

                for week in range(1, weeks + 1):
                    week_start = today + timedelta(days=(week-1)*7)
                    week_end = today + timedelta(days=week*7)

                    # Get incoming moves for this week
                    incoming = client.search_read(
                        'stock.move',
                        [
                            ('product_id', '=', prod_id),
                            ('state', 'in', ['assigned', 'confirmed', 'waiting']),
                            ('location_dest_id', '=', DEFAULT_LOCATION_ID),
                            ('date', '>=', week_start.strftime('%Y-%m-%d 00:00:00')),
                            ('date', '<=', week_end.strftime('%Y-%m-%d 23:59:59'))
                        ],
                        ['product_uom_qty']
                    )

                    # Get outgoing moves for this week
                    outgoing = client.search_read(
                        'stock.move',
                        [
                            ('product_id', '=', prod_id),
                            ('state', 'in', ['assigned', 'confirmed', 'waiting']),
                            ('location_id', '=', DEFAULT_LOCATION_ID),
                            ('date', '>=', week_start.strftime('%Y-%m-%d 00:00:00')),
                            ('date', '<=', week_end.strftime('%Y-%m-%d 23:59:59'))
                        ],
                        ['product_uom_qty']
                    )

                    week_incoming = sum(m['product_uom_qty'] for m in incoming)
                    week_outgoing = sum(m['product_uom_qty'] for m in outgoing)
                    running_stock = running_stock + week_incoming - week_outgoing

                    product_forecast['weekly_forecast'].append({
                        'week': week,
                        'period': f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}",
                        'incoming': week_incoming,
                        'outgoing': week_outgoing,
                        'ending_stock': running_stock
                    })

                product_forecast['final_stock'] = running_stock
                product_forecast['total_incoming'] = sum(w['incoming'] for w in product_forecast['weekly_forecast'])
                product_forecast['total_outgoing'] = sum(w['outgoing'] for w in product_forecast['weekly_forecast'])

                results['products'].append(product_forecast)

            # Add summary
            results['summary'] = {
                'total_products': len(results['products']),
                'total_current_stock': sum(p['current_on_hand'] for p in results['products']),
                'total_final_stock': sum(p['final_stock'] for p in results['products']),
                'total_incoming': sum(p['total_incoming'] for p in results['products']),
                'total_outgoing': sum(p['total_outgoing'] for p in results['products'])
            }

            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(results, indent=2)
                )]
            )

        # Stock Level Tools
        elif name == "get_stock_levels":
            analyzer = StockLevelAnalyzer(client)
            results = analyzer.get_stock_levels(
                product_ids=arguments.get("product_ids"),
                category_ids=arguments.get("category_ids"),
                warehouse_id=arguments.get("warehouse_id"),
                include_zero_stock=arguments.get("include_zero_stock", False)
            )
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(serialize_results(results), indent=2)
                )]
            )

        elif name == "get_reorder_alerts":
            analyzer = StockLevelAnalyzer(client)
            results = analyzer.get_reorder_alerts(
                threshold_days=arguments.get("threshold_days", 7),
                warehouse_id=arguments.get("warehouse_id")
            )
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(serialize_results(results), indent=2)
                )]
            )

        elif name == "get_stock_summary":
            analyzer = StockLevelAnalyzer(client)
            summary = analyzer.get_stock_summary(
                warehouse_id=arguments.get("warehouse_id")
            )
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(summary, indent=2)
                )]
            )

        # Forecasting Tools
        elif name == "forecast_demand":
            forecaster = DemandForecaster(client)
            method_str = arguments.get("method", "auto")
            method = ForecastMethod(method_str)

            results = forecaster.forecast_demand(
                product_ids=arguments.get("product_ids"),
                periods=arguments.get("periods", 30),
                period_type=arguments.get("period_type", "day"),
                method=method,
                historical_days=arguments.get("historical_days", 365)
            )
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(serialize_results(results), indent=2)
                )]
            )

        elif name == "get_forecast_summary":
            forecaster = DemandForecaster(client)
            results = forecaster.forecast_demand(
                product_ids=arguments.get("product_ids"),
                periods=arguments.get("periods", 30),
                period_type=arguments.get("period_type", "day")
            )
            summary = forecaster.get_forecast_summary(results)
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(summary, indent=2)
                )]
            )

        # ABC/XYZ Tools
        elif name == "analyze_abc_xyz":
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

        elif name == "get_abc_xyz_summary":
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
        elif name == "analyze_turnover":
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

        elif name == "analyze_aging":
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

        elif name == "get_turnover_summary":
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

        elif name == "get_aging_summary":
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

        elif name == "get_slow_moving_items":
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

        elif name == "get_high_risk_aging_items":
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

        else:
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Unknown tool: {name}"
                )],
                isError=True
            )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )],
            isError=True
        )


async def run_stdio():
    """Run the MCP server with stdio transport (for local use)."""
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


async def run_sse(host: str = "0.0.0.0", port: int = 8000):
    """Run the MCP server with SSE transport (for remote use)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse, PlainTextResponse
    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def health_check(request):
        return JSONResponse({"status": "healthy", "service": "inventory-analysis-mcp"})

    async def root(request):
        return PlainTextResponse("Odoo Inventory Analysis MCP Server is running. Connect via /sse endpoint.")

    starlette_app = Starlette(
        debug=False,
        routes=[
            Route("/", root),
            Route("/health", health_check),
            Route("/sse", handle_sse),
            Mount("/messages/", routes=[Route("/", handle_messages, methods=["POST"])]),
        ],
    )

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    """Main entry point - determines transport based on environment."""
    import sys

    # Check if PORT is set (Railway sets this) or MCP_TRANSPORT is sse
    port = os.environ.get("PORT")
    if port or os.environ.get("MCP_TRANSPORT", "stdio") == "sse":
        port = int(port or 8000)
        host = os.environ.get("HOST", "0.0.0.0")
        print(f"Starting MCP server with SSE transport on {host}:{port}")
        asyncio.run(run_sse(host=host, port=port))
    else:
        # Default to stdio for local use
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
