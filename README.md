# Inventory Analysis MCP Server

An MCP (Model Context Protocol) server that connects to Odoo ERP to provide comprehensive inventory analysis, forecasting, and reporting capabilities.

## Features

### 1. Stock Levels & Reorder Points
- Current stock levels with status classification (out of stock, critical, low, normal, overstock)
- Reorder alerts based on stock levels and reorder rules
- Days of stock calculations
- Stock summary statistics

### 2. Demand Forecasting
- Multiple forecasting methods:
  - Moving Average
  - Exponential Smoothing
  - Linear Regression
  - Holt-Winters (for seasonal data)
  - Auto-selection (best method based on data)
- Trend detection (increasing, decreasing, stable)
- Seasonality detection
- Confidence intervals for predictions
- Accuracy metrics (MAE, RMSE, MAPE)

### 3. ABC/XYZ Analysis
- **ABC Classification** (by annual consumption value):
  - A: High value items (~20% of items, ~80% of value)
  - B: Medium value items (~30% of items, ~15% of value)
  - C: Low value items (~50% of items, ~5% of value)
- **XYZ Classification** (by demand variability):
  - X: Stable demand (CV < 0.5)
  - Y: Variable demand (0.5 <= CV < 1.0)
  - Z: Highly unpredictable demand (CV >= 1.0)
- Combined matrix with management recommendations

### 4. Turnover & Aging Reports
- **Turnover Analysis**:
  - Turnover ratio calculation
  - Days of inventory
  - Classification: fast-moving, normal, slow-moving, dead stock
- **Aging Analysis**:
  - Inventory age buckets (0-30, 31-60, 61-90, 91-180, 181-365, >365 days)
  - Obsolescence risk assessment
  - Slow-moving and high-risk item identification

## Installation

### Prerequisites
- Python 3.10 or higher
- Access to an Odoo instance (v14+)

### Setup

1. Clone or download this repository

2. Install dependencies:
   ```bash
   cd inventory_mcp_server
   pip install -e .
   ```

   Or using requirements.txt:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure Odoo connection:
   ```bash
   cp .env.example .env
   # Edit .env with your Odoo credentials
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ODOO_URL` | Odoo server URL | `https://duracubeonline.com.au` |
| `ODOO_DB` | Database name | `live` |
| `ODOO_USERNAME` | Username/email | `accounting@qagroup.com.au` |
| `ODOO_API_KEY` | API key for authentication | (required) |

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "inventory-analysis": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "C:/Users/jatin/ODOO/Claude/inventory_mcp_server",
      "env": {
        "ODOO_URL": "https://duracubeonline.com.au",
        "ODOO_DB": "live",
        "ODOO_USERNAME": "accounting@qagroup.com.au",
        "ODOO_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Or using `uv`:

```json
{
  "mcpServers": {
    "inventory-analysis": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Users/jatin/ODOO/Claude/inventory_mcp_server", "python", "-m", "src.server"],
      "env": {
        "ODOO_URL": "https://duracubeonline.com.au",
        "ODOO_DB": "live",
        "ODOO_USERNAME": "accounting@qagroup.com.au",
        "ODOO_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Available Tools

### Stock Level Tools
| Tool | Description |
|------|-------------|
| `get_stock_levels` | Get current stock levels with status classification |
| `get_reorder_alerts` | Get products needing reorder |
| `get_stock_summary` | Get summary statistics |

### Forecasting Tools
| Tool | Description |
|------|-------------|
| `forecast_demand` | Generate demand forecasts |
| `get_forecast_summary` | Get forecast summary statistics |

### ABC/XYZ Tools
| Tool | Description |
|------|-------------|
| `analyze_abc_xyz` | Perform ABC/XYZ classification |
| `get_abc_xyz_summary` | Get classification summary |

### Turnover & Aging Tools
| Tool | Description |
|------|-------------|
| `analyze_turnover` | Analyze inventory turnover |
| `analyze_aging` | Analyze inventory aging |
| `get_turnover_summary` | Get turnover summary |
| `get_aging_summary` | Get aging summary |
| `get_slow_moving_items` | Get slow-moving/dead stock |
| `get_high_risk_aging_items` | Get high obsolescence risk items |

## Usage Examples

### Get Stock Alerts
```
"Show me products that need reordering"
```

### Forecast Demand
```
"Forecast demand for the next 30 days for product ID 42"
```

### ABC/XYZ Analysis
```
"Perform ABC/XYZ analysis on my inventory"
```

### Identify Problem Stock
```
"Show me slow-moving inventory worth more than $1000"
```

## Odoo Requirements

The server requires the following Odoo modules:
- `stock` (Inventory)
- `product` (Products)

Optional for full functionality:
- `purchase` (for reorder rules)
- `sale` (for sales history)

### Required Odoo User Permissions
- Read access to:
  - `product.product`
  - `product.category`
  - `stock.quant`
  - `stock.move`
  - `stock.location`
  - `stock.warehouse.orderpoint`

## Development

### Running Tests
```bash
pytest tests/
```

### Code Formatting
```bash
black src/
ruff check src/
```

### Type Checking
```bash
mypy src/
```

## License

MIT License
