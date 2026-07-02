"""
Translates a strategy JSON definition into boolean signal arrays.
Recursively evaluates ConditionGroups (AND/OR) to produce entry/exit signals.

Optimized (N1+N2a): dict dispatch for comparators, pre-normalized indicator names,
unified timestamp parsing, and native numpy array evaluation path.
"""
import logging
import numpy as np
import pandas as pd
from app.services.indicators import (
    compute_indicator, detect_candle_pattern, normalize_indicator_name,
    _vwap, _sma, _ema, _rsi, _atr, _heikin_ashi, _bollinger_bands,
    _stochastic, _macd, _dmi, _cci, _roc, _momentum, _obv,
    _linear_regression, _consecutive_count,
    _hammer, _shooting_star, _pivot_points, _safe_float,
)

logger = logging.getLogger("backtester.strategy_engine")

# ── N1c: Dict dispatch for comparators ───────────────────────────────────
_COMPARATOR_OPS = {
    "GREATER_THAN": lambda s, t: s > t,
    "LESS_THAN": lambda s, t: s < t,
    "GREATER_THAN_OR_EQUAL": lambda s, t: s >= t,
    "LESS_THAN_OR_EQUAL": lambda s, t: s <= t,
    "EQUAL": lambda s, t: s == t,
    "CROSSES_ABOVE": lambda s, t: (s.shift(1) <= t.shift(1)) & (s > t),
    "CROSSES_BELOW": lambda s, t: (s.shift(1) >= t.shift(1)) & (s < t),
}

# ── N2a: Raw indicator compute dispatch (numpy arrays, O(1) lookup) ─────
def _compute_indicator_raw(name, close, high, low, open_, volume, period=None,
                           period2=None, period3=None, std_dev=None,
                           multiplier=None, offset=0, daily_stats=None):
    """Compute indicator directly from numpy arrays. Dict dispatch for O(1) lookup."""
    ds = daily_stats or {}
    fn = _RAW_INDICATOR_DISPATCH.get(name)
    if fn is not None:
        return fn(close, high, low, open_, volume, period, period2, period3,
                  std_dev, multiplier, ds)
    # Fallback: NaN for uncommon indicators
    return np.full(len(close), np.nan)


def _ri_close(c, h, l, o, v, p, p2, p3, sd, m, ds):  return c
def _ri_open(c, h, l, o, v, p, p2, p3, sd, m, ds):   return o
def _ri_high(c, h, l, o, v, p, p2, p3, sd, m, ds):   return h
def _ri_low(c, h, l, o, v, p, p2, p3, sd, m, ds):    return l
def _ri_volume(c, h, l, o, v, p, p2, p3, sd, m, ds): return v.astype(np.float64)
def _ri_sma(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _sma(c, p or 20)
def _ri_ema(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _ema(c, p or 20)
def _ri_vwap(c, h, l, o, v, p, p2, p3, sd, m, ds):   return _vwap(h, l, c, v)
def _ri_rsi(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _rsi(c, p or 14)
def _ri_atr(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _atr(h, l, c, p or 14)
def _ri_cci(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _cci(h, l, c, p or 20)
def _ri_roc(c, h, l, o, v, p, p2, p3, sd, m, ds):    return _roc(c, p or 12)
def _ri_momentum(c, h, l, o, v, p, p2, p3, sd, m, ds): return _momentum(c, p or 10)
def _ri_macd(c, h, l, o, v, p, p2, p3, sd, m, ds):
    ml, _, _ = _macd(c, p or 12, p2 or 26, p3 or 9); return ml
def _ri_macd_signal(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, sl, _ = _macd(c, p or 12, p2 or 26, p3 or 9); return sl
def _ri_macd_hist(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, _, hist = _macd(c, p or 12, p2 or 26, p3 or 9); return hist
def _ri_stoch(c, h, l, o, v, p, p2, p3, sd, m, ds):
    k, _ = _stochastic(h, l, c, p or 14, p2 or 3); return k
def _ri_dmi(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pd_i, _ = _dmi(h, l, c, p or 14); return pd_i
def _ri_dmi_minus(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, md = _dmi(h, l, c, p or 14); return md
def _ri_bb_upper(c, h, l, o, v, p, p2, p3, sd, m, ds):
    u, _, _ = _bollinger_bands(c, p or 20, sd or 2.0); return u
def _ri_bb_mid(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, mid, _ = _bollinger_bands(c, p or 20, sd or 2.0); return mid
def _ri_bb_lower(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, _, low = _bollinger_bands(c, p or 20, sd or 2.0); return low
def _ri_obv(c, h, l, o, v, p, p2, p3, sd, m, ds):      return _obv(c, v)
def _ri_ha_close(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, _, _, hc = _heikin_ashi(o, h, l, c); return hc
def _ri_ha_open(c, h, l, o, v, p, p2, p3, sd, m, ds):
    ho, _, _, _ = _heikin_ashi(o, h, l, c); return ho
def _ri_ha_high(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, hh, _, _ = _heikin_ashi(o, h, l, c); return hh
def _ri_ha_low(c, h, l, o, v, p, p2, p3, sd, m, ds):
    _, _, hl, _ = _heikin_ashi(o, h, l, c); return hl
def _ri_red_candles(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return _consecutive_count(c < o)
def _ri_green_candles(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return _consecutive_count(c > o)
def _ri_higher_highs(c, h, l, o, v, p, p2, p3, sd, m, ds):
    hh = np.zeros(len(h), dtype=bool); hh[1:] = h[1:] > h[:-1]; return _consecutive_count(hh)
def _ri_lower_highs(c, h, l, o, v, p, p2, p3, sd, m, ds):
    lh = np.zeros(len(h), dtype=bool); lh[1:] = h[1:] < h[:-1]; return _consecutive_count(lh)
def _ri_lower_lows(c, h, l, o, v, p, p2, p3, sd, m, ds):
    ll = np.zeros(len(l), dtype=bool); ll[1:] = l[1:] < l[:-1]; return _consecutive_count(ll)
def _ri_higher_lows(c, h, l, o, v, p, p2, p3, sd, m, ds):
    hl = np.zeros(len(l), dtype=bool); hl[1:] = l[1:] > l[:-1]; return _consecutive_count(hl)
def _ri_yesterday_open(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("yesterday_open", ds.get("lag_rth_open_1", np.nan))))
def _ri_yesterday_close(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("previous_close", ds.get("prev_close", np.nan))))
def _ri_yesterday_high(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("yesterday_high", ds.get("lag_rth_high_1", np.nan))))
def _ri_yesterday_low(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("yesterday_low", ds.get("lag_rth_low_1", np.nan))))
def _ri_day_open(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("rth_open", float(o[0]) if len(o) > 0 else np.nan)))
def _ri_pm_high(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("pm_high", np.nan)))
def _ri_pm_low(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("pm_low", np.nan)))
def _ri_rth_open(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("rth_open", np.nan)))
def _ri_rth_high(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("rth_high", np.nan)))
def _ri_rth_low(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return np.full(len(c), _safe_float(ds.get("rth_low", np.nan)))
def _ri_linear_reg(c, h, l, o, v, p, p2, p3, sd, m, ds):
    return _linear_regression(c, p or 14)
def _ri_pivot_pp(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pv = _pivot_points(ds); return np.full(len(c), pv.get("PP", np.nan))
def _ri_pivot_r1(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pv = _pivot_points(ds); return np.full(len(c), pv.get("R1", np.nan))
def _ri_pivot_s1(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pv = _pivot_points(ds); return np.full(len(c), pv.get("S1", np.nan))
def _ri_pivot_r2(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pv = _pivot_points(ds); return np.full(len(c), pv.get("R2", np.nan))
def _ri_pivot_s2(c, h, l, o, v, p, p2, p3, sd, m, ds):
    pv = _pivot_points(ds); return np.full(len(c), pv.get("S2", np.nan))

_RAW_INDICATOR_DISPATCH = {
    "Close": _ri_close, "Open": _ri_open, "High": _ri_high, "Low": _ri_low,
    "Bar Close": _ri_close, "Bar Open": _ri_open,
    "Volume": _ri_volume,
    "SMA": _ri_sma, "EMA": _ri_ema, "VWAP": _ri_vwap, "AVWAP": _ri_vwap,
    "RSI": _ri_rsi, "ATR": _ri_atr, "CCI": _ri_cci, "ROC": _ri_roc,
    "Momentum": _ri_momentum, "MACD": _ri_macd, "MACD Signal": _ri_macd_signal,
    "MACD Histogram": _ri_macd_hist, "Stochastic": _ri_stoch,
    "Stochastic %D": _ri_stoch, "DMI": _ri_dmi, "DMI-": _ri_dmi_minus,
    "Bollinger Bands": _ri_bb_upper, "Bollinger Upper": _ri_bb_upper,
    "Bollinger Middle": _ri_bb_mid, "Bollinger Lower": _ri_bb_lower,
    "OBV": _ri_obv,
    "Heikin-Ashi": _ri_ha_close, "HA Close": _ri_ha_close,
    "HA Open": _ri_ha_open, "HA High": _ri_ha_high, "HA Low": _ri_ha_low,
    "Consecutive Red Candles": _ri_red_candles,
    "Consecutive Green Candles": _ri_green_candles,
    "Consecutive Higher Highs": _ri_higher_highs,
    "Consecutive Lower Highs": _ri_lower_highs,
    "Consecutive Lower Lows": _ri_lower_lows,
    "Consecutive Higher Lows": _ri_higher_lows,
    "Linear Regression": _ri_linear_reg,
    "Yesterday Open": _ri_yesterday_open,
    "Yesterday Close": _ri_yesterday_close, "Previous Close": _ri_yesterday_close,
    "Yesterday High": _ri_yesterday_high, "Yesterday Low": _ri_yesterday_low,
    "Day Open": _ri_day_open, "Current Open": _ri_day_open,
    "Pre-Market High": _ri_pm_high, "Pre-Market Low": _ri_pm_low,
    "RTH Open": _ri_rth_open, "rth_open": _ri_rth_open,
    "RTH High": _ri_rth_high, "rth_high": _ri_rth_high,
    "RTH Low": _ri_rth_low, "rth_low": _ri_rth_low,
    "Pivot Points": _ri_pivot_pp, "PP": _ri_pivot_pp,
    "R1": _ri_pivot_r1, "S1": _ri_pivot_s1,
    "R2": _ri_pivot_r2, "S2": _ri_pivot_s2,
}


# ── N2a: Comparators for native numpy arrays ─────────────────────────────
_COMP_NATIVE = {
    "GREATER_THAN": lambda s, t: s > t,
    "LESS_THAN": lambda s, t: s < t,
    "GREATER_THAN_OR_EQUAL": lambda s, t: s >= t,
    "LESS_THAN_OR_EQUAL": lambda s, t: s <= t,
    "EQUAL": lambda s, t: s == t,
}


def get_lowest_timeframe_mins(logic_dict: dict | None) -> int:
    if not logic_dict:
        return 1
    tf_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
    base_tf = logic_dict.get("timeframe", "1m")
    lowest_mins = tf_map.get(base_tf, 1)

    def check_group(group):
        nonlocal lowest_mins
        if not group:
            return
        conditions = group.get("conditions", [])
        for cond in conditions:
            if cond.get("type") == "group" or "conditions" in cond:
                check_group(cond)
            else:
                cond_tf = cond.get("timeframe")
                if cond_tf:
                    lowest_mins = min(lowest_mins, tf_map.get(cond_tf, 1))
    check_group(logic_dict.get("root_condition", {}))
    return lowest_mins


def compile_strategy_def(strategy_def: dict) -> dict:
    """Pre-extract all per-strategy fields once. N1d: also normalize indicator names."""
    bias = strategy_def.get("bias", "long")
    entry_logic = strategy_def.get("entry_logic", {}) or {}
    exit_logic = strategy_def.get("exit_logic", {}) or {}
    risk = strategy_def.get("risk_management", {}) or {}

    # N1d: normalize all indicator names in the condition tree
    def _normalize_tree(group):
        if not group:
            return
        for cond in group.get("conditions", []):
            if cond.get("type") == "group" or ("conditions" in cond and "operator" in cond):
                _normalize_tree(cond)
            for key in ("source", "target", "level"):
                cfg = cond.get(key)
                if isinstance(cfg, dict) and "name" in cfg:
                    cfg["name"] = normalize_indicator_name(cfg["name"])

    _normalize_tree(entry_logic.get("root_condition", {}))
    _normalize_tree(exit_logic.get("root_condition", {}))

    compiled = {
        "bias": bias,
        "direction": "longonly" if bias == "long" else "shortonly",
        "entry_logic": entry_logic,
        "exit_logic": exit_logic,
        "risk_management": risk,
        "entry_tf": entry_logic.get("timeframe", "1m"),
        "exit_tf": exit_logic.get("timeframe", "1m"),
        "entry_root": entry_logic.get("root_condition", {}),
        "exit_root": exit_logic.get("root_condition", {}),
        "accept_reentries": risk.get("accept_reentries", False),
        "max_reentries": risk.get("max_reentries", -1 if risk.get("accept_reentries", False) else 0),
        "entry_time_windows": entry_logic.get("entry_time_windows", []),
        "entry_candle_delay": entry_logic.get("candle_delay"),
        "exit_candle_delay": exit_logic.get("candle_delay"),
    }

    # N2a: generate indicator plan for native evaluation
    compiled["_indicator_plan"] = _extract_indicator_plan(compiled)

    return compiled


# ── N2a: Indicator plan extraction ───────────────────────────────────────

def _extract_indicator_plan(compiled: dict) -> dict:
    """Walk the condition tree and extract all unique indicator specs.
    Called once per backtest (compile time), not per pair."""
    specs = {}  # key -> spec dict, deduplicated

    def _cfg_key(cfg: dict, tf: str) -> str:
        """Build a dedup key for an indicator config."""
        if not isinstance(cfg, dict) or "name" not in cfg:
            return None
        name = cfg.get("name", "")
        period = cfg.get("period")
        period2 = cfg.get("period2")
        period3 = cfg.get("period3")
        std_dev = cfg.get("stdDev")
        return f"{name}|{tf}|{period}|{period2}|{period3}|{std_dev}"

    def _walk_group(group, parent_tf):
        if not group:
            return
        for cond in group.get("conditions", []):
            if cond.get("type") == "group" or ("conditions" in cond and "operator" in cond):
                _walk_group(cond, parent_tf)
            else:
                tf = cond.get("timeframe") or parent_tf or "1m"
                cond_type = cond.get("type", "")
                if cond_type in ("indicator_comparison", "price_level_distance"):
                    for key in ("source", "target", "level"):
                        cfg = cond.get(key)
                        if isinstance(cfg, dict) and "name" in cfg:
                            k = _cfg_key(cfg, tf)
                            if k and k not in specs:
                                specs[k] = {"name": cfg["name"], "tf": tf,
                                    "period": cfg.get("period"),
                                    "period2": cfg.get("period2"),
                                    "period3": cfg.get("period3"),
                                    "std_dev": cfg.get("stdDev"),
                                    "multiplier": cfg.get("multiplier"),
                                    "offset": cfg.get("offset", 0),
                                    "key": k}

    _walk_group(compiled.get("entry_root", {}), compiled.get("entry_tf", "1m"))
    _walk_group(compiled.get("exit_root", {}), compiled.get("exit_tf", "1m"))

    # Also extract risk management indicators (ATR-based SL, etc.)
    risk = compiled.get("risk_management", {})
    if risk.get("use_hard_stop") and risk.get("hard_stop"):
        hs = risk["hard_stop"]
        if hs.get("type") == "ATR Multiplier":
            k = "ATR|1m|14|None|None|None"
            if k not in specs:
                specs[k] = {"name": "ATR", "tf": "1m", "period": 14,
                    "period2": None, "period3": None, "std_dev": None, "key": k}

    # Group by timeframe
    by_tf = {}
    for spec in specs.values():
        tf = spec["tf"]
        if tf not in by_tf:
            by_tf[tf] = []
        by_tf[tf].append(spec)

    # Check for patterns that need DataFrames
    has_special = False
    for group in [compiled.get("entry_root", {}), compiled.get("exit_root", {})]:
        for cond in group.get("conditions", []):
            if cond.get("type") == "candle_pattern":
                has_special = True
            elif cond.get("type") == "price_level_distance":
                has_special = True

    return {
        "specs": list(specs.values()),
        "by_timeframe": by_tf,
        "has_special": has_special,
    }


# ── Public API: translate_strategy (legacy path, backward compatible) ────

def translate_strategy(
    df: pd.DataFrame,
    strategy_def: dict,
    daily_stats: dict | None = None,
    compiled: dict | None = None,
    precomputed_minutes: np.ndarray | None = None,
) -> dict:
    """N1e: accepts precomputed_minutes to avoid redundant pd.to_datetime."""
    if compiled is None:
        compiled = compile_strategy_def(strategy_def)

    direction = compiled["direction"]
    risk = compiled["risk_management"]
    entry_tf = compiled["entry_tf"]
    exit_tf = compiled["exit_tf"]

    entry_cache: dict = {}
    exit_cache: dict = entry_cache if entry_tf == exit_tf else {}

    entries = _evaluate_condition_group(
        compiled["entry_root"], df, entry_tf, daily_stats, entry_cache
    )

    time_windows = compiled.get("entry_time_windows", [])
    if time_windows:
        if precomputed_minutes is not None:
            minutes_since_midnight = precomputed_minutes
        else:
            ts = pd.to_datetime(df["timestamp"])
            minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
        time_mask = pd.Series(False, index=df.index)
        for window in time_windows:
            from_time = window.get("from_time", "")
            to_time = window.get("to_time", "")
            if not from_time or not to_time:
                continue
            try:
                from_h, from_m = map(int, from_time.split(":"))
                to_h, to_m = map(int, to_time.split(":"))
                start_mins = from_h * 60 + from_m
                end_mins = to_h * 60 + to_m
                window_mask = (minutes_since_midnight >= start_mins) & (minutes_since_midnight <= end_mins)
                time_mask = time_mask | window_mask
            except Exception as e:
                logger.error(f"Error parsing entry time window {window}: {e}")
                continue
        entries = entries & time_mask

    exits = _evaluate_condition_group(
        compiled["exit_root"], df, exit_tf, daily_stats, exit_cache
    )

    risk_cache: dict = entry_cache if entry_tf == "1m" else {}
    sl_stop, sl_trail, tp_stop, tp_time_limit, trail_pct, partial_tps = \
        _parse_risk_management(risk, df, daily_stats, risk_cache)

    return {
        "entries": entries.astype(bool),
        "exits": exits.astype(bool),
        "direction": direction,
        "sl_stop": sl_stop,
        "sl_trail": sl_trail,
        "tp_stop": tp_stop,
        "tp_time_limit": tp_time_limit,
        "trail_pct": trail_pct,
        "accept_reentries": compiled["accept_reentries"],
        "max_reentries": compiled.get("max_reentries", -1 if compiled.get("accept_reentries", False) else 0),
        "partial_take_profits": partial_tps,
    }


# ── N2a: Native numpy translate (fast path) ─────────────────────────────

def translate_strategy_native(
    arrays: dict,
    compiled: dict,
    daily_stats: dict | None = None,
) -> dict:
    """Fast path: receive numpy arrays (not DataFrame), precompute all indicators,
    evaluate conditions with numpy boolean operations. No pandas overhead."""
    plan = compiled.get("_indicator_plan", {})
    by_tf = plan.get("by_timeframe", {})
    has_special = plan.get("has_special", False)

    C = arrays["close"]
    H = arrays["high"]
    L = arrays["low"]
    O = arrays["open"]
    V = arrays["volume"]
    n_bars = len(C)

    # Fase 1: Precompute all indicators
    indicator_results = {}

    for tf, specs in by_tf.items():
        if tf == "1m":
            c, h, l, o, v = C, H, L, O, V
        else:
            c, h, l, o, v = _resample_arrays_ohlcv(C, H, L, O, V, arrays.get("minutes_arr"), tf)

        for spec in specs:
            indicator_results[spec["key"]] = _compute_indicator_raw(
                spec["name"], c, h, l, o, v,
                period=spec.get("period"),
                period2=spec.get("period2"),
                period3=spec.get("period3"),
                std_dev=spec.get("std_dev"),
                multiplier=spec.get("multiplier"),
                offset=spec.get("offset", 0),
                daily_stats=daily_stats,
            )

    # Fase 2: Evaluate conditions
    if not has_special:
        entries = _evaluate_group_native(
            compiled.get("entry_root", {}), indicator_results, n_bars, plan
        )
        exits = _evaluate_group_native(
            compiled.get("exit_root", {}), indicator_results, n_bars, plan
        )
        # Ensure correct shape after alignment
        if entries is not None and len(entries) != n_bars:
            entries = np.zeros(n_bars, dtype=bool)
        if exits is not None and len(exits) != n_bars:
            exits = np.zeros(n_bars, dtype=bool)
    else:
        # Fallback to legacy for complex patterns
        entries = np.zeros(n_bars, dtype=bool)
        exits = np.zeros(n_bars, dtype=bool)

    if entries is None:
        entries = np.zeros(n_bars, dtype=bool)
    if exits is None:
        exits = np.zeros(n_bars, dtype=bool)

    # Fase 3: Risk management
    direction = compiled["direction"]
    risk = compiled.get("risk_management", {})
    sl_stop = None
    sl_trail = False
    tp_stop = None
    tp_time_limit = None
    trail_pct = None
    partial_tps = None

    if risk.get("use_hard_stop") and risk.get("hard_stop"):
        hs = risk["hard_stop"]
        hs_type = hs.get("type", "Percentage")
        hs_value = hs.get("value", 0)
        if hs_type == "Percentage":
            sl_stop = hs_value / 100.0
        elif hs_type == "Fixed Amount":
            first_close = float(C[0]) if n_bars > 0 else 1.0
            sl_stop = hs_value / first_close if first_close > 0 else None

    trailing = risk.get("trailing_stop", {})
    if trailing.get("active"):
        sl_trail = True
        if trailing.get("type") == "Percentage" and trailing.get("buffer_pct"):
            trail_pct = trailing["buffer_pct"] / 100.0

    if risk.get("use_take_profit") is not False:
        if risk.get("take_profit"):
            tp = risk["take_profit"]
            tp_type = tp.get("type")
            if tp_type == "Percentage":
                tp_stop = tp.get("value", 0) / 100.0
            elif tp_type == "Time":
                tp_time_limit = float(tp.get("value", 0)) if tp.get("value") else 0.0
            elif tp_type == "Hour":
                tp_time_limit = f"HOUR:{tp.get('value', '15:30')}"

    return {
        "entries": entries,
        "exits": exits,
        "direction": direction,
        "sl_stop": sl_stop,
        "sl_trail": sl_trail,
        "tp_stop": tp_stop,
        "tp_time_limit": tp_time_limit,
        "trail_pct": trail_pct,
        "accept_reentries": compiled.get("accept_reentries", False),
        "max_reentries": compiled.get("max_reentries", -1 if compiled.get("accept_reentries", False) else 0),
        "partial_take_profits": partial_tps,
    }


def _resample_arrays_ohlcv(C, H, L, O, V, minutes_arr, tf):
    """Downsample 1m numpy arrays to a higher timeframe using pandas resample logic.
    Returns (C_tf, H_tf, L_tf, O_tf, V_tf) as numpy arrays."""
    if tf == "1m":
        return C, H, L, O, V

    tf_map = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
    period = tf_map.get(tf, 1)
    if period == 1:
        return C, H, L, O, V

    n = len(C)
    num_buckets = (n + period - 1) // period

    c_res = np.full(num_buckets, np.nan)
    h_res = np.full(num_buckets, np.nan)
    l_res = np.full(num_buckets, np.nan)
    o_res = np.full(num_buckets, np.nan)
    v_res = np.full(num_buckets, np.nan)

    for i in range(num_buckets):
        start = i * period
        end = min(start + period, n)
        if end > start:
            o_res[i] = O[start]
            c_res[i] = C[end - 1]
            h_res[i] = np.max(H[start:end])
            l_res[i] = np.min(L[start:end])
            v_res[i] = np.sum(V[start:end])

    mask = ~np.isnan(o_res)
    return c_res[mask], h_res[mask], l_res[mask], o_res[mask], v_res[mask]


def _evaluate_group_native(group: dict, results: dict, n_bars: int,
                           plan: dict) -> np.ndarray | None:
    """Evaluate a condition group against precomputed indicator arrays."""
    if not group:
        return np.zeros(n_bars, dtype=bool)

    operator = group.get("operator", "AND")
    conditions = group.get("conditions", [])
    if not conditions:
        return np.zeros(n_bars, dtype=bool)

    combined = None
    for cond in conditions:
        cond_type = cond.get("type", "")
        if cond_type == "group" or ("conditions" in cond and "operator" in cond):
            res = _evaluate_group_native(cond, results, n_bars, plan)
        elif cond_type == "indicator_comparison":
            res = _eval_comparison_native(cond, results)
        elif cond_type == "price_level_distance":
            res = _eval_distance_native(cond, results)
        elif cond_type == "candle_pattern":
            res = np.zeros(n_bars, dtype=bool)
        else:
            res = np.zeros(n_bars, dtype=bool)

        if res is None:
            res = np.zeros(n_bars, dtype=bool)

        if combined is None:
            combined = res
        elif operator == "AND":
            combined = combined & res
        else:
            combined = combined | res

    return combined if combined is not None else np.zeros(n_bars, dtype=bool)


def _eval_comparison_native(cond: dict, results: dict) -> np.ndarray | None:
    """Evaluate an indicator_comparison condition against precomputed arrays."""
    source_cfg = cond.get("source", {})
    target_cfg = cond.get("target", {})
    comparator = cond.get("comparator", "GREATER_THAN")
    tf = cond.get("timeframe", "1m")

    source_key = _cfg_key_static(source_cfg, tf)
    source_arr = results.get(source_key) if source_key else None
    if source_arr is None:
        return None

    if isinstance(target_cfg, (int, float)):
        target_val = float(target_cfg)
        op = _COMP_NATIVE.get(comparator)
        if op is not None:
            return op(source_arr, target_val)
    elif isinstance(target_cfg, dict):
        target_key = _cfg_key_static(target_cfg, tf)
        target_arr = results.get(target_key) if target_key else None
        if target_arr is not None:
            op = _COMP_NATIVE.get(comparator)
            if op is not None:
                return op(source_arr, target_arr)

    return None


def _eval_distance_native(cond: dict, results: dict) -> np.ndarray | None:
    """Evaluate price_level_distance against precomputed arrays."""
    source_cfg = cond.get("source", {})
    level_cfg = cond.get("level", {})
    comparator = cond.get("comparator", "DISTANCE_LESS_THAN")
    value_pct = float(cond.get("value_pct", 1.0))
    position = cond.get("position") or "any"
    tf = cond.get("timeframe", "1m")

    source_key = _cfg_key_static(source_cfg, tf) if isinstance(source_cfg, dict) else None
    level_key = _cfg_key_static(level_cfg, tf) if isinstance(level_cfg, dict) else None

    source_arr = results.get(source_key) if source_key else None
    level_arr = results.get(level_key) if level_key else None

    if source_arr is None or level_arr is None:
        return None

    with np.errstate(divide="ignore", invalid="ignore"):
        distance_pct = np.abs(source_arr - level_arr) / np.where(level_arr != 0, level_arr, np.nan) * 100

    comp = comparator.upper().replace("DISTANCE_", "")
    if comp in ("LT", "LESS_THAN"):
        dist_mask = distance_pct <= value_pct
    elif comp in ("GT", "GREATER_THAN"):
        dist_mask = distance_pct >= value_pct
    else:
        dist_mask = distance_pct <= value_pct

    dist_mask = np.nan_to_num(dist_mask, nan=False)

    if position == "above":
        pos_mask = source_arr >= level_arr
    elif position == "below":
        pos_mask = source_arr <= level_arr
    else:
        pos_mask = np.ones(len(source_arr), dtype=bool)

    return dist_mask & pos_mask


def _cfg_key_static(cfg: dict, tf: str) -> str | None:
    """Build indicator cache key (same format as _extract_indicator_plan)."""
    if not isinstance(cfg, dict) or "name" not in cfg:
        return None
    name = cfg.get("name", "")
    period = cfg.get("period")
    period2 = cfg.get("period2")
    period3 = cfg.get("period3")
    std_dev = cfg.get("stdDev")
    return f"{name}|{tf}|{period}|{period2}|{period3}|{std_dev}"


# ── Legacy functions (unchanged, kept for backward compatibility) ─────────

def _resample_if_needed(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "1m":
        return df
    tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}
    freq = tf_map.get(timeframe, "1min")
    ts = pd.to_datetime(df["timestamp"])
    agg_dict = {
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "timestamp": "first",
    }
    for col in df.columns:
        if col not in agg_dict:
            agg_dict[col] = "first"
    resampled = df.set_index(ts).resample(freq).agg(agg_dict).dropna(subset=["open"])
    return resampled


def _align_signals_to_1m(
    signals_tf: pd.Series, df_1m: pd.DataFrame, timeframe: str,
) -> pd.Series:
    if timeframe == "1m":
        return signals_tf
    ts_1m = pd.to_datetime(df_1m["timestamp"])
    tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}
    freq = tf_map.get(timeframe, "1min")
    delta = pd.to_timedelta(freq)
    t_shifted = ts_1m + pd.to_timedelta("1min")
    t_floored = t_shifted.dt.floor(freq)
    T_closed = t_floored - delta
    result = T_closed.map(signals_tf).fillna(False).astype(bool)
    result.index = df_1m.index
    return result


def _evaluate_condition_group(
    group: dict, df_1m: pd.DataFrame, parent_tf: str,
    daily_stats: dict | None, cache: dict | None = None,
) -> pd.Series:
    if not group:
        return pd.Series(False, index=df_1m.index)
    operator = group.get("operator", "AND")
    conditions = group.get("conditions", [])
    if not conditions:
        return pd.Series(False, index=df_1m.index)
    results = []
    for cond in conditions:
        cond_type = cond.get("type", "")
        if cond_type == "group" or ("conditions" in cond and "operator" in cond):
            result = _evaluate_condition_group(cond, df_1m, parent_tf, daily_stats, cache)
        else:
            result = _evaluate_single_condition(cond, df_1m, parent_tf, daily_stats, cache)
        results.append(result)
    if not results:
        return pd.Series(False, index=df_1m.index)
    combined = results[0]
    for r in results[1:]:
        if operator == "AND":
            combined = combined & r
        else:
            combined = combined | r
    return combined


def _evaluate_single_condition(
    cond: dict, df_1m: pd.DataFrame, parent_tf: str,
    daily_stats: dict | None, cache: dict | None = None,
) -> pd.Series:
    cond_type = cond.get("type", "")
    tf = cond.get("timeframe") or parent_tf or "1m"
    tf_cache = cache.setdefault(tf, {}) if cache is not None else None

    if tf_cache is not None:
        cond_df = tf_cache.get("__resampled__")
        if cond_df is None:
            cond_df = _resample_if_needed(df_1m, tf)
            tf_cache["__resampled__"] = cond_df
    else:
        cond_df = _resample_if_needed(df_1m, tf)

    if cond_type == "indicator_comparison":
        res_tf = _eval_indicator_comparison(cond, cond_df, daily_stats, tf_cache)
    elif cond_type == "price_level_distance":
        res_tf = _eval_price_level_distance(cond, cond_df, daily_stats, tf_cache)
    elif cond_type == "candle_pattern":
        res_tf = _eval_candle_pattern(cond, cond_df)
    else:
        res_tf = pd.Series(False, index=cond_df.index)

    if tf != "1m":
        res_1m = _align_signals_to_1m(res_tf, df_1m, tf)
    else:
        res_1m = res_tf
    return res_1m


def _eval_indicator_comparison(
    cond: dict, df: pd.DataFrame, daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    source_cfg = cond.get("source", {})
    target_cfg = cond.get("target", {})
    comparator = cond.get("comparator", "GREATER_THAN")
    source_series = _compute_from_config(source_cfg, df, daily_stats, cache)

    if isinstance(target_cfg, (int, float)):
        target_series = pd.Series(float(target_cfg), index=df.index)
    elif isinstance(target_cfg, dict):
        target_series = _compute_from_config(target_cfg, df, daily_stats, cache)
    else:
        target_series = pd.Series(float(target_cfg), index=df.index)

    source_name = source_cfg.get("name", "") if isinstance(source_cfg, dict) else ""
    if "Consecutive" in source_name:
        valid_vals = source_series.dropna()
        if len(valid_vals) > 0:
            logger.info(
                f"[CONSECUTIVE] {source_name}: max={valid_vals.max():.0f}, "
                f"last={valid_vals.iloc[-1]:.0f}, "
                f"compare {comparator} {target_cfg if isinstance(target_cfg, (int, float)) else 'indicator'}"
            )

    return _apply_comparator(source_series, target_series, comparator)


def _eval_price_level_distance(
    cond: dict, df: pd.DataFrame, daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    source_cfg = cond.get("source", {})
    level_cfg = cond.get("level", {})
    comparator = cond.get("comparator", "DISTANCE_LESS_THAN")
    value_pct = cond.get("value_pct", 1.0)
    position = cond.get("position") or "any"

    if isinstance(source_cfg, str):
        source_cfg = {"name": source_cfg}
    if isinstance(level_cfg, str):
        level_cfg = {"name": level_cfg}

    source_series = _compute_from_config(source_cfg, df, daily_stats, cache)
    level_series = _compute_from_config(level_cfg, df, daily_stats, cache)

    distance_pct = abs(source_series - level_series) / level_series.replace(0, np.nan) * 100

    if position == "above":
        position_mask = source_series >= level_series
    elif position == "below":
        position_mask = source_series <= level_series
    else:
        position_mask = pd.Series(True, index=df.index)

    comp = comparator.upper().replace("DISTANCE_", "")
    if comp in ("LT", "LESS_THAN"):
        dist_mask = distance_pct <= value_pct
    elif comp in ("GT", "GREATER_THAN"):
        dist_mask = distance_pct >= value_pct
    else:
        dist_mask = distance_pct <= value_pct

    return dist_mask & position_mask


def _eval_candle_pattern(cond: dict, df: pd.DataFrame) -> pd.Series:
    return detect_candle_pattern(
        df=df, pattern=cond.get("pattern", "GREEN_VOLUME"),
        lookback=cond.get("lookback", 0),
        consecutive_count=cond.get("consecutive_count", 1),
    )


def _compute_from_config(
    cfg: dict, df: pd.DataFrame, daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    if not cfg:
        return df["close"]
    return compute_indicator(
        name=cfg.get("name", "Close"), df=df,
        period=cfg.get("period"), period2=cfg.get("period2"),
        period3=cfg.get("period3"), std_dev=cfg.get("stdDev"),
        multiplier=cfg.get("multiplier"), offset=cfg.get("offset", 0),
        days_lookback=cfg.get("days_lookback"),
        calc_on_heikin=cfg.get("calc_on_heikin", False),
        time_hour=cfg.get("time_hour"), time_minute=cfg.get("time_minute"),
        time_condition=cfg.get("time_condition"),
        band_line=cfg.get("band_line"), orb_minutes=cfg.get("orb_minutes"),
        ap_session=cfg.get("ap_session"), daily_stats=daily_stats,
        cache=cache, range_minutes=cfg.get("range_minutes"),
        pivot_window=cfg.get("pivot_window"),
        tri_lookback=cfg.get("tri_lookback"),
        slope_tolerance=cfg.get("slope_tolerance"),
        min_r_squared=cfg.get("min_r_squared"),
        min_pivots=cfg.get("min_pivots"),
    )


# ── N1c applied: dict dispatch for comparator ────────────────────────────

def _apply_comparator(
    source: pd.Series, target: pd.Series, comparator: str,
) -> pd.Series:
    op = _COMPARATOR_OPS.get(comparator)
    if op is not None:
        return op(source, target)
    if comparator in ("DISTANCE_GREATER_THAN", "DISTANCE_LESS_THAN"):
        logger.warning(
            f"{comparator} used in indicator_comparison — this comparator "
            "requires 'price_level_distance' condition type with value_pct. Returning False."
        )
        return pd.Series(False, index=source.index)
    return source > target


# ── Risk management (unchanged) ──────────────────────────────────────────

def _parse_risk_management(
    risk: dict, df: pd.DataFrame, daily_stats: dict | None,
    cache: dict | None = None,
) -> tuple:
    sl_stop = None
    sl_trail = False
    tp_stop = None
    tp_time_limit = None
    trail_pct = None
    partial_tps = None

    if risk.get("use_hard_stop") and risk.get("hard_stop"):
        hs = risk["hard_stop"]
        hs_type = hs.get("type", "Percentage")
        hs_value = hs.get("value", 0)
        if hs_type == "Percentage":
            sl_stop = hs_value / 100.0
        elif hs_type == "Fixed Amount":
            first_close = df["close"].iloc[0] if not df.empty else 1
            sl_stop = hs_value / first_close if first_close > 0 else None
        elif hs_type == "ATR Multiplier":
            atr = compute_indicator("ATR", df, period=14, daily_stats=daily_stats, cache=cache)
            avg_atr = atr.dropna().mean()
            first_close = df["close"].iloc[0] if not df.empty else 1
            sl_stop = (avg_atr * hs_value) / first_close if first_close > 0 else None
        elif hs_type == "Market Structure (HOD/LOD)":
            sl_stop = None

    trailing = risk.get("trailing_stop", {})
    if trailing.get("active"):
        sl_trail = True
        if trailing.get("type") == "Percentage" and trailing.get("buffer_pct"):
            trail_pct = trailing["buffer_pct"] / 100.0

    if risk.get("use_take_profit") is not False:
        tp_mode = risk.get("take_profit_mode", "Full")
        if tp_mode == "Partial" and risk.get("partial_take_profits"):
            raw_pts = risk["partial_take_profits"]
            partial_tps = []
            for pt in raw_pts:
                dist = pt.get("distance_pct", 0)
                cap = pt.get("capital_pct", 0)
                is_eod_val = isinstance(dist, str) and dist.upper() == "EOD"
                is_time_val = isinstance(dist, str) and dist.startswith("TIME:")
                is_hour_val = isinstance(dist, str) and dist.startswith("HOUR:")
                if (is_eod_val or is_time_val or is_hour_val or (isinstance(dist, (int, float)) and dist > 0)) and cap > 0:
                    partial_tps.append({"distance_pct": dist, "capital_pct": cap / 100.0})

            def _pt_sort_key(x):
                d = x["distance_pct"]
                if isinstance(d, str):
                    if d.upper() == "EOD": return (3, 0.0)
                    if d.startswith("HOUR:"):
                        try:
                            parts = d.split(":")
                            return (2, int(parts[1]) * 60 + int(parts[2]))
                        except: return (2, 0.0)
                    if d.startswith("TIME:"):
                        try: return (1, float(d.split(":")[1]))
                        except: return (1, 0.0)
                return (0, float(d) / 100.0)

            if partial_tps:
                for pt in partial_tps:
                    d = pt["distance_pct"]
                    if not isinstance(d, str):
                        pt["distance_pct"] = float(d) / 100.0
                partial_tps.sort(key=_pt_sort_key)
            else:
                partial_tps = None
        elif risk.get("take_profit"):
            tp = risk["take_profit"]
            tp_type = tp.get("type")
            if tp_type == "Percentage":
                tp_stop = tp.get("value", 0) / 100.0
            elif tp_type == "Time":
                tp_time_limit = float(tp.get("value", 0)) if tp.get("value") else 0.0
            elif tp_type == "Hour":
                tp_time_limit = f"HOUR:{tp.get('value', '15:30')}"

    return sl_stop, sl_trail, tp_stop, tp_time_limit, trail_pct, partial_tps
