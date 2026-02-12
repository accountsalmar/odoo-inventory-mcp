"""
MCP Server for Odoo Inventory Analysis.

This server exposes inventory analysis tools via the Model Context Protocol.
Supports both stdio (local) and HTTP/SSE (remote) transports.
"""

import asyncio
import os
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult

from .config import get_odoo_client
from .tools.definitions import get_tool_definitions
from .tools.search import (
    handle_search_categories,
    handle_search_products,
    handle_get_products_by_category,
)
from .tools.stock import (
    handle_get_reorder_rules,
    handle_get_stock_levels,
    handle_get_reorder_alerts,
    handle_get_stock_summary,
)
from .tools.forecast import (
    handle_get_stock_forecast,
    handle_forecast_demand,
    handle_get_forecast_summary,
)
from .tools.lead_time import handle_get_lead_time
from .tools.future_stock import handle_get_future_stock_alert
from .tools.analysis import (
    handle_analyze_abc_xyz,
    handle_get_abc_xyz_summary,
    handle_analyze_turnover,
    handle_analyze_aging,
    handle_get_turnover_summary,
    handle_get_aging_summary,
    handle_get_slow_moving_items,
    handle_get_high_risk_aging_items,
)


# Initialize MCP server
app = Server("inventory-analysis")


# Tool handler mapping
TOOL_HANDLERS = {
    # Search tools
    "search_categories": handle_search_categories,
    "search_products": handle_search_products,
    "get_products_by_category": handle_get_products_by_category,

    # Stock tools
    "get_reorder_rules": handle_get_reorder_rules,
    "get_stock_levels": handle_get_stock_levels,
    "get_reorder_alerts": handle_get_reorder_alerts,
    "get_stock_summary": handle_get_stock_summary,

    # Forecast tools
    "get_stock_forecast": handle_get_stock_forecast,
    "forecast_demand": handle_forecast_demand,
    "get_forecast_summary": handle_get_forecast_summary,

    # Lead time tools
    "get_lead_time": handle_get_lead_time,

    # Future stock alert tools
    "get_future_stock_alert": handle_get_future_stock_alert,

    # Analysis tools
    "analyze_abc_xyz": handle_analyze_abc_xyz,
    "get_abc_xyz_summary": handle_get_abc_xyz_summary,
    "analyze_turnover": handle_analyze_turnover,
    "analyze_aging": handle_analyze_aging,
    "get_turnover_summary": handle_get_turnover_summary,
    "get_aging_summary": handle_get_aging_summary,
    "get_slow_moving_items": handle_get_slow_moving_items,
    "get_high_risk_aging_items": handle_get_high_risk_aging_items,
}


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available inventory analysis tools."""
    return get_tool_definitions()


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Handle tool calls."""
    try:
        client = get_odoo_client()

        handler = TOOL_HANDLERS.get(name)
        if handler:
            return handler(client, arguments)
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
