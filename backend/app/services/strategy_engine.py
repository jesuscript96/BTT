"""
Translates a strategy JSON definition into boolean signal arrays.
Recursively evaluates ConditionGroups (AND/OR) to produce entry/exit signals.
"""

import logging
import numpy as np
import pandas as pd
from app.services.indicators import compute_indicator, detect_candle_pattern

logger = logging.getLogger("backtester.strategy_engine")


def get_lowest_timeframe_mins(logic_dict: dict | None) -> int:
    if not logic_dict:
        return 1
    
    tf_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
    
    # Base timeframe
    base_tf = logic_dict.get("timeframe", "1m")
    lowest_mins = tf_map.get(base_tf, 1)
    
    # Check conditions recursively
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
    """Pre-extract all per-strategy fields once so the per-day translate_strategy
    call avoids repeating dict.get() lookups inside the day loop."""
    bias = strategy_def.get("bias", "long")
    entry_logic = strategy_def.get("entry_logic", {}) or {}
    exit_logic = strategy_def.get("exit_logic", {}) or {}
    risk = strategy_def.get("risk_management", {}) or {}
    return {
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
        "entry_time_windows": entry_logic.get("entry_time_windows", []),
        "entry_candle_delay": entry_logic.get("candle_delay"),
        "exit_candle_delay": exit_logic.get("candle_delay"),
    }


def translate_strategy(
    df: pd.DataFrame,
    strategy_def: dict,
    daily_stats: dict | None = None,
    compiled: dict | None = None,
) -> dict:
    """
    Translate strategy definition JSON into simulation parameters.

    Returns dict with:
        entries: pd.Series[bool]
        exits: pd.Series[bool]
        direction: str ('longonly' or 'shortonly')
        sl_stop: float | None
        sl_trail: bool
        tp_stop: float | None
        init_cash: passed through

    If `compiled` is provided, dict-lookup overhead from strategy_def is skipped.
    """
    if compiled is None:
        compiled = compile_strategy_def(strategy_def)

    direction = compiled["direction"]
    entry_logic = compiled["entry_logic"]
    exit_logic = compiled["exit_logic"]
    risk = compiled["risk_management"]
    entry_tf = compiled["entry_tf"]
    exit_tf = compiled["exit_tf"]

    entry_cache: dict = {}
    exit_cache: dict = entry_cache if entry_tf == exit_tf else {}

    entries = _evaluate_condition_group(
        compiled["entry_root"], df, entry_tf, daily_stats, entry_cache
    )
    
    # Filter entries strictly to configured time windows
    time_windows = compiled.get("entry_time_windows", [])
    if time_windows:
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
                
                # Check if the time falls in this range
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
    sl_stop, sl_trail, tp_stop, trail_pct, partial_tps = _parse_risk_management(risk, df, daily_stats, risk_cache)

    return {
        "entries": entries.astype(bool),
        "exits": exits.astype(bool),
        "direction": direction,
        "sl_stop": sl_stop,
        "sl_trail": sl_trail,
        "tp_stop": tp_stop,
        "trail_pct": trail_pct,
        "accept_reentries": compiled["accept_reentries"],
        "partial_take_profits": partial_tps,
    }


def _resample_if_needed(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "1m":
        return df

    tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}
    freq = tf_map.get(timeframe, "1min")

    ts = pd.to_datetime(df["timestamp"])
    
    # Define aggregation rules to avoid losing other columns like 'rvol'
    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "timestamp": "first",
    }
    for col in df.columns:
        if col not in agg_dict:
            agg_dict[col] = "first"

    resampled = df.set_index(ts).resample(freq).agg(agg_dict).dropna(subset=["open"])

    return resampled


def _align_signals_to_1m(
    signals_tf: pd.Series,
    df_1m: pd.DataFrame,
    timeframe: str,
) -> pd.Series:
    """
    Alinea señales de un timeframe mayor a barras 1m.
    Usa la señal del bucket ANTERIOR para evitar look-ahead.
    Una señal generada en el bucket [T, T+N) se aplica
    a partir de la primera barra 1m de [T+N, T+2N).
    """
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
    group: dict,
    df_1m: pd.DataFrame,
    parent_tf: str,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    """Recursively evaluate a ConditionGroup with AND/OR logic."""
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
    cond: dict,
    df_1m: pd.DataFrame,
    parent_tf: str,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    cond_type = cond.get("type", "")
    tf = cond.get("timeframe") or parent_tf or "1m"

    # Evaluate the condition on its own resampled dataframe
    cond_df = _resample_if_needed(df_1m, tf)

    # Use a timeframe-specific cache to avoid key collisions of indicators across timeframes
    tf_cache = cache.setdefault(tf, {}) if cache is not None else None

    if cond_type == "indicator_comparison":
        res_tf = _eval_indicator_comparison(cond, cond_df, daily_stats, tf_cache)
    elif cond_type == "price_level_distance":
        res_tf = _eval_price_level_distance(cond, cond_df, daily_stats, tf_cache)
    elif cond_type == "candle_pattern":
        res_tf = _eval_candle_pattern(cond, cond_df)
    else:
        res_tf = pd.Series(False, index=cond_df.index)

    # Align the result series back to 1m
    if tf != "1m":
        res_1m = _align_signals_to_1m(res_tf, df_1m, tf)
    else:
        res_1m = res_tf

    return res_1m


def _eval_indicator_comparison(
    cond: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
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

    # Log consecutive indicator evaluations for debugging
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
    cond: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    source_cfg = cond.get("source", {})
    level_cfg = cond.get("level", {})
    comparator = cond.get("comparator", "DISTANCE_LESS_THAN")
    value_pct = cond.get("value_pct", 1.0)
    position = cond.get("position")
    if position is None or position == "":
        position = "any"

    # Parse source/level as IndicatorConfig objects (or string fallback)
    if isinstance(source_cfg, str):
        source_cfg = {"name": source_cfg}
    if isinstance(level_cfg, str):
        level_cfg = {"name": level_cfg}

    source_series = _compute_from_config(source_cfg, df, daily_stats, cache)
    level_series = _compute_from_config(level_cfg, df, daily_stats, cache)

    distance_pct = abs(source_series - level_series) / level_series.replace(0, np.nan) * 100

    # Apply position filter
    if position == "above":
        position_mask = source_series >= level_series
    elif position == "below":
        position_mask = source_series <= level_series
    else:  # "any"
        position_mask = pd.Series(True, index=df.index)

    # Normalize comparator aliases
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
        df=df,
        pattern=cond.get("pattern", "GREEN_VOLUME"),
        lookback=cond.get("lookback", 0),
        consecutive_count=cond.get("consecutive_count", 1),
    )


def _compute_from_config(
    cfg: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    """Compute an indicator from a full IndicatorConfig dict."""
    if not cfg:
        return df["close"]
    return compute_indicator(
        name=cfg.get("name", "Close"),
        df=df,
        period=cfg.get("period"),
        period2=cfg.get("period2"),
        period3=cfg.get("period3"),
        std_dev=cfg.get("stdDev"),
        multiplier=cfg.get("multiplier"),
        offset=cfg.get("offset", 0),
        days_lookback=cfg.get("days_lookback"),
        calc_on_heikin=cfg.get("calc_on_heikin", False),
        time_hour=cfg.get("time_hour"),
        time_minute=cfg.get("time_minute"),
        time_condition=cfg.get("time_condition"),
        band_line=cfg.get("band_line"),
        orb_minutes=cfg.get("orb_minutes"),
        ap_session=cfg.get("ap_session"),
        daily_stats=daily_stats,
        cache=cache,
        range_minutes=cfg.get("range_minutes"),
        pivot_window=cfg.get("pivot_window"),
        tri_lookback=cfg.get("tri_lookback"),
        slope_tolerance=cfg.get("slope_tolerance"),
        min_r_squared=cfg.get("min_r_squared"),
        min_pivots=cfg.get("min_pivots"),
    )


def _apply_comparator(
    source: pd.Series,
    target: pd.Series,
    comparator: str,
) -> pd.Series:
    if comparator == "GREATER_THAN":
        return source > target
    elif comparator == "LESS_THAN":
        return source < target
    elif comparator == "GREATER_THAN_OR_EQUAL":
        return source >= target
    elif comparator == "LESS_THAN_OR_EQUAL":
        return source <= target
    elif comparator == "EQUAL":
        return source == target
    elif comparator == "CROSSES_ABOVE":
        return (source.shift(1) <= target.shift(1)) & (source > target)
    elif comparator == "CROSSES_BELOW":
        return (source.shift(1) >= target.shift(1)) & (source < target)
    elif comparator == "DISTANCE_GREATER_THAN":
        # BUG FIX: This comparator requires a value_pct threshold.
        # When used in indicator_comparison mode, there is no value_pct available.
        # These conditions should use price_level_distance type instead.
        logger.warning(
            "DISTANCE_GREATER_THAN used in indicator_comparison — this comparator "
            "requires 'price_level_distance' condition type with value_pct. Returning False."
        )
        return pd.Series(False, index=source.index)
    elif comparator == "DISTANCE_LESS_THAN":
        logger.warning(
            "DISTANCE_LESS_THAN used in indicator_comparison — this comparator "
            "requires 'price_level_distance' condition type with value_pct. Returning False."
        )
        return pd.Series(False, index=source.index)
    else:
        return source > target


def _parse_risk_management(
    risk: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> tuple[float | None, bool, float | None, float | None, list | None]:
    sl_stop = None
    sl_trail = False
    tp_stop = None
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

    # --- Take Profit ---
    if risk.get("use_take_profit") is not False:
        tp_mode = risk.get("take_profit_mode", "Full")

        if tp_mode == "Partial" and risk.get("partial_take_profits"):
            # Partial Take-Profits: array of {distance_pct, capital_pct}
            raw_pts = risk["partial_take_profits"]
            partial_tps = []
            for pt in raw_pts:
                dist = pt.get("distance_pct", 0)
                cap = pt.get("capital_pct", 0)
                is_eod_val = isinstance(dist, str) and dist.upper() == "EOD"
                if (is_eod_val or (isinstance(dist, (int, float)) and dist > 0)) and cap > 0:
                    partial_tps.append({
                        "distance_pct": "EOD" if is_eod_val else (dist / 100.0),
                        "capital_pct": cap / 100.0,
                    })
            # Sort by distance ascending so nearest TP triggers first, and EOD goes last
            if partial_tps:
                partial_tps.sort(key=lambda x: float('inf') if isinstance(x["distance_pct"], str) and x["distance_pct"].upper() == "EOD" else x["distance_pct"])
            else:
                partial_tps = None
            # tp_stop stays None — partial mode doesn't use a single TP
        elif risk.get("take_profit"):
            tp = risk["take_profit"]
            if tp.get("type") == "Percentage":
                tp_stop = tp.get("value", 0) / 100.0

    return sl_stop, sl_trail, tp_stop, trail_pct, partial_tps
