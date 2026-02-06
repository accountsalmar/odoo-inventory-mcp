"""
Forecast tools - get_stock_forecast, forecast_demand, get_forecast_summary
"""

import json
from datetime import datetime, timedelta
from typing import Any
from dataclasses import asdict
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient
from ..config import DEFAULT_LOCATION_ID
from ..analysis import DemandForecaster
from ..analysis.forecasting import ForecastMethod


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


def handle_get_stock_forecast(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get pending stock forecast for products."""
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


def handle_forecast_demand(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Forecast future demand for products using time series analysis."""
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


def handle_get_forecast_summary(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get summary of demand forecasts."""
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
