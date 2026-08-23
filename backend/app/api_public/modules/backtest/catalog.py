"""Indicator catalog, derived from the REAL engine enum `IndicatorType`
(app.schemas.strategy). Served via GET /v1/catalog/indicators and as an MCP
resource so the LLM discovers indicators without inflating context.
"""
from __future__ import annotations

from app.schemas.strategy import IndicatorType

# Category map (from the grouping comments in app/schemas/strategy.py).
_CATEGORY = {
    "Trend / MA": [
        "SMA", "EMA", "WMA", "VWAP", "VWAP Sd+", "VWAP Sd-", "AVWAP",
        "Linear Regression", "Zig Zag", "Ichimoku Clouds",
    ],
    "Momentum": [
        "RSI", "MACD", "Stochastic", "Momentum", "CCI", "ROC", "DMI+", "DMI-", "Williams %R",
    ],
    "Volatility": ["ATR", "ADX", "Bollinger Bands", "Donchian", "Parabolic SAR"],
    "Volume": ["OBV", "Volume", "RVOL by bar", "Accumulated Volume", "SMA Volume"],
    "Price": [
        "Bar Close", "Bar Open", "High Bar", "Low Bar", "PM High", "PM Low", "PM Open",
        "AM Open", "RTH High", "RTH Low", "RTH Open", "Yesterday High", "Yesterday Low",
        "Yesterday Open", "Yesterday Close", "Yesterday Volume", "High of last X days",
        "Low of last X days", "Previous max", "Previous min", "Prev. Bar Close",
        "Prev. Bar Open", "Prev. Bar High", "Prev. Bar Low", "Day Open", "High of Day",
        "Low of Day", "Current Open", "Previous Close", "Max N Bars",
    ],
    "Behavior": [
        "Consecutive Higher Highs", "Consecutive Lower Lows", "Consecutive Red Candles",
        "Consecutive Green Candles", "Consecutive Higher Lows", "Consecutive Lower Highs",
        "Opening Range +", "Opening Range -", "Opening Range AM +", "Opening Range AM -",
        "Heikin-Ashi", "HA Close", "HA Open", "HA High", "HA Low", "Triangle Ascending",
        "Triangle Descending", "Triangle Symmetric", "Ret % AM", "Candle Range %",
        "Elapsed time from last High", "Elapsed Time", "PM High Gap (%)",
    ],
    "Time": [
        "Time of Day", "Range of Time", "High/Low from x time", "High/Low from hour-time",
    ],
    "Returns": ["Ret % PM", "Ret % RTH"],
}

# Common parameters per indicator (hint for the LLM/dev).
_PARAMS = {
    "SMA": ["period"], "EMA": ["period"], "WMA": ["period"], "SMA Volume": ["period"],
    "RSI": ["period", "overbought", "oversold"], "MACD": ["period", "period2", "period3", "macd_line"],
    "Stochastic": ["period"], "CCI": ["period"], "ROC": ["period"], "Williams %R": ["period"],
    "ATR": ["period", "multiplier"], "ADX": ["period"], "RVOL by bar": ["period"],
    "Bollinger Bands": ["period", "stdDev", "band_line"], "Donchian": ["period"],
    "Parabolic SAR": ["min_af", "max_af"], "Linear Regression": ["period", "deviationLevel"],
    "Zig Zag": ["reversionPercentage"], "Ichimoku Clouds": ["ichimoku_line"],
    "Time of Day": ["time_hour", "time_minute", "time_condition"],
    "High of last X days": ["days_lookback"], "Low of last X days": ["days_lookback"],
    "Max N Bars": ["period"], "Opening Range +": ["orb_minutes"], "Opening Range -": ["orb_minutes"],
}


def _category_for(value: str) -> str:
    for cat, members in _CATEGORY.items():
        if value in members:
            return cat
    return "Other"


def build_catalog() -> list[dict]:
    """Distinct indicator entries (the enum has aliases that share a value)."""
    seen: dict[str, dict] = {}
    for item in IndicatorType:
        val = item.value
        if val in seen:
            continue
        seen[val] = {
            "name": val,
            "category": _category_for(val),
            "params": _PARAMS.get(val, []),
        }
    # Stable order: by category then name.
    return sorted(seen.values(), key=lambda e: (e["category"], e["name"]))
