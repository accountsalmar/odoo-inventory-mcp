"""
Configuration and constants for the MCP server.
"""

import os
from .odoo_client import OdooClient, OdooConfig


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
