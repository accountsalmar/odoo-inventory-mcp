"""
Lead time tools - get_lead_time
"""

import json
from typing import Any
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient


def handle_get_lead_time(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """Get supplier lead time for products."""
    product_name = arguments.get("product_name")
    category_name = arguments.get("category_name")

    # Build domain for products
    product_domain = [('type', '=', 'product')]

    if product_name:
        product_domain.insert(0, '|')
        product_domain.insert(1, ('name', 'ilike', product_name))
        product_domain.insert(2, ('default_code', 'ilike', product_name))

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

    # Get products
    products = client.search_read(
        'product.product',
        product_domain,
        ['id', 'name', 'default_code', 'product_tmpl_id'],
        limit=200
    )

    if not products:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": "No products found matching criteria"}, indent=2)
            )]
        )

    # Get product template IDs (supplier info is linked to template)
    product_tmpl_ids = [p['product_tmpl_id'][0] for p in products if p.get('product_tmpl_id')]
    product_by_tmpl = {p['product_tmpl_id'][0]: p for p in products if p.get('product_tmpl_id')}

    # Get supplier info for these products (ordered by sequence to get top supplier first)
    supplier_infos = client.search_read(
        'product.supplierinfo',
        [('product_tmpl_id', 'in', product_tmpl_ids)],
        ['product_tmpl_id', 'partner_id', 'delay', 'min_qty', 'price', 'sequence'],
        order='product_tmpl_id, sequence, id'
    )

    # Group by product template and take only the first (top) supplier
    supplier_by_tmpl = {}
    for si in supplier_infos:
        tmpl_id = si['product_tmpl_id'][0]
        if tmpl_id not in supplier_by_tmpl:
            supplier_by_tmpl[tmpl_id] = si

    # Build results
    results = []
    for tmpl_id, prod in product_by_tmpl.items():
        supplier = supplier_by_tmpl.get(tmpl_id)
        results.append({
            'product_id': prod['id'],
            'name': prod['name'],
            'code': prod.get('default_code') or 'N/A',
            'supplier': supplier['partner_id'][1] if supplier and supplier.get('partner_id') else 'No supplier',
            'lead_time_days': supplier.get('delay', 0) if supplier else 0,
            'min_qty': supplier.get('min_qty', 0) if supplier else 0,
            'price': supplier.get('price', 0) if supplier else 0
        })

    # Sort by lead time (highest first to show longest lead times)
    results.sort(key=lambda x: x['lead_time_days'], reverse=True)

    summary = {
        'total_products': len(results),
        'products_with_supplier': sum(1 for r in results if r['supplier'] != 'No supplier'),
        'products_without_supplier': sum(1 for r in results if r['supplier'] == 'No supplier'),
        'avg_lead_time_days': round(sum(r['lead_time_days'] for r in results) / len(results), 1) if results else 0,
        'max_lead_time_days': max((r['lead_time_days'] for r in results), default=0),
        'min_lead_time_days': min((r['lead_time_days'] for r in results if r['lead_time_days'] > 0), default=0)
    }

    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps({'summary': summary, 'products': results}, indent=2)
        )]
    )
