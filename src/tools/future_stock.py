"""
Future stock alert tools - get_future_stock_alert
"""

import json
from datetime import datetime, timedelta
from typing import Any
from mcp.types import TextContent, CallToolResult

from ..odoo_client import OdooClient
from ..config import DEFAULT_LOCATION_ID


def handle_get_future_stock_alert(client: OdooClient, arguments: dict[str, Any]) -> CallToolResult:
    """
    Get low stock alerts for a future date considering lead time.
    Shows which products will have stock below threshold on the target date,
    and when to place orders to avoid stockouts.
    """
    target_date_str = arguments.get("target_date")
    threshold = arguments.get("threshold", 50)
    category_name = arguments.get("category_name")
    product_name = arguments.get("product_name")

    # Parse target date
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": "Invalid date format. Use YYYY-MM-DD (e.g., '2025-07-26')"}, indent=2)
            )]
        )

    today = datetime.now().date()
    if target_date <= today:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": "Target date must be in the future"}, indent=2)
            )]
        )

    days_until_target = (target_date - today).days

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

    # Get products with stored fields
    products_basic = client.search_read(
        'product.product',
        product_domain,
        ['id', 'name', 'default_code', 'product_tmpl_id', 'qty_available', 'minimum'],
        limit=500
    )

    if not products_basic:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": "No products found matching criteria"}, indent=2)
            )]
        )

    # Get computed fields (pending_forecast, require)
    product_ids = [p['id'] for p in products_basic]
    computed_data = client.read(
        'product.product',
        product_ids,
        ['id', 'pending_forecast', 'require']
    )
    products_computed = {p['id']: p for p in computed_data}

    # Get product template IDs for lead time lookup
    product_tmpl_ids = [p['product_tmpl_id'][0] for p in products_basic if p.get('product_tmpl_id')]
    product_by_tmpl = {}
    for p in products_basic:
        if p.get('product_tmpl_id'):
            product_by_tmpl[p['product_tmpl_id'][0]] = p

    # Get supplier info for lead times (top supplier only)
    supplier_infos = client.search_read(
        'product.supplierinfo',
        [('product_tmpl_id', 'in', product_tmpl_ids)],
        ['product_tmpl_id', 'partner_id', 'delay', 'sequence'],
        order='product_tmpl_id, sequence, id'
    )

    # Group by product template and take only the first (top) supplier
    supplier_by_tmpl = {}
    for si in supplier_infos:
        tmpl_id = si['product_tmpl_id'][0]
        if tmpl_id not in supplier_by_tmpl:
            supplier_by_tmpl[tmpl_id] = si

    # Get scheduled moves (incoming and outgoing) up to target date
    target_date_end = target_date.strftime('%Y-%m-%d 23:59:59')
    today_start = today.strftime('%Y-%m-%d 00:00:00')

    # Incoming moves to WH/Stock
    incoming_moves = client.search_read(
        'stock.move',
        [
            ('product_id', 'in', product_ids),
            ('state', 'in', ['assigned', 'confirmed', 'waiting']),
            ('location_dest_id', '=', DEFAULT_LOCATION_ID),
            ('date', '>=', today_start),
            ('date', '<=', target_date_end)
        ],
        ['product_id', 'product_uom_qty', 'date']
    )

    # Outgoing moves from WH/Stock
    outgoing_moves = client.search_read(
        'stock.move',
        [
            ('product_id', 'in', product_ids),
            ('state', 'in', ['assigned', 'confirmed', 'waiting']),
            ('location_id', '=', DEFAULT_LOCATION_ID),
            ('date', '>=', today_start),
            ('date', '<=', target_date_end)
        ],
        ['product_id', 'product_uom_qty', 'date']
    )

    # Aggregate moves by product
    incoming_by_product = {}
    for move in incoming_moves:
        pid = move['product_id'][0]
        incoming_by_product[pid] = incoming_by_product.get(pid, 0) + move['product_uom_qty']

    outgoing_by_product = {}
    for move in outgoing_moves:
        pid = move['product_id'][0]
        outgoing_by_product[pid] = outgoing_by_product.get(pid, 0) + move['product_uom_qty']

    # Build results
    low_stock_alerts = []

    for prod in products_basic:
        prod_id = prod['id']
        tmpl_id = prod.get('product_tmpl_id', [None])[0]
        computed = products_computed.get(prod_id, {})
        supplier = supplier_by_tmpl.get(tmpl_id, {}) if tmpl_id else {}

        current_stock = prod.get('qty_available', 0)
        incoming = incoming_by_product.get(prod_id, 0)
        outgoing = outgoing_by_product.get(prod_id, 0)

        # Projected stock on target date
        projected_stock = current_stock + incoming - outgoing

        # Get lead time and minimum
        lead_time_days = supplier.get('delay', 0) if supplier else 0
        minimum = prod.get('minimum', 0)
        pending_forecast = computed.get('pending_forecast', 0)
        require = computed.get('require', 0)
        supplier_name = supplier.get('partner_id', [None, 'No supplier'])[1] if supplier else 'No supplier'

        # Check if projected stock is below threshold
        if projected_stock <= threshold:
            # Calculate order-by date
            if lead_time_days > 0:
                order_by_date = target_date - timedelta(days=lead_time_days)
                order_by_date_str = order_by_date.strftime('%Y-%m-%d')

                # Check if it's still possible to order in time
                if order_by_date < today:
                    order_status = "TOO LATE - Lead time exceeded"
                    days_late = (today - order_by_date).days
                    order_recommendation = f"Should have ordered {days_late} days ago"
                elif order_by_date == today:
                    order_status = "ORDER TODAY"
                    order_recommendation = "Place order immediately to receive by target date"
                else:
                    days_until_order = (order_by_date - today).days
                    order_status = "OK"
                    order_recommendation = f"Place order within {days_until_order} days"
            else:
                order_by_date_str = "N/A"
                order_status = "NO LEAD TIME"
                order_recommendation = "No supplier lead time configured"

            # Calculate suggested order quantity
            shortage = threshold - projected_stock
            suggested_qty = max(shortage, minimum - projected_stock) if minimum > projected_stock else shortage

            low_stock_alerts.append({
                'product_id': prod_id,
                'name': prod['name'],
                'code': prod.get('default_code') or 'N/A',
                'current_stock': current_stock,
                'incoming_by_target': incoming,
                'outgoing_by_target': outgoing,
                'projected_stock': round(projected_stock, 2),
                'minimum': minimum,
                'pending_forecast': pending_forecast,
                'threshold': threshold,
                'shortage': round(max(0, threshold - projected_stock), 2),
                'supplier': supplier_name,
                'lead_time_days': lead_time_days,
                'order_by_date': order_by_date_str,
                'order_status': order_status,
                'order_recommendation': order_recommendation,
                'suggested_order_qty': round(max(0, suggested_qty), 2)
            })

    # Sort by projected stock (lowest first - most critical)
    low_stock_alerts.sort(key=lambda x: x['projected_stock'])

    summary = {
        'target_date': target_date_str,
        'days_until_target': days_until_target,
        'threshold': threshold,
        'total_products_checked': len(products_basic),
        'low_stock_count': len(low_stock_alerts),
        'critical_count': sum(1 for a in low_stock_alerts if a['order_status'] == 'TOO LATE - Lead time exceeded'),
        'order_today_count': sum(1 for a in low_stock_alerts if a['order_status'] == 'ORDER TODAY'),
        'ok_count': sum(1 for a in low_stock_alerts if a['order_status'] == 'OK')
    }

    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps({
                'summary': summary,
                'low_stock_alerts': low_stock_alerts
            }, indent=2)
        )]
    )
