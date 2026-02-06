"""
Stock tools - get_stock_levels, get_reorder_alerts, get_stock_summary, get_reorder_rules
"""

import json
from typing import Any
from dataclasses import asdict
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient
from ..analysis import StockLevelAnalyzer


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


def handle_get_reorder_rules(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get minimum stock levels (reorder points) for products."""
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


def handle_get_stock_levels(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get current stock levels for products."""
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


def handle_get_reorder_alerts(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get products that need reordering."""
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


def handle_get_stock_summary(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get summary statistics of stock levels."""
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
