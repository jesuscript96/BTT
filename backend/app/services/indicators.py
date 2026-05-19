"""
Computes technical indicators from OHLCV data.
Numba-accelerated numpy implementations for maximum performance.

Supports the full IndicatorConfig schema (BTT March 2026):
  name, period, period2, period3, stdDev, multiplier, offset,
  days_lookback, calc_on_heikin, time_hour, time_minute, time_condition
"""

import numpy as np
import pandas as pd
from numba import njit

try:
    import talib as _talib
except ImportError:
    _talib = None

try:
    import pandas_ta as ta
except ImportError:
    ta = None


# ---------------------------------------------------------------------------
# Numba-accelerated indicator implementations
# ---------------------------------------------------------------------------

def _sma(values: np.ndarray, window: int) -> np.ndarray:
    """SMA via cumsum — already vectorized, no loop needed."""
    out = np.full(len(values), np.nan)
    if len(values) < window:
        return out
    cs = np.cumsum(values)
    out[window - 1] = cs[window - 1] / window
    out[window:] = (cs[window:] - cs[:-window]) / window
    return out


@njit(cache=True)
def _ema_core(values, window):
    n = len(values)
    alpha = 2.0 / (window + 1)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    first_valid = window - 1
    if first_valid >= n:
        return out
    s = 0.0
    for k in range(window):
        s += values[k]
    out[first_valid] = s / window
    for i in range(first_valid + 1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _ema(values: np.ndarray, window: int) -> np.ndarray:
    return _ema_core(np.ascontiguousarray(values, dtype=np.float64), window)


@njit(cache=True)
def _rsi_core(close, window):
    n = len(close)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    if n < 2:
        return out
    # Calculate deltas
    m = n - 1
    gain = np.empty(m, dtype=np.float64)
    loss = np.empty(m, dtype=np.float64)
    for i in range(m):
        d = close[i + 1] - close[i]
        gain[i] = d if d > 0.0 else 0.0
        loss[i] = -d if d < 0.0 else 0.0
    # EMA of gain/loss
    alpha = 2.0 / (window + 1)
    avg_g = np.empty(m, dtype=np.float64)
    avg_l = np.empty(m, dtype=np.float64)
    for k in range(m):
        avg_g[k] = np.nan
        avg_l[k] = np.nan
    fv = window - 1
    if fv < m:
        sg = 0.0
        sl = 0.0
        for k in range(window):
            sg += gain[k]
            sl += loss[k]
        avg_g[fv] = sg / window
        avg_l[fv] = sl / window
        for i in range(fv + 1, m):
            avg_g[i] = alpha * gain[i] + (1.0 - alpha) * avg_g[i - 1]
            avg_l[i] = alpha * loss[i] + (1.0 - alpha) * avg_l[i - 1]
    for i in range(m):
        ag = avg_g[i]
        al = avg_l[i]
        if al != al or ag != ag:  # NaN check
            out[i + 1] = np.nan
        elif al == 0.0:
            out[i + 1] = 100.0
        else:
            rs = ag / al
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _rsi(close: np.ndarray, window: int) -> np.ndarray:
    return _rsi_core(np.ascontiguousarray(close, dtype=np.float64), window)


def _macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    """Returns (macd_line, signal_line, histogram). Uses Numba-accelerated EMA."""
    c = np.ascontiguousarray(close, dtype=np.float64)
    ema_fast = _ema_core(c, fast)
    ema_slow = _ema_core(c, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema_core(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


@njit(cache=True)
def _atr_core(high, low, close, window):
    n = len(close)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = hl
        if hc > tr[i]:
            tr[i] = hc
        if lc > tr[i]:
            tr[i] = lc
    # Inline EMA
    alpha = 2.0 / (window + 1)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    fv = window - 1
    if fv >= n:
        return out
    s = 0.0
    for k in range(window):
        s += tr[k]
    out[fv] = s / window
    for i in range(fv + 1, n):
        out[i] = alpha * tr[i] + (1.0 - alpha) * out[i - 1]
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> np.ndarray:
    return _atr_core(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        window,
    )


def _vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    typical = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical * volume)
    cum_vol = np.cumsum(volume)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(cum_vol != 0, cum_tp_vol / cum_vol, np.nan)


@njit(cache=True)
def _consecutive_count_core(signal):
    n = len(signal)
    result = np.zeros(n, dtype=np.float64)
    count = 0.0
    for i in range(n):
        if signal[i]:
            count += 1.0
        else:
            count = 0.0
        result[i] = count
    return result


def _consecutive_count(signal: np.ndarray) -> np.ndarray:
    return _consecutive_count_core(np.ascontiguousarray(signal))


def _hammer(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    body = np.abs(close - open_)
    full_range = high - low + 1e-10
    lower_wick = np.minimum(open_, close) - low
    return (lower_wick >= 2 * body) & (body / full_range < 0.4)


def _shooting_star(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    body = np.abs(close - open_)
    full_range = high - low + 1e-10
    upper_wick = high - np.maximum(open_, close)
    return (upper_wick >= 2 * body) & (body / full_range < 0.4)


@njit(cache=True)
def _stochastic_k(high, low, close, k_period):
    n = len(close)
    k = np.empty(n, dtype=np.float64)
    for i in range(n):
        k[i] = np.nan
    for i in range(k_period - 1, n):
        hh = high[i]
        ll = low[i]
        for j in range(i - k_period + 1, i):
            if high[j] > hh:
                hh = high[j]
            if low[j] < ll:
                ll = low[j]
        if hh != ll:
            k[i] = (close[i] - ll) / (hh - ll) * 100.0
        else:
            k[i] = 50.0
    return k


def _stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                k_period: int = 14, d_period: int = 3) -> tuple:
    """Returns (%K, %D)."""
    k = _stochastic_k(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        k_period,
    )
    d = _sma(k, d_period)
    return k, d


@njit(cache=True)
def _rolling_std_core(values, period):
    n = len(values)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += values[j]
        mean = s / period
        ss = 0.0
        for j in range(i - period + 1, i + 1):
            d = values[j] - mean
            ss += d * d
        out[i] = (ss / period) ** 0.5
    return out


def _bollinger_bands(close: np.ndarray, period: int = 20, std_dev: float = 2.0) -> tuple:
    """Returns (upper, middle, lower)."""
    c = np.ascontiguousarray(close, dtype=np.float64)
    middle = _sma(c, period)
    rolling_std = _rolling_std_core(c, period)
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    return upper, middle, lower


@njit(cache=True)
def _cci_core(high, low, close, period):
    n = len(close)
    typical = np.empty(n, dtype=np.float64)
    for i in range(n):
        typical[i] = (high[i] + low[i] + close[i]) / 3.0
    # SMA of typical
    sma_tp = np.empty(n, dtype=np.float64)
    for k in range(n):
        sma_tp[k] = np.nan
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += typical[j]
        sma_tp[i] = s / period
    # MAD and CCI
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    for i in range(period - 1, n):
        sm = sma_tp[i]
        if sm != sm:  # NaN
            continue
        mad_sum = 0.0
        for j in range(i - period + 1, i + 1):
            d = typical[j] - sm
            if d < 0.0:
                d = -d
            mad_sum += d
        mad = mad_sum / period
        if mad != 0.0:
            out[i] = (typical[i] - sm) / (0.015 * mad)
        else:
            out[i] = 0.0
    return out


def _cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    return _cci_core(
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
        period,
    )


def _roc(close: np.ndarray, period: int = 12) -> np.ndarray:
    out = np.full(len(close), np.nan)
    out[period:] = (close[period:] - close[:-period]) / close[:-period] * 100
    return out


def _momentum(close: np.ndarray, period: int = 10) -> np.ndarray:
    out = np.full(len(close), np.nan)
    out[period:] = close[period:] - close[:-period]
    return out


@njit(cache=True)
def _obv_core(close, volume):
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    return _obv_core(
        np.ascontiguousarray(close, dtype=np.float64),
        np.ascontiguousarray(volume, dtype=np.float64),
    )


@njit(cache=True)
def _dmi_loops(high, low, close):
    n = len(close)
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0.0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0.0:
            minus_dm[i] = down_move
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = hl
        if hc > tr[i]:
            tr[i] = hc
        if lc > tr[i]:
            tr[i] = lc
    return plus_dm, minus_dm, tr


def _dmi(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> tuple:
    """Returns (+DI, -DI)."""
    h = np.ascontiguousarray(high, dtype=np.float64)
    l = np.ascontiguousarray(low, dtype=np.float64)
    c = np.ascontiguousarray(close, dtype=np.float64)
    plus_dm, minus_dm, tr = _dmi_loops(h, l, c)

    atr = _ema_core(tr, period)
    plus_di = _ema_core(plus_dm, period) / np.where(atr != 0, atr, np.nan) * 100
    minus_di = _ema_core(minus_dm, period) / np.where(atr != 0, atr, np.nan) * 100
    return plus_di, minus_di


@njit(cache=True)
def _heikin_ashi_core(open_, high, low, close):
    n = len(close)
    ha_close = np.empty(n, dtype=np.float64)
    ha_open = np.empty(n, dtype=np.float64)
    ha_high = np.empty(n, dtype=np.float64)
    ha_low = np.empty(n, dtype=np.float64)
    for i in range(n):
        ha_close[i] = (open_[i] + high[i] + low[i] + close[i]) / 4.0
    ha_open[0] = (open_[0] + close[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    for i in range(n):
        hh = high[i]
        if ha_open[i] > hh:
            hh = ha_open[i]
        if ha_close[i] > hh:
            hh = ha_close[i]
        ha_high[i] = hh
        ll = low[i]
        if ha_open[i] < ll:
            ll = ha_open[i]
        if ha_close[i] < ll:
            ll = ha_close[i]
        ha_low[i] = ll
    return ha_open, ha_high, ha_low, ha_close


def _heikin_ashi(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> tuple:
    """Returns (ha_open, ha_high, ha_low, ha_close)."""
    return _heikin_ashi_core(
        np.ascontiguousarray(open_, dtype=np.float64),
        np.ascontiguousarray(high, dtype=np.float64),
        np.ascontiguousarray(low, dtype=np.float64),
        np.ascontiguousarray(close, dtype=np.float64),
    )


@njit(cache=True)
def _linear_regression_core(close, period):
    n = len(close)
    out = np.empty(n, dtype=np.float64)
    for k in range(n):
        out[k] = np.nan
    # Pre-compute x stats
    x_mean = (period - 1.0) / 2.0
    x_var = 0.0
    for k in range(period):
        d = k - x_mean
        x_var += d * d
    if x_var == 0.0:
        return out
    for i in range(period - 1, n):
        y_sum = 0.0
        for j in range(i - period + 1, i + 1):
            y_sum += close[j]
        y_mean = y_sum / period
        cov = 0.0
        for k in range(period):
            cov += (k - x_mean) * (close[i - period + 1 + k] - y_mean)
        slope = cov / x_var
        out[i] = y_mean + slope * (period - 1.0 - x_mean)
    return out


def _linear_regression(close: np.ndarray, period: int = 14) -> np.ndarray:
    return _linear_regression_core(np.ascontiguousarray(close, dtype=np.float64), period)


def _pivot_points(daily_stats: dict) -> dict:
    """Calculate pivot points from daily stats. Returns dict with PP, R1, S1, R2, S2, R3, S3."""
    h = daily_stats.get("yesterday_high", daily_stats.get("rth_high", np.nan))
    l = daily_stats.get("yesterday_low", daily_stats.get("rth_low", np.nan))
    c = daily_stats.get("previous_close", np.nan)
    if np.isnan(h) or np.isnan(l) or np.isnan(c):
        return {}
    pp = (h + l + c) / 3.0
    return {
        "PP": pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
        "R3": h + 2 * (pp - l),
        "S3": l - 2 * (h - pp),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_indicator(
    name: str,
    df: pd.DataFrame,
    period: int | None = None,
    period2: int | None = None,
    period3: int | None = None,
    std_dev: float | None = None,
    multiplier: float | None = None,
    offset: int = 0,
    days_lookback: int | None = None,
    calc_on_heikin: bool = False,
    time_hour: int | None = None,
    time_minute: int | None = None,
    time_condition: str | None = None,
    daily_stats: dict | None = None,
    cache: dict | None = None,
) -> pd.Series:
    cache_key = (name, period, period2, period3, std_dev, multiplier, offset,
                 days_lookback, calc_on_heikin, time_hour, time_minute, time_condition)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    volume = df["volume"]

    # If calc_on_heikin, transform OHLC to Heikin-Ashi
    if calc_on_heikin:
        ha_o, ha_h, ha_l, ha_c = _heikin_ashi(
            open_.values.astype(np.float64),
            high.values.astype(np.float64),
            low.values.astype(np.float64),
            close.values.astype(np.float64),
        )
        close = pd.Series(ha_c, index=df.index)
        high = pd.Series(ha_h, index=df.index)
        low = pd.Series(ha_l, index=df.index)
        open_ = pd.Series(ha_o, index=df.index)

    result = _compute_raw(
        name, close, high, low, open_, volume,
        period, period2, period3, std_dev, multiplier,
        days_lookback, time_hour, time_minute, time_condition,
        daily_stats, df,
    )

    if offset and offset != 0:
        result = result.shift(offset)

    if cache is not None:
        cache[cache_key] = result

    return result


def _compute_raw(
    name: str,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    open_: pd.Series,
    volume: pd.Series,
    period: int | None,
    period2: int | None,
    period3: int | None,
    std_dev: float | None,
    multiplier: float | None,
    days_lookback: int | None,
    time_hour: int | None,
    time_minute: int | None,
    time_condition: str | None,
    daily_stats: dict | None,
    df: pd.DataFrame,
) -> pd.Series:
    ds = daily_stats or {}

    # --- Price / Bars ---
    if name == "Close":
        return close
    if name == "Open":
        return open_
    if name == "High":
        return high
    if name == "Low":
        return low
    if name == "Volume":
        return volume.astype(float)
    if name in ("Day Open", "Current Open"):
        if "rth_open" in ds and not pd.isna(ds["rth_open"]):
            return pd.Series(float(ds["rth_open"]), index=close.index)
        return pd.Series(float(open_.iloc[0]) if len(open_) > 0 else np.nan, index=close.index)
    if name == "Bar Open":
        return open_
    if name == "Yesterday Open":
        return pd.Series(ds.get("yesterday_open", ds.get("rth_open", np.nan)), index=close.index)
    if name == "Yesterday Close" or name == "Previous Close":
        return pd.Series(ds.get("previous_close", np.nan), index=close.index)
    if name == "Yesterday High":
        return pd.Series(ds.get("yesterday_high", np.nan), index=close.index)
    if name == "Yesterday Low":
        return pd.Series(ds.get("yesterday_low", np.nan), index=close.index)
    if name == "Pre-Market High":
        return pd.Series(ds.get("pm_high", np.nan), index=close.index)
    if name == "Pre-Market Low":
        return pd.Series(ds.get("pm_low", np.nan), index=close.index)
    if name == "High of Day":
        return high.cummax()
    if name == "Low of Day":
        return low.cummin()
    if name == "Max of last X days":
        val = ds.get("max_last_x", np.nan)
        return pd.Series(val, index=close.index)
    if name == "Min of last X days":
        val = ds.get("min_last_x", np.nan)
        return pd.Series(val, index=close.index)

    # --- Trend / MA ---
    if name == "SMA":
        return pd.Series(_sma(close.values, period or 20), index=close.index)
    if name == "EMA":
        return pd.Series(_ema(close.values, period or 20), index=close.index)
    if name == "WMA":
        if _talib is not None:
            return pd.Series(_talib.WMA(close.values, timeperiod=period or 20), index=close.index)
        if ta is not None:
            result = ta.wma(close, length=period or 20)
            if result is not None:
                return result
        # Fallback: weighted moving average
        w = period or 20
        weights = np.arange(1, w + 1, dtype=np.float64)
        out = np.full(len(close), np.nan)
        for i in range(w - 1, len(close)):
            out[i] = np.dot(close.values[i - w + 1:i + 1], weights) / weights.sum()
        return pd.Series(out, index=close.index)

    if name in ("VWAP", "AVWAP"):
        vals = _vwap(high.values.astype(np.float64), low.values.astype(np.float64),
                     close.values.astype(np.float64), volume.values.astype(np.float64))
        return pd.Series(vals, index=close.index)

    if name == "Linear Regression":
        return pd.Series(_linear_regression(close.values.astype(np.float64), period or 14), index=close.index)

    # --- Momentum ---
    if name == "RSI":
        return pd.Series(_rsi(close.values, period or 14), index=close.index)

    if name == "MACD":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        macd_line, signal_line, histogram = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(macd_line, index=close.index)

    if name == "MACD Signal":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        _, signal_line, _ = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(signal_line, index=close.index)

    if name == "MACD Histogram":
        fast = period or 12
        slow = period2 or 26
        signal = period3 or 9
        _, _, histogram = _macd(close.values.astype(np.float64), fast, slow, signal)
        return pd.Series(histogram, index=close.index)

    if name == "Stochastic":
        k_period = period or 14
        d_period = period2 or 3
        k, d = _stochastic(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), k_period, d_period)
        return pd.Series(k, index=close.index)

    if name == "Stochastic %D":
        k_period = period or 14
        d_period = period2 or 3
        _, d = _stochastic(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), k_period, d_period)
        return pd.Series(d, index=close.index)

    if name == "Momentum":
        return pd.Series(_momentum(close.values.astype(np.float64), period or 10), index=close.index)

    if name == "CCI":
        return pd.Series(_cci(high.values.astype(np.float64), low.values.astype(np.float64),
                              close.values.astype(np.float64), period or 20), index=close.index)

    if name == "ROC":
        return pd.Series(_roc(close.values.astype(np.float64), period or 12), index=close.index)

    if name == "DMI":
        plus_di, minus_di = _dmi(high.values.astype(np.float64), low.values.astype(np.float64),
                                 close.values.astype(np.float64), period or 14)
        return pd.Series(plus_di, index=close.index)

    if name == "DMI-":
        _, minus_di = _dmi(high.values.astype(np.float64), low.values.astype(np.float64),
                           close.values.astype(np.float64), period or 14)
        return pd.Series(minus_di, index=close.index)

    if name == "Williams %R":
        if _talib is not None:
            return pd.Series(
                _talib.WILLR(high.values, low.values, close.values, timeperiod=period or 14),
                index=close.index,
            )
        if ta is not None:
            result = ta.willr(high, low, close, length=period or 14)
            if result is not None:
                return result
        # Fallback
        p = period or 14
        out = np.full(len(close), np.nan)
        for i in range(p - 1, len(close)):
            hh = np.max(high.values[i - p + 1:i + 1])
            ll = np.min(low.values[i - p + 1:i + 1])
            if hh != ll:
                out[i] = (hh - close.values[i]) / (hh - ll) * -100
        return pd.Series(out, index=close.index)

    # --- Volatility ---
    if name == "ATR":
        return pd.Series(_atr(high.values.astype(np.float64), low.values.astype(np.float64),
                               close.values.astype(np.float64), period or 14), index=close.index)

    if name == "ADX":
        if _talib is not None:
            return pd.Series(
                _talib.ADX(high.values, low.values, close.values, timeperiod=period or 14),
                index=close.index,
            )
        if ta is not None:
            adx_df = ta.adx(high, low, close, length=period or 14)
            if adx_df is not None:
                return adx_df.iloc[:, 0]
        return pd.Series(np.nan, index=close.index)

    if name == "Bollinger Bands" or name == "Bollinger Upper":
        sd = std_dev or 2.0
        upper, middle, lower = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(upper, index=close.index)

    if name == "Bollinger Middle":
        sd = std_dev or 2.0
        _, middle, _ = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(middle, index=close.index)

    if name == "Bollinger Lower":
        sd = std_dev or 2.0
        _, _, lower = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(lower, index=close.index)

    if name == "Parabolic SAR":
        if _talib is not None:
            accel = multiplier or 0.02
            return pd.Series(
                _talib.SAR(high.values, low.values, acceleration=accel, maximum=0.2),
                index=close.index,
            )
        if ta is not None:
            result = ta.psar(high, low, close)
            if result is not None:
                # pandas_ta returns a DataFrame, pick the main column
                for col in result.columns:
                    if 'PSARl' in col or 'PSAR' in col:
                        return result[col]
        return pd.Series(np.nan, index=close.index)

    # --- Volume ---
    if name == "OBV":
        return pd.Series(_obv(close.values.astype(np.float64), volume.values.astype(np.float64)), index=close.index)

    if name == "Accumulated Volume":
        return volume.cumsum().astype(float)

    if name == "RVOL":
        # Relative Volume: current cumulative volume / average cumulative volume at same time
        # Simple approximation: volume / SMA(volume, period)
        p = period or 20
        avg_vol = _sma(volume.values.astype(np.float64), p)
        with np.errstate(divide="ignore", invalid="ignore"):
            rvol = volume.values.astype(np.float64) / np.where(avg_vol != 0, avg_vol, np.nan)
        return pd.Series(rvol, index=close.index)

    if name == "Chaikin Money Flow":
        p = period or 20
        mfm = ((close.values - low.values) - (high.values - close.values)) / (high.values - low.values + 1e-10)
        mfv = mfm * volume.values.astype(np.float64)
        sum_mfv = _sma(mfv, p) * p
        sum_vol = _sma(volume.values.astype(np.float64), p) * p
        with np.errstate(divide="ignore", invalid="ignore"):
            cmf = np.where(sum_vol != 0, sum_mfv / sum_vol, 0)
        return pd.Series(cmf, index=close.index)

    if name == "Accumulation/Distribution":
        mfm = ((close.values - low.values) - (high.values - close.values)) / (high.values - low.values + 1e-10)
        ad = np.cumsum(mfm * volume.values.astype(np.float64))
        return pd.Series(ad, index=close.index)

    # --- Behavior / Consecutive ---
    if name == "Consecutive Red Candles":
        signal = (close.values < open_.values)
        return pd.Series(_consecutive_count(signal), index=close.index)

    if name == "Consecutive Green Candles":
        signal = (close.values > open_.values)
        return pd.Series(_consecutive_count(signal), index=close.index)

    if name == "Consecutive Higher Highs":
        hh = np.empty(len(high), dtype=np.bool_)
        hh[0] = False
        hh[1:] = high.values[1:] > high.values[:-1]
        return pd.Series(_consecutive_count(hh), index=close.index)

    if name == "Consecutive Lower Lows":
        ll = np.empty(len(low), dtype=np.bool_)
        ll[0] = False
        ll[1:] = low.values[1:] < low.values[:-1]
        return pd.Series(_consecutive_count(ll), index=close.index)

    # --- Heikin-Ashi values (for direct reference, not calc_on_heikin) ---
    if name == "Heikin-Ashi" or name == "HA Close":
        ha_o, ha_h, ha_l, ha_c = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                                low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_c, index=close.index)
    if name == "HA Open":
        ha_o, _, _, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_o, index=close.index)
    if name == "HA High":
        _, ha_h, _, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_h, index=close.index)
    if name == "HA Low":
        _, _, ha_l, _ = _heikin_ashi(open_.values.astype(np.float64), high.values.astype(np.float64),
                                      low.values.astype(np.float64), close.values.astype(np.float64))
        return pd.Series(ha_l, index=close.index)

    # --- Time / Other ---
    if name == "Ret % PM":
        pm_h = ds.get("pm_high", np.nan)
        prev_c = ds.get("previous_close", np.nan)
        val = (pm_h - prev_c) / prev_c * 100 if prev_c and prev_c > 0 else np.nan
        return pd.Series(val, index=close.index)
    if name == "Ret % RTH":
        return (close - open_.iloc[0]) / open_.iloc[0] * 100 if open_.iloc[0] > 0 else pd.Series(np.nan, index=close.index)
    if name == "Ret % AM":
        return (close - open_.iloc[0]) / open_.iloc[0] * 100 if open_.iloc[0] > 0 else pd.Series(np.nan, index=close.index)

    if name == "Time of Day":
        ts = pd.to_datetime(df["timestamp"])
        minutes = ts.dt.hour * 60 + ts.dt.minute
        # Apply time_condition if provided
        if time_hour is not None and time_minute is not None and time_condition:
            target_min = time_hour * 60 + time_minute
            if time_condition == "BEFORE":
                return (minutes < target_min).astype(float)
            elif time_condition == "AFTER":
                return (minutes >= target_min).astype(float)
        return minutes

    if name == "Max N Bars":
        return pd.Series(np.arange(len(close), dtype=float), index=close.index)

    if name == "Pivot Points" or name == "PP":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("PP", np.nan), index=close.index)
    if name == "R1":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("R1", np.nan), index=close.index)
    if name == "S1":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("S1", np.nan), index=close.index)
    if name == "R2":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("R2", np.nan), index=close.index)
    if name == "S2":
        pivots = _pivot_points(ds)
        return pd.Series(pivots.get("S2", np.nan), index=close.index)

    if name == "Opening Range":
        # First 5 minutes high/low range (approximation)
        if len(high) >= 5:
            or_high = high.iloc[:5].max()
            or_low = low.iloc[:5].min()
            or_mid = (or_high + or_low) / 2
            return pd.Series(or_mid, index=close.index)
        return pd.Series(np.nan, index=close.index)

    return pd.Series(np.nan, index=close.index)


def detect_candle_pattern(
    df: pd.DataFrame,
    pattern: str,
    lookback: int = 0,
    consecutive_count: int = 1,
) -> pd.Series:
    close = df["close"].values
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    idx = df.index

    if pattern == "GREEN_VOLUME":
        sig = close > open_
    elif pattern == "GREEN_VOLUME_PLUS":
        vol_up = np.empty(len(volume), dtype=np.bool_)
        vol_up[0] = False
        vol_up[1:] = volume[1:] > volume[:-1]
        sig = (close > open_) & vol_up
    elif pattern == "RED_VOLUME":
        sig = close < open_
    elif pattern == "RED_VOLUME_PLUS":
        vol_up = np.empty(len(volume), dtype=np.bool_)
        vol_up[0] = False
        vol_up[1:] = volume[1:] > volume[:-1]
        sig = (close < open_) & vol_up
    elif pattern == "DOJI":
        body = np.abs(close - open_)
        full_range = high - low + 1e-10
        sig = (body / full_range) < 0.1
    elif pattern == "HAMMER":
        sig = _hammer(open_, high, low, close)
    elif pattern == "SHOOTING_STAR":
        sig = _shooting_star(open_, high, low, close)
    else:
        return pd.Series(False, index=idx)

    signal = pd.Series(sig, index=idx)

    if lookback > 0:
        signal = signal.shift(lookback).fillna(False).astype(bool)

    if consecutive_count > 1:
        rolling_sum = signal.astype(int).rolling(window=consecutive_count, min_periods=consecutive_count).sum()
        signal = rolling_sum >= consecutive_count

    return signal.astype(bool)
