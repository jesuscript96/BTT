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
        "RSI", "MACD", "MACD Signal", "MACD Histogram", "Stochastic", "Momentum",
        "CCI", "ROC", "DMI+", "DMI-", "Williams %R",
        "Squeeze",
    ],
    "Volatility": ["ATR", "ADX", "Bollinger Bands", "Donchian", "Parabolic SAR"],
    "Volume": ["OBV", "Volume", "RVOL by bar", "Accumulated Volume", "Accumulated Dollar Volume", "Dollar Volume", "SMA Volume"],
    "Price": [
        "Bar Close", "Bar Open", "High Bar", "Low Bar", "PM High", "PM Low", "PM Open",
        "AM Open", "RTH High", "RTH Low", "RTH Open", "Yesterday High", "Yesterday Low",
        "Yesterday Open", "Yesterday Close", "Yesterday Volume", "Overhead last X days",
        "High of last X days",
        "Low of last X days", "Previous max", "Previous min", "Prev. Bar Close",
        "Prev. Bar Open", "Prev. Bar High", "Prev. Bar Low", "Day Open", "High of Day",
        "Low of Day", "Current Open", "Previous Close", "Max N Bars",
        "Ultimo pivote",
        "Punto de control", "Nodo de arriba", "Nodo de abajo",
        "Zona alta", "Zona baja",
    ],
    "Behavior": [
        "Consecutive Higher Highs", "Consecutive Lower Lows", "Consecutive Red Candles",
        "Consecutive Green Candles", "Consecutive Higher Lows", "Consecutive Lower Highs",
        "Opening Range +", "Opening Range -", "Opening Range AM +", "Opening Range AM -",
        "Heikin-Ashi", "HA Close", "HA Open", "HA High", "HA Low", "Triangle Ascending",
        "Triangle Descending", "Triangle Symmetric", "Ret % AM", "Candle Range %",
        "Recorrido (%)",
        "Elapsed time from last High", "Elapsed Time", "PM High Gap (%)", "Current Gap (%)", "Open Gap (%)",
        "% Session Fade", "% Fade",
    ],
    "Time": [
        "Time of Day", "Range of Time", "High/Low from x time", "High/Low from hour-time",
    ],
    "Returns": ["Ret % PM", "Ret % RTH"],
    # Bloque aparte, igual que en la UI: medidas que no existen en las
    # plataformas comerciales. Todas son standalone (solo contra una cifra).
    "Alternativos": [
        "Vol. de la franja",
        "Reg. Slope", "Reg. R2", "ATR Extension",
        "Absorption", "Wick Ratio", "Absorption + Wick",
        "Retroceso (%)", "Time vs Level",
    ],
}

# Common parameters per indicator (hint for the LLM/dev).
_PARAMS = {
    "SMA": ["period"], "EMA": ["period"], "WMA": ["period"], "SMA Volume": ["period"],
    "RSI": ["period", "overbought", "oversold"],
    # period = media rapida (12), period2 = lenta (26), period3 = señal (9).
    # `macd_line` NO se lee: la linea se elige por el nombre del indicador.
    "MACD": ["period", "period2", "period3"],
    "MACD Signal": ["period", "period2", "period3"],
    "MACD Histogram": ["period", "period2", "period3"],
    "Stochastic": ["period"], "CCI": ["period"], "ROC": ["period"], "Williams %R": ["period"],
    "ATR": ["period", "multiplier"], "ADX": ["period"], "RVOL by bar": ["period"],
    "Bollinger Bands": ["period", "stdDev", "band_line"], "Donchian": ["period"],
    "Parabolic SAR": ["min_af", "max_af"], "Linear Regression": ["period", "deviationLevel"],
    "Zig Zag": ["reversionPercentage"], "Ichimoku Clouds": ["ichimoku_line"],
    "Time of Day": ["time_hour", "time_minute", "time_condition"],
    "High of last X days": ["days_lookback"], "Low of last X days": ["days_lookback"],
    "Overhead last X days": ["days_lookback", "overhead_extreme",
                              "overhead_ref", "overhead_vol_rule"],
    "Max N Bars": ["period"], "Opening Range +": ["orb_minutes"], "Opening Range -": ["orb_minutes"],
    "Squeeze": ["range_minutes", "squeeze_direction"],
    "% Session Fade": ["session_ref"],
    "% Fade": ["fade_ref", "ap_session"],
    # range_minutes = ventana de RELOJ en minutos (no de velas).
    "Reg. Slope": ["range_minutes"],
    "Reg. R2": ["range_minutes"],
    # period = ATR; period2 = periodo de la media si ref_level es sma/ema.
    "ATR Extension": ["period", "period2", "ref_level"],
    "Time vs Level": ["period2", "ref_level", "level_dir"],
    # range_minutes = ventana de RELOJ. Los umbrales de "Absorption + Wick" van
    # dentro del indicador porque la condicion solo tiene un `target`.
    # range_minutes = 0 (o ausente) mide el impulso del DIA entero.
    "Retroceso (%)": ["range_minutes", "swing_dir"],
    # pivot_window = velas de confirmacion a cada lado; swing_dir = techo o suelo.
    "Ultimo pivote": ["pivot_window", "swing_dir"],
    # bin_pct = anchura de franja en % del precio; liston_pct = % del POC para
    # que una franja cuente como nodo.
    "Vol. de la franja": ["bin_pct"],
    "Punto de control": ["bin_pct"],
    "Nodo de arriba": ["bin_pct", "liston_pct"],
    "Nodo de abajo": ["bin_pct", "liston_pct"],
    # zona_pct = % del volumen del dia que abarca la banda (70 clasico).
    "Zona alta": ["bin_pct", "zona_pct"],
    "Zona baja": ["bin_pct", "zona_pct"],
    "Absorption": ["range_minutes"],
    "Wick Ratio": ["range_minutes", "wick_side"],
    "Absorption + Wick": ["range_minutes", "wick_side", "abs_op", "abs_level",
                           "wick_op", "wick_level"],
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
