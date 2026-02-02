"""
Demand Forecasting using Time Series Analysis.
"""

from dataclasses import dataclass
from typing import Optional, Literal
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np
from scipy import stats

from ..odoo_client import OdooClient


class ForecastMethod(str, Enum):
    """Available forecasting methods."""
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    LINEAR_REGRESSION = "linear_regression"
    HOLT_WINTERS = "holt_winters"
    AUTO = "auto"  # Automatically select best method


@dataclass
class ForecastResult:
    """Result of demand forecasting for a product."""
    product_id: int
    product_name: str
    product_code: Optional[str]
    method_used: str
    forecast_periods: list[dict]  # List of {date, quantity, lower_bound, upper_bound}
    accuracy_metrics: dict  # MAE, RMSE, MAPE
    historical_avg: float
    trend: str  # "increasing", "decreasing", "stable"
    seasonality_detected: bool
    confidence_level: float


class DemandForecaster:
    """Demand forecasting for inventory planning."""

    # Default WH/Stock location ID
    DEFAULT_LOCATION_ID = 8  # WH/Stock

    def __init__(self, odoo_client: OdooClient):
        self.client = odoo_client

    def forecast_demand(
        self,
        product_ids: Optional[list[int]] = None,
        periods: int = 30,
        period_type: Literal["day", "week", "month"] = "day",
        method: ForecastMethod = ForecastMethod.AUTO,
        historical_days: int = 365,
        confidence_level: float = 0.95,
        location_id: Optional[int] = None
    ) -> list[ForecastResult]:
        """
        Forecast demand for products.

        Args:
            product_ids: Products to forecast (None = all products with history)
            periods: Number of periods to forecast
            period_type: Granularity of forecast
            method: Forecasting method to use
            historical_days: Days of historical data to use
            confidence_level: Confidence level for prediction intervals
            location_id: Filter by location (default: WH/Stock)

        Returns:
            List of ForecastResult objects
        """
        location_id = location_id or self.DEFAULT_LOCATION_ID

        # Get products
        if product_ids:
            products = self.client.search_read(
                "product.product",
                [("id", "in", product_ids), ("type", "=", "product")],
                ["id", "name", "default_code"]
            )
        else:
            products = self.client.search_read(
                "product.product",
                [("type", "=", "product")],
                ["id", "name", "default_code"],
                limit=100  # Limit for performance
            )

        results = []
        for product in products:
            try:
                result = self._forecast_product(
                    product,
                    periods,
                    period_type,
                    method,
                    historical_days,
                    confidence_level,
                    location_id
                )
                if result:
                    results.append(result)
            except Exception as e:
                # Skip products with insufficient data
                continue

        return results

    def _forecast_product(
        self,
        product: dict,
        periods: int,
        period_type: str,
        method: ForecastMethod,
        historical_days: int,
        confidence_level: float,
        location_id: int
    ) -> Optional[ForecastResult]:
        """Forecast demand for a single product."""
        # Get historical demand data
        history = self._get_demand_history(
            product["id"],
            historical_days,
            period_type,
            location_id
        )

        if len(history) < 4:  # Need minimum data points
            return None

        df = pd.DataFrame(history)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        # Detect trend and seasonality
        trend = self._detect_trend(df["quantity"].values)
        seasonality = self._detect_seasonality(df["quantity"].values, period_type)

        # Select or use specified method
        if method == ForecastMethod.AUTO:
            method = self._select_best_method(df, seasonality)

        # Generate forecast
        forecast, accuracy = self._generate_forecast(
            df["quantity"].values,
            periods,
            method,
            confidence_level
        )

        # Create forecast periods
        last_date = df.index[-1]
        forecast_periods = []
        for i, (point, lower, upper) in enumerate(forecast):
            if period_type == "day":
                date = last_date + timedelta(days=i + 1)
            elif period_type == "week":
                date = last_date + timedelta(weeks=i + 1)
            else:  # month
                date = last_date + pd.DateOffset(months=i + 1)

            forecast_periods.append({
                "date": date.strftime("%Y-%m-%d"),
                "quantity": round(max(0, point), 2),
                "lower_bound": round(max(0, lower), 2),
                "upper_bound": round(max(0, upper), 2)
            })

        return ForecastResult(
            product_id=product["id"],
            product_name=product["name"],
            product_code=product.get("default_code"),
            method_used=method.value,
            forecast_periods=forecast_periods,
            accuracy_metrics=accuracy,
            historical_avg=round(df["quantity"].mean(), 2),
            trend=trend,
            seasonality_detected=seasonality,
            confidence_level=confidence_level
        )

    def _get_demand_history(
        self,
        product_id: int,
        days: int,
        period_type: str,
        location_id: int
    ) -> list[dict]:
        """Get historical demand data aggregated by period."""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Get outgoing moves (sales) from specific location
        moves = self.client.search_read(
            "stock.move",
            [
                ("product_id", "=", product_id),
                ("state", "=", "done"),
                ("date", ">=", date_from),
                ("location_id", "=", location_id),
                ("location_dest_id.usage", "=", "customer")
            ],
            ["date", "product_uom_qty"],
            order="date asc"
        )

        if not moves:
            return []

        # Convert to DataFrame and aggregate
        df = pd.DataFrame(moves)
        df["date"] = pd.to_datetime(df["date"]).dt.date

        # Group by period
        if period_type == "day":
            grouped = df.groupby("date")["product_uom_qty"].sum()
        elif period_type == "week":
            df["period"] = pd.to_datetime(df["date"]).dt.to_period("W")
            grouped = df.groupby("period")["product_uom_qty"].sum()
            grouped.index = grouped.index.to_timestamp()
        else:  # month
            df["period"] = pd.to_datetime(df["date"]).dt.to_period("M")
            grouped = df.groupby("period")["product_uom_qty"].sum()
            grouped.index = grouped.index.to_timestamp()

        # Fill missing periods with zeros
        if len(grouped) > 1:
            if period_type == "day":
                full_range = pd.date_range(grouped.index.min(), grouped.index.max(), freq="D")
            elif period_type == "week":
                full_range = pd.date_range(grouped.index.min(), grouped.index.max(), freq="W")
            else:
                full_range = pd.date_range(grouped.index.min(), grouped.index.max(), freq="MS")

            grouped = grouped.reindex(full_range, fill_value=0)

        return [
            {"date": str(date), "quantity": qty}
            for date, qty in grouped.items()
        ]

    def _detect_trend(self, data: np.ndarray) -> str:
        """Detect trend direction in time series."""
        if len(data) < 3:
            return "stable"

        # Simple linear regression for trend
        x = np.arange(len(data))
        slope, _, r_value, p_value, _ = stats.linregress(x, data)

        # Significant trend if p < 0.05 and meaningful slope
        if p_value < 0.05:
            relative_slope = slope / (np.mean(data) + 1e-10)
            if relative_slope > 0.01:
                return "increasing"
            elif relative_slope < -0.01:
                return "decreasing"

        return "stable"

    def _detect_seasonality(self, data: np.ndarray, period_type: str) -> bool:
        """Detect if seasonality is present."""
        if len(data) < 14:  # Need enough data
            return False

        # Expected seasonal periods
        if period_type == "day":
            period = 7  # Weekly
        elif period_type == "week":
            period = 4  # Monthly
        else:
            period = 12  # Yearly

        if len(data) < period * 2:
            return False

        # Use autocorrelation to detect seasonality
        autocorr = np.correlate(data - np.mean(data), data - np.mean(data), mode="full")
        autocorr = autocorr[len(autocorr) // 2:]
        autocorr = autocorr / autocorr[0]

        if len(autocorr) > period:
            # Check if autocorrelation at seasonal lag is significant
            return autocorr[period] > 0.3

        return False

    def _select_best_method(
        self,
        df: pd.DataFrame,
        has_seasonality: bool
    ) -> ForecastMethod:
        """Select the best forecasting method based on data characteristics."""
        data = df["quantity"].values

        if len(data) < 10:
            return ForecastMethod.MOVING_AVERAGE

        if has_seasonality:
            return ForecastMethod.HOLT_WINTERS

        # Check variance
        cv = np.std(data) / (np.mean(data) + 1e-10)
        if cv < 0.3:
            return ForecastMethod.EXPONENTIAL_SMOOTHING
        else:
            return ForecastMethod.LINEAR_REGRESSION

    def _generate_forecast(
        self,
        data: np.ndarray,
        periods: int,
        method: ForecastMethod,
        confidence_level: float
    ) -> tuple[list[tuple], dict]:
        """Generate forecast using specified method."""
        if method == ForecastMethod.MOVING_AVERAGE:
            return self._moving_average_forecast(data, periods, confidence_level)
        elif method == ForecastMethod.EXPONENTIAL_SMOOTHING:
            return self._exponential_smoothing_forecast(data, periods, confidence_level)
        elif method == ForecastMethod.LINEAR_REGRESSION:
            return self._linear_regression_forecast(data, periods, confidence_level)
        elif method == ForecastMethod.HOLT_WINTERS:
            return self._holt_winters_forecast(data, periods, confidence_level)
        else:
            return self._moving_average_forecast(data, periods, confidence_level)

    def _moving_average_forecast(
        self,
        data: np.ndarray,
        periods: int,
        confidence_level: float
    ) -> tuple[list[tuple], dict]:
        """Simple moving average forecast."""
        window = min(7, len(data) // 2)
        ma = np.convolve(data, np.ones(window) / window, mode="valid")

        forecast_value = ma[-1]
        std_error = np.std(data[-window:])
        z_score = stats.norm.ppf((1 + confidence_level) / 2)

        forecasts = []
        for i in range(periods):
            lower = forecast_value - z_score * std_error * np.sqrt(1 + i * 0.1)
            upper = forecast_value + z_score * std_error * np.sqrt(1 + i * 0.1)
            forecasts.append((forecast_value, lower, upper))

        # Calculate accuracy on last 20% of data
        accuracy = self._calculate_accuracy(data, window, "ma")

        return forecasts, accuracy

    def _exponential_smoothing_forecast(
        self,
        data: np.ndarray,
        periods: int,
        confidence_level: float
    ) -> tuple[list[tuple], dict]:
        """Exponential smoothing forecast."""
        alpha = 0.3  # Smoothing parameter

        # Calculate exponential smoothing
        smoothed = [data[0]]
        for i in range(1, len(data)):
            smoothed.append(alpha * data[i] + (1 - alpha) * smoothed[-1])

        forecast_value = smoothed[-1]
        residuals = data - np.array(smoothed[:len(data)])
        std_error = np.std(residuals)
        z_score = stats.norm.ppf((1 + confidence_level) / 2)

        forecasts = []
        for i in range(periods):
            # Variance increases with forecast horizon
            variance_factor = np.sqrt(1 + (i * alpha ** 2))
            lower = forecast_value - z_score * std_error * variance_factor
            upper = forecast_value + z_score * std_error * variance_factor
            forecasts.append((forecast_value, lower, upper))

        accuracy = self._calculate_accuracy(data, len(data) // 5, "es")

        return forecasts, accuracy

    def _linear_regression_forecast(
        self,
        data: np.ndarray,
        periods: int,
        confidence_level: float
    ) -> tuple[list[tuple], dict]:
        """Linear regression forecast."""
        x = np.arange(len(data))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, data)

        residuals = data - (slope * x + intercept)
        rmse = np.sqrt(np.mean(residuals ** 2))
        z_score = stats.norm.ppf((1 + confidence_level) / 2)

        forecasts = []
        for i in range(periods):
            future_x = len(data) + i
            point_forecast = slope * future_x + intercept
            # Prediction interval widens with distance from mean
            se_forecast = rmse * np.sqrt(1 + 1 / len(data) +
                (future_x - np.mean(x)) ** 2 / np.sum((x - np.mean(x)) ** 2))
            lower = point_forecast - z_score * se_forecast
            upper = point_forecast + z_score * se_forecast
            forecasts.append((point_forecast, lower, upper))

        accuracy = {
            "r_squared": round(r_value ** 2, 4),
            "rmse": round(rmse, 2),
            "mae": round(np.mean(np.abs(residuals)), 2),
            "mape": round(np.mean(np.abs(residuals / (data + 1e-10))) * 100, 2)
        }

        return forecasts, accuracy

    def _holt_winters_forecast(
        self,
        data: np.ndarray,
        periods: int,
        confidence_level: float
    ) -> tuple[list[tuple], dict]:
        """Holt-Winters exponential smoothing (simplified)."""
        alpha = 0.3  # Level
        beta = 0.1   # Trend

        # Initialize
        level = data[0]
        trend = (data[1] - data[0]) if len(data) > 1 else 0

        levels = [level]
        trends = [trend]

        for i in range(1, len(data)):
            new_level = alpha * data[i] + (1 - alpha) * (levels[-1] + trends[-1])
            new_trend = beta * (new_level - levels[-1]) + (1 - beta) * trends[-1]
            levels.append(new_level)
            trends.append(new_trend)

        # Forecast
        residuals = data - np.array([l + t for l, t in zip(levels, trends)])[:len(data)]
        std_error = np.std(residuals)
        z_score = stats.norm.ppf((1 + confidence_level) / 2)

        forecasts = []
        for i in range(periods):
            point = levels[-1] + (i + 1) * trends[-1]
            se = std_error * np.sqrt(1 + i * 0.2)
            lower = point - z_score * se
            upper = point + z_score * se
            forecasts.append((point, lower, upper))

        accuracy = {
            "rmse": round(np.sqrt(np.mean(residuals ** 2)), 2),
            "mae": round(np.mean(np.abs(residuals)), 2),
            "mape": round(np.mean(np.abs(residuals / (data + 1e-10))) * 100, 2)
        }

        return forecasts, accuracy

    def _calculate_accuracy(
        self,
        data: np.ndarray,
        holdout: int,
        method: str
    ) -> dict:
        """Calculate accuracy metrics using holdout validation."""
        if holdout < 2 or holdout >= len(data):
            return {"mae": 0, "rmse": 0, "mape": 0}

        train = data[:-holdout]
        test = data[-holdout:]

        if method == "ma":
            window = min(7, len(train) // 2)
            forecast = np.convolve(train, np.ones(window) / window, mode="valid")[-1]
            predictions = np.full(holdout, forecast)
        else:
            # Simple exponential smoothing for validation
            alpha = 0.3
            smoothed = train[0]
            for val in train[1:]:
                smoothed = alpha * val + (1 - alpha) * smoothed
            predictions = np.full(holdout, smoothed)

        errors = test - predictions
        return {
            "mae": round(np.mean(np.abs(errors)), 2),
            "rmse": round(np.sqrt(np.mean(errors ** 2)), 2),
            "mape": round(np.mean(np.abs(errors / (test + 1e-10))) * 100, 2)
        }

    def get_forecast_summary(
        self,
        forecasts: list[ForecastResult]
    ) -> dict:
        """Get summary of all forecasts."""
        if not forecasts:
            return {}

        total_forecast = sum(
            sum(p["quantity"] for p in f.forecast_periods)
            for f in forecasts
        )

        trend_counts = {"increasing": 0, "decreasing": 0, "stable": 0}
        for f in forecasts:
            trend_counts[f.trend] += 1

        avg_accuracy = {
            "avg_mape": round(np.mean([
                f.accuracy_metrics.get("mape", 0) for f in forecasts
            ]), 2)
        }

        return {
            "products_forecasted": len(forecasts),
            "total_forecasted_demand": round(total_forecast, 2),
            "trend_breakdown": trend_counts,
            "seasonality_detected_count": sum(1 for f in forecasts if f.seasonality_detected),
            "accuracy_metrics": avg_accuracy
        }
