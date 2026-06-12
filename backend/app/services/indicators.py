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


def _safe_float(val) -> float:
    if val is None or pd.isna(val):
        return np.nan
    try:
        return float(val)
    except Exception:
        return np.nan


# Global cache for "High of last X days" and "Low of last X days" lookup
_ticker_daily_ohlc_cache = {}
_global_daily_metrics_df = None

def prefetch_daily_ohlc(tickers: list[str]):
    """
    Prefetches all daily historical metrics for the given tickers from the database
    and stores them in the process-global cache _ticker_daily_ohlc_cache.
    This prevents individual slow GCS queries during the backtest loop.
    """
    global _ticker_daily_ohlc_cache, _global_daily_metrics_df
    if not tickers:
        return
        
    # Only fetch tickers that are not already cached
    tickers_to_fetch = [t for t in tickers if t and t not in _ticker_daily_ohlc_cache]
    if not tickers_to_fetch:
        return
        
    import time
    from app.database import get_db_connection
    con = get_db_connection()
    try:
        if _global_daily_metrics_df is None:
            print("[INFO] Fetching entire daily_metrics table for global cache...")
            t0 = time.time()
            df_all = con.execute("""
                SELECT ticker, CAST("timestamp" AS DATE) as date, rth_high, rth_low 
                FROM daily_metrics 
                ORDER BY ticker, "timestamp"
            """).fetchdf()
            # Convert date to string format
            df_all["date"] = pd.to_datetime(df_all["date"]).dt.strftime("%Y-%m-%d")
            _global_daily_metrics_df = df_all
            print(f"[INFO] Fetched and prepared {len(df_all):,} daily metrics in {time.time()-t0:.2f}s")
        else:
            df_all = _global_daily_metrics_df

        # Filter to tickers_to_fetch in Pandas
        df_filtered = df_all[df_all["ticker"].isin(tickers_to_fetch)]
        
        # Group by ticker and store in cache
        for ticker_symbol, group in df_filtered.groupby("ticker"):
            group_indexed = group.set_index("date")
            group_indexed = group_indexed[~group_indexed.index.duplicated(keep='first')]
            _ticker_daily_ohlc_cache[ticker_symbol] = group_indexed
            
        # Ensure that any tickers that returned no data are cached as empty DataFrames
        # to avoid repeated queries
        for t in tickers_to_fetch:
            if t not in _ticker_daily_ohlc_cache:
                _ticker_daily_ohlc_cache[t] = pd.DataFrame(columns=["rth_high", "rth_low"])
    except Exception as e:
        print(f"[ERROR] Failed to prefetch daily ohlc: {e}")
        # On error, make sure we populate them as empty so we don't block
        for t in tickers_to_fetch:
            if t not in _ticker_daily_ohlc_cache:
                _ticker_daily_ohlc_cache[t] = pd.DataFrame(columns=["rth_high", "rth_low"])



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
@njit(cache=True)
def _fit_ols_numba(x, y):
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0
    
    x_mean = 0.0
    y_mean = 0.0
    for i in range(n):
        x_mean += x[i]
        y_mean += y[i]
    x_mean /= n
    y_mean /= n
    
    num = 0.0
    den = 0.0
    for i in range(n):
        dx = x[i] - x_mean
        dy = y[i] - y_mean
        num += dx * dy
        den += dx * dx
        
    if den == 0.0:
        return 0.0, y_mean, 1.0
        
    slope = num / den
    intercept = y_mean - slope * x_mean
    
    ss_tot = 0.0
    ss_res = 0.0
    for i in range(n):
        y_pred = slope * x[i] + intercept
        ss_tot += (y[i] - y_mean) ** 2
        ss_res += (y[i] - y_pred) ** 2
        
    if ss_tot == 0.0:
        r2 = 1.0
    else:
        r2 = 1.0 - (ss_res / ss_tot)
        
    return slope, intercept, r2


@njit(cache=True)
def _detect_triangles_numba(
    high,
    low,
    close,
    pivot_window,
    lookback,
    slope_tolerance,
    min_r_squared,
    min_pivots,
    pattern_type_code,
):
    n = len(close)
    out = np.zeros(n, dtype=np.float64)
    
    is_sh = np.zeros(n, dtype=np.bool_)
    is_sl = np.zeros(n, dtype=np.bool_)
    
    for i in range(pivot_window, n - pivot_window):
        val_h = high[i]
        is_high = True
        for j in range(i - pivot_window, i):
            if high[j] >= val_h:
                is_high = False
                break
        if is_high:
            for j in range(i + 1, i + pivot_window + 1):
                if high[j] > val_h:
                    is_high = False
                    break
        is_sh[i] = is_high
        
        val_l = low[i]
        is_low = True
        for j in range(i - pivot_window, i):
            if low[j] <= val_l:
                is_low = False
                break
        if is_low:
            for j in range(i + 1, i + pivot_window + 1):
                if low[j] < val_l:
                    is_low = False
                    break
        is_sl[i] = is_low

    for t in range(0, n):
        close_t = close[t]
        if close_t <= 0.0 or np.isnan(close_t):
            continue
            
        start_idx = t - lookback
        end_idx = t - pivot_window
        
        if end_idx < start_idx:
            continue
            
        sh_indices = np.empty(lookback, dtype=np.float64)
        sh_prices = np.empty(lookback, dtype=np.float64)
        sh_count = 0
        for i in range(start_idx, end_idx + 1):
            if is_sh[i]:
                sh_indices[sh_count] = float(i)
                sh_prices[sh_count] = high[i] / close_t
                sh_count += 1
                
        sl_indices = np.empty(lookback, dtype=np.float64)
        sl_prices = np.empty(lookback, dtype=np.float64)
        sl_count = 0
        for i in range(start_idx, end_idx + 1):
            if is_sl[i]:
                sl_indices[sl_count] = float(i)
                sl_prices[sl_count] = low[i] / close_t
                sl_count += 1
                
        if sh_count < min_pivots or sl_count < min_pivots:
            continue
            
        # Ensure the pattern has just been confirmed on the current bar t
        last_high_confirm = sh_indices[sh_count - 1] + pivot_window
        last_low_confirm = sl_indices[sl_count - 1] + pivot_window
        if last_high_confirm != t and last_low_confirm != t:
            continue
            
        slope_R, intercept_R, r2_R = _fit_ols_numba(sh_indices[:sh_count], sh_prices[:sh_count])
        slope_S, intercept_S, r2_S = _fit_ols_numba(sl_indices[:sl_count], sl_prices[:sl_count])
        
        if r2_R < min_r_squared or r2_S < min_r_squared:
            continue
            
        y_R_t = slope_R * t + intercept_R
        y_S_t = slope_S * t + intercept_S
        if y_R_t <= y_S_t:
            continue
            
        # Convert slopes to percentage total change over the lookback window
        slope_R_pct = slope_R * lookback * 100.0
        slope_S_pct = slope_S * lookback * 100.0
        
        is_pattern = False
        if pattern_type_code == 1:
            # Ascending: flat resistance, rising support
            if abs(slope_R_pct) <= slope_tolerance and slope_S_pct > slope_tolerance:
                is_pattern = True
        elif pattern_type_code == 2:
            # Descending: falling resistance, flat support
            if slope_R_pct < -slope_tolerance and abs(slope_S_pct) <= slope_tolerance:
                is_pattern = True
        elif pattern_type_code == 3:
            # Symmetric: falling resistance, rising support
            if slope_R_pct < -slope_tolerance and slope_S_pct > slope_tolerance:
                is_pattern = True
                
        if is_pattern:
            out[t] = 1.0
            
    return out


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

# Normalize frontend indicator names to backend names
INDICATOR_NAME_MAP = {
    # Price Variables — nuevos nombres del frontend
    "Bar Close": "Close",
    "Bar Open": "Open",
    "High Bar": "High",
    "Low Bar": "Low",
    "PM Open": "PM Open",
    "PM High": "Pre-Market High",
    "PM Low": "Pre-Market Low",
    "RTH Open": "RTH Open",
    "RTH High": "RTH High",
    "RTH Low": "RTH Low",
    "AM Open": "AM Open",
    "Previous max": "Previous max",
    "Previous min": "Previous min",
    "Yesterday Open": "Yesterday Open",
    "Yesterday Close": "Yesterday Close",
    "Yesterday High": "Yesterday High",
    "Yesterday Low": "Yesterday Low",
    "Yesterday AM High": "Yesterday AM High",
    "Yesterday AM Low": "Yesterday AM Low",
    "High of last X days": "Max of last X days",
    "Low of last X days": "Min of last X days",

    # Behaviour & Patterns
    "Consecutive higher highs": "Consecutive Higher Highs",
    "Consecutive lower lows": "Consecutive Lower Lows",
    "Consecutive lower highs": "Consecutive Lower Highs",
    "Consecutive higher lows": "Consecutive Higher Lows",
    "Consecutive green candles": "Consecutive Green Candles",
    "Consecutive red candles": "Consecutive Red Candles",
    
    # Abbreviated label aliases
    "Consec Higher Highs": "Consecutive Higher Highs",
    "Consec Lower Lows": "Consecutive Lower Lows",
    "Consec Lower Highs": "Consecutive Lower Highs",
    "Consec Higher Lows": "Consecutive Higher Lows",
    "Consec Green Candles": "Consecutive Green Candles",
    "Consec Red Candles": "Consecutive Red Candles",
    "Candle Range %": "Candle Range %",
    "Range of time": "Range of time",
    "Opening range +": "Opening Range +",
    "Opening range -": "Opening Range -",
    "Opening range AM +": "Opening Range AM +",
    "Opening range AM -": "Opening Range AM -",
    "Elapsed time from last High": "Elapsed Time from Last High",
    "Triangle Ascending": "Triangle Ascending",
    "Triangle Descending": "Triangle Descending",
    "Triangle Symmetric": "Triangle Symmetric",

    # Indicators
    "Donchian": "Donchian Channels",
    "Bollinger Bands": "Bollinger Bands",
    "Accumulated Volume": "Accumulated Volume",
    "Yesterday Volume": "Yesterday Volume",
    "RVOL": "RVOL",

    # Legacy aliases (compatibilidad con estrategias antiguas)
    "Max of last X days": "Max of last X days",
    "Min of last X days": "Min of last X days",
    "Bollinger Upper": "Bollinger Upper",
    "Bollinger Lower": "Bollinger Lower",
    "Bollinger Middle": "Bollinger Middle",
}

def normalize_indicator_name(name: str) -> str:
    return INDICATOR_NAME_MAP.get(name, name)

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
    band_line: str | None = None,
    orb_minutes: int | None = None,
    ap_session: str | None = None,
    daily_stats: dict | None = None,
    cache: dict | None = None,
    range_minutes: int | None = None,
    pivot_window: int | None = None,
    tri_lookback: int | None = None,
    slope_tolerance: float | None = None,
    min_r_squared: float | None = None,
    min_pivots: int | None = None,
) -> pd.Series:
    name = normalize_indicator_name(name)
    cache_key = (name, period, period2, period3, std_dev, multiplier, offset,
                 days_lookback, calc_on_heikin, time_hour, time_minute, time_condition,
                 band_line, orb_minutes, ap_session, range_minutes,
                 pivot_window, tri_lookback, slope_tolerance, min_r_squared, min_pivots)
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
        band_line, orb_minutes, ap_session, daily_stats, df, range_minutes,
        pivot_window, tri_lookback, slope_tolerance, min_r_squared, min_pivots
    )

    if offset and offset != 0:
        result = result.shift(offset)

    if name != "Parabolic SAR" and multiplier is not None:
        result = result * multiplier

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
    band_line: str | None,
    orb_minutes: int | None,
    ap_session: str | None,
    daily_stats: dict | None,
    df: pd.DataFrame,
    range_minutes: int | None = None,
    pivot_window: int | None = None,
    tri_lookback: int | None = None,
    slope_tolerance: float | None = None,
    min_r_squared: float | None = None,
    min_pivots: int | None = None,
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
            return pd.Series(_safe_float(ds["rth_open"]), index=close.index)
        return pd.Series(float(open_.iloc[0]) if len(open_) > 0 else np.nan, index=close.index)
    if name == "Bar Open":
        return open_
    if name == "Yesterday Open":
        return pd.Series(_safe_float(ds.get("yesterday_open", ds.get("lag_rth_open_1", np.nan))), index=close.index)
    if name == "Yesterday Close" or name == "Previous Close":
        return pd.Series(_safe_float(ds.get("previous_close", ds.get("prev_close", ds.get("lag_rth_close_1", np.nan)))), index=close.index)
    if name == "Yesterday High":
        return pd.Series(_safe_float(ds.get("yesterday_high", ds.get("lag_rth_high_1", np.nan))), index=close.index)
    if name == "Yesterday Low":
        return pd.Series(_safe_float(ds.get("yesterday_low", ds.get("lag_rth_low_1", np.nan))), index=close.index)
    if name == "Pre-Market High":
        val = ds.get("pm_high") if ds else None
        if val is None or pd.isna(val):
            timestamps = pd.to_datetime(df["timestamp"])
            pm_mask = (timestamps.dt.hour * 60 + timestamps.dt.minute >= 4 * 60) & (timestamps.dt.hour * 60 + timestamps.dt.minute < 9 * 60 + 30)
            val = df.loc[pm_mask, "high"].max() if pm_mask.any() else np.nan
        return pd.Series(_safe_float(val), index=close.index)

    if name == "Pre-Market Low":
        val = ds.get("pm_low") if ds else None
        if val is None or pd.isna(val):
            timestamps = pd.to_datetime(df["timestamp"])
            pm_mask = (timestamps.dt.hour * 60 + timestamps.dt.minute >= 4 * 60) & (timestamps.dt.hour * 60 + timestamps.dt.minute < 9 * 60 + 30)
            val = df.loc[pm_mask, "low"].min() if pm_mask.any() else np.nan
        return pd.Series(_safe_float(val), index=close.index)
    if name in ("RTH Open", "rth_open"):
        val = ds.get("rth_open") if ds else None
        if val is None or pd.isna(val):
            timestamps = pd.to_datetime(df["timestamp"])
            rth_mask = (timestamps.dt.hour * 60 + timestamps.dt.minute >= 9 * 60 + 30) & (timestamps.dt.hour * 60 + timestamps.dt.minute < 16 * 60)
            rth_open_rows = df.loc[rth_mask]
            val = rth_open_rows["open"].iloc[0] if not rth_open_rows.empty else np.nan
        return pd.Series(_safe_float(val), index=close.index)
    if name in ("RTH High", "rth_high"):
        val = ds.get("rth_high") if ds else None
        if val is None or pd.isna(val):
            timestamps = pd.to_datetime(df["timestamp"])
            rth_mask = (timestamps.dt.hour * 60 + timestamps.dt.minute >= 9 * 60 + 30) & (timestamps.dt.hour * 60 + timestamps.dt.minute < 16 * 60)
            val = df.loc[rth_mask, "high"].max() if rth_mask.any() else np.nan
        return pd.Series(_safe_float(val), index=close.index)
    if name in ("RTH Low", "rth_low"):
        val = ds.get("rth_low") if ds else None
        if val is None or pd.isna(val):
            timestamps = pd.to_datetime(df["timestamp"])
            rth_mask = (timestamps.dt.hour * 60 + timestamps.dt.minute >= 9 * 60 + 30) & (timestamps.dt.hour * 60 + timestamps.dt.minute < 16 * 60)
            val = df.loc[rth_mask, "low"].min() if rth_mask.any() else np.nan
        return pd.Series(_safe_float(val), index=close.index)
    if name == "High of Day":
        return high.cummax()
    if name == "Low of Day":
        return low.cummin()
    if name in ("High of last X days", "Max of last X days", "Low of last X days", "Min of last X days"):
        ticker = ds.get("ticker") if ds else None
        if not ticker:
            return pd.Series(np.nan, index=close.index)
            
        if ds and "date" in ds:
            target_date_str = str(ds["date"])[:10]
        elif len(df) > 0 and "timestamp" in df.columns:
            target_date_str = str(df["timestamp"].iloc[0])[:10]
        else:
            target_date_str = None
            
        if not target_date_str:
            return pd.Series(np.nan, index=close.index)
            
        lookback = days_lookback or period or 5
        
        global _ticker_daily_ohlc_cache
        if ticker not in _ticker_daily_ohlc_cache:
            from app.database import get_db_connection
            con = get_db_connection()
            try:
                df_daily = con.execute(f"""
                    SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
                    FROM daily_metrics 
                    WHERE ticker = '{ticker}' 
                    ORDER BY "timestamp"
                """).fetchdf()
                df_daily["date"] = pd.to_datetime(df_daily["date"]).dt.strftime("%Y-%m-%d")
                df_daily = df_daily.set_index("date")
                df_daily = df_daily[~df_daily.index.duplicated(keep='first')]
                _ticker_daily_ohlc_cache[ticker] = df_daily
            except Exception as e:
                print(f"[ERROR] Failed to load lookback metrics for {ticker}: {e}")
                _ticker_daily_ohlc_cache[ticker] = pd.DataFrame(columns=["rth_high", "rth_low"])
                
        df_daily = _ticker_daily_ohlc_cache[ticker]
        if df_daily.empty or target_date_str not in df_daily.index:
            return pd.Series(np.nan, index=close.index)
            
        pos = df_daily.index.get_loc(target_date_str)
        start_pos = max(0, pos - lookback)
        if start_pos >= pos:
            return pd.Series(np.nan, index=close.index)
            
        if name in ("High of last X days", "Max of last X days"):
            val = df_daily["rth_high"].iloc[start_pos:pos].max()
        else:
            val = df_daily["rth_low"].iloc[start_pos:pos].min()
            
        return pd.Series(_safe_float(val), index=close.index)

    if name == "Previous max":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        minutes = timestamps.dt.minute
        if ap_session == "ap.RTH":
            start_mask = (hours > 9) | ((hours == 9) & (minutes >= 30))
        elif ap_session == "ap.AM":
            start_mask = hours >= 16
        else:  # ap.PM default
            start_mask = pd.Series(True, index=df.index)
        result = pd.Series(np.nan, index=close.index)
        running_max = np.nan
        started = False
        for i in range(len(close)):
            if not started and start_mask.iloc[i]:
                started = True
            if started:
                if np.isnan(running_max):
                    running_max = high.iloc[i]
                else:
                    running_max = max(running_max, high.iloc[i])
                result.iloc[i] = running_max
        return result.shift(1)

    if name == "Previous min":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        minutes = timestamps.dt.minute
        if ap_session == "ap.RTH":
            start_mask = (hours > 9) | ((hours == 9) & (minutes >= 30))
        elif ap_session == "ap.AM":
            start_mask = hours >= 16
        else:  # ap.PM default
            start_mask = pd.Series(True, index=df.index)
        result = pd.Series(np.nan, index=close.index)
        running_min = np.nan
        started = False
        for i in range(len(close)):
            if not started and start_mask.iloc[i]:
                started = True
            if started:
                if np.isnan(running_min):
                    running_min = low.iloc[i]
                else:
                    running_min = min(running_min, low.iloc[i])
                result.iloc[i] = running_min
        return result.shift(1)

    if name == "PM Open":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        minutes = timestamps.dt.minute
        pm_mask = (hours < 9) | ((hours == 9) & (minutes < 30))
        pm_bars = open_[pm_mask]
        if len(pm_bars) > 0:
            pm_open_val = float(pm_bars.iloc[0])
        else:
            pm_open_val = _safe_float(ds.get("rth_open", np.nan))
        return pd.Series(pm_open_val, index=close.index)

    if name == "AM Open":
        timestamps = pd.to_datetime(df["timestamp"])
        hours = timestamps.dt.hour
        am_mask = hours >= 16
        am_bars = open_[am_mask]
        if len(am_bars) > 0:
            am_open_val = float(am_bars.iloc[0])
        else:
            am_open_val = np.nan
        return pd.Series(am_open_val, index=close.index)

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
        period = period or 20
        sd = std_dev or 2.0
        upper, middle, lower = _bollinger_bands(close.values.astype(np.float64), period, sd)
        if band_line == "Lower":
            return pd.Series(lower, index=close.index)
        elif band_line == "Basis":
            return pd.Series(middle, index=close.index)
        else:  # Upper es default
            return pd.Series(upper, index=close.index)

    if name == "Bollinger Middle":
        sd = std_dev or 2.0
        _, middle, _ = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(middle, index=close.index)

    if name == "Bollinger Lower":
        sd = std_dev or 2.0
        _, _, lower = _bollinger_bands(close.values.astype(np.float64), period or 20, sd)
        return pd.Series(lower, index=close.index)

    if name == "Donchian Channels":
        period = period or 20
        upper = high.rolling(period).max().shift(1)
        lower = low.rolling(period).min().shift(1)
        mid = (upper + lower) / 2
        if band_line == "Lower":
            return lower
        elif band_line == "Basis":
            return mid
        else:  # Upper es default
            return upper

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

    if name == "RVOL by bar" or name == "RVOL":
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

    if name == "Consecutive Lower Highs":
        lh = np.empty(len(high), dtype=np.bool_)
        lh[0] = False
        lh[1:] = high.values[1:] < high.values[:-1]
        return pd.Series(_consecutive_count(lh), index=close.index)

    if name == "Consecutive Lower Lows":
        ll = np.empty(len(low), dtype=np.bool_)
        ll[0] = False
        ll[1:] = low.values[1:] < low.values[:-1]
        return pd.Series(_consecutive_count(ll), index=close.index)

    if name == "Consecutive Higher Lows":
        hl = np.empty(len(low), dtype=np.bool_)
        hl[0] = False
        hl[1:] = low.values[1:] > low.values[:-1]
        return pd.Series(_consecutive_count(hl), index=close.index)

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

    if name == "Range of time" or name == "Range of Time":
        timestamps = pd.to_datetime(df["timestamp"])
        if len(timestamps) > 0:
            dates = timestamps.dt.normalize()
            rth_start = dates + pd.to_timedelta("9h 30m")
            am_start = dates + pd.to_timedelta("16h")
            first_candle_of_day = pd.to_datetime(df.groupby(dates)["timestamp"].transform("first"))
            
            is_rth = (timestamps >= rth_start) & (timestamps < am_start)
            is_am = timestamps >= am_start
            
            start_times = pd.Series(first_candle_of_day, index=df.index)
            start_times = start_times.mask(is_rth, rth_start)
            start_times = start_times.mask(is_am, am_start)
            
            elapsed = (timestamps - start_times).dt.total_seconds() / 60.0
            return elapsed.clip(lower=0.0)
        else:
            return pd.Series(0.0, index=close.index)

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

    if name in ("Opening Range +", "Opening Range", "Opening Range Plus",
                "Opening Range -", "Opening Range Minus",
                "Opening Range AM +", "Opening Range AM Plus",
                "Opening Range AM -", "Opening Range AM Minus"):
        n_mins = int(orb_minutes) if orb_minutes else 30
        timestamps = pd.to_datetime(df["timestamp"])
        
        result = pd.Series(np.nan, index=close.index)
        is_am = "AM" in name
        is_minus = name.endswith("-") or name.endswith("Minus")
        
        dates = timestamps.dt.normalize()
        minutes_of_day = timestamps.dt.hour * 60 + timestamps.dt.minute
        
        for date, group_indices in df.groupby(dates).groups.items():
            group_minutes = minutes_of_day.loc[group_indices]
            
            if is_am:
                session_start = 960
                session_end = 1440
            else:
                session_start = 570
                session_end = 960
                
            session_mask = (group_minutes >= session_start) & (group_minutes < session_end)
            if not session_mask.any():
                continue
                
            orb_mask = session_mask & (group_minutes < session_start + n_mins)
            if not orb_mask.any():
                continue
                
            orb_indices = group_minutes[orb_mask].index
            
            if is_minus:
                range_val = low.loc[orb_indices].min()
            else:
                range_val = high.loc[orb_indices].max()
                
            trading_mask = session_mask & (group_minutes >= session_start + n_mins)
            trading_indices = group_minutes[trading_mask].index
            
            result.loc[trading_indices] = float(range_val)
            
        return result


    if name == "Yesterday Volume":
        yesterday_volume = ds.get("eod_volume", np.nan)
        return pd.Series(float(yesterday_volume), index=close.index)

    if name == "Candle Range %":
        candle_range = ((close - open_) / open_.abs()) * 100
        return candle_range.abs()

    if name in ("Elapsed Time from Last High", "Elapsed time from last High"):
        elapsed = pd.Series(0, index=close.index, dtype=float)
        last_high_idx = 0
        current_high = high.iloc[0] if len(high) > 0 else 0
        for i in range(len(high)):
            if high.iloc[i] > current_high:
                current_high = high.iloc[i]
                last_high_idx = i
            elapsed.iloc[i] = i - last_high_idx
        return elapsed

    if name in ("Triangle Ascending", "Triangle Descending", "Triangle Symmetric"):
        pw = pivot_window or 5
        lb = tri_lookback or 35
        st = slope_tolerance or 1.5
        mr = min_r_squared or 0.65
        mp = min_pivots or 2
        
        pattern_code = 1
        if name == "Triangle Descending":
            pattern_code = 2
        elif name == "Triangle Symmetric":
            pattern_code = 3
            
        vals = _detect_triangles_numba(
            high.values.astype(np.float64),
            low.values.astype(np.float64),
            close.values.astype(np.float64),
            pw,
            lb,
            st,
            mr,
            mp,
            pattern_code
        )
        return pd.Series(vals, index=close.index)

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
