"""
Search tools - search_categories, search_products, get_products_by_category
"""

import json
from typing import Any
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient


def handle_search_categories(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Search for product categories by name."""
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


def handle_search_products(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Search for products by name or code."""
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

    # First get products with stored fields
    products_basic = client.search_read(
        'product.product',
        domain,
        ['id', 'name', 'default_code', 'categ_id', 'qty_available', 'virtual_available', 'minimum'],
        limit=50
    )

    # Then use read() to get computed fields (pending_forecast, require)
    product_ids = [p['id'] for p in products_basic]
    products_computed = {}
    if product_ids:
        computed_data = client.read(
            'product.product',
            product_ids,
            ['id', 'pending_forecast', 'require']
        )
        products_computed = {p['id']: p for p in computed_data}

    results = []
    for prod in products_basic:
        prod_id = prod['id']
        computed = products_computed.get(prod_id, {})
        results.append({
            'id': prod_id,
            'name': prod['name'],
            'code': prod.get('default_code') or 'N/A',
            'category': prod['categ_id'][1] if prod.get('categ_id') else None,
            'on_hand': prod.get('qty_available', 0),
            'forecasted': prod.get('virtual_available', 0),
            'minimum': prod.get('minimum', 0),
            'pending_forecast': computed.get('pending_forecast', 0),
            'require': computed.get('require', 0)
        })
    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(results, indent=2)
        )]
    )


def handle_get_products_by_category(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get all products in a category by category name."""
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

    # First get product IDs with stored fields
    products_basic = client.search_read(
        'product.product',
        product_domain,
        ['id', 'name', 'default_code', 'categ_id', 'qty_available', 'virtual_available', 'incoming_qty', 'outgoing_qty', 'minimum'],
        order='default_code'
    )

    # Then use read() to get computed fields (pending_forecast, require)
    product_ids = [p['id'] for p in products_basic]
    products_computed = {}
    if product_ids:
        computed_data = client.read(
            'product.product',
            product_ids,
            ['id', 'pending_forecast', 'require']
        )
        products_computed = {p['id']: p for p in computed_data}

    results = {
        'category': {
            'id': category['id'],
            'name': category['name'],
            'full_path': category.get('complete_name', category['name'])
        },
        'product_count': len(products_basic),
        'products': []
    }

    for prod in products_basic:
        prod_id = prod['id']
        computed = products_computed.get(prod_id, {})
        results['products'].append({
            'id': prod_id,
            'name': prod['name'],
            'code': prod.get('default_code') or 'N/A',
            'on_hand': prod.get('qty_available', 0),
            'forecasted': prod.get('virtual_available', 0),
            'incoming': prod.get('incoming_qty', 0),
            'outgoing': prod.get('outgoing_qty', 0),
            'minimum': prod.get('minimum', 0),
            'pending_forecast': computed.get('pending_forecast', 0),
            'require': computed.get('require', 0)
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
