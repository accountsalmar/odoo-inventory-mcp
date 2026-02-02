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

        # Stock Level Tools
        if name == "get_stock_levels":
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
