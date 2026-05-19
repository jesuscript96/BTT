"""
Translates a strategy JSON definition into boolean signal arrays.
Recursively evaluates ConditionGroups (AND/OR) to produce entry/exit signals.
"""

import logging
import numpy as np
import pandas as pd
from app.services.indicators import compute_indicator, detect_candle_pattern

logger = logging.getLogger("backtester.strategy_engine")


def translate_strategy(
    df: pd.DataFrame,
    strategy_def: dict,
    daily_stats: dict | None = None,
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
    """
    bias = strategy_def.get("bias", "long")
    direction = "longonly" if bias == "long" else "shortonly"

    entry_logic = strategy_def.get("entry_logic", {})
    exit_logic = strategy_def.get("exit_logic", {})
    risk = strategy_def.get("risk_management", {})

    entry_tf = entry_logic.get("timeframe", "1m")
    exit_tf = exit_logic.get("timeframe", "1m")

    entry_df = _resample_if_needed(df, entry_tf)
    exit_df = _resample_if_needed(df, exit_tf)

    entry_cache: dict = {}
    exit_cache: dict = entry_cache if entry_tf == exit_tf else {}

    entries = _evaluate_condition_group(
        entry_logic.get("root_condition", {}), entry_df, daily_stats, entry_cache
    )
    exits = _evaluate_condition_group(
        exit_logic.get("root_condition", {}), exit_df, daily_stats, exit_cache
    )

    if entry_tf != "1m":
        entries = entries.reindex(df.index, method="ffill").fillna(False)
    if exit_tf != "1m":
        exits = exits.reindex(df.index, method="ffill").fillna(False)

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
        "accept_reentries": risk.get("accept_reentries", False),
        "partial_take_profits": partial_tps,
    }


def _resample_if_needed(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "1m":
        return df

    tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}
    freq = tf_map.get(timeframe, "1min")

    ts = pd.to_datetime(df["timestamp"])
    resampled = df.set_index(ts).resample(freq).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "timestamp": "first",
    }).dropna(subset=["open"])

    return resampled.reset_index(drop=True)


def _evaluate_condition_group(
    group: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    """Recursively evaluate a ConditionGroup with AND/OR logic."""
    if not group:
        return pd.Series(False, index=df.index)

    operator = group.get("operator", "AND")
    conditions = group.get("conditions", [])

    if not conditions:
        return pd.Series(False, index=df.index)

    results = []
    for cond in conditions:
        cond_type = cond.get("type", "")
        if cond_type == "group" or ("conditions" in cond and "operator" in cond):
            result = _evaluate_condition_group(cond, df, daily_stats, cache)
        else:
            result = _evaluate_single_condition(cond, df, daily_stats, cache)
        results.append(result)

    if not results:
        return pd.Series(False, index=df.index)

    combined = results[0]
    for r in results[1:]:
        if operator == "AND":
            combined = combined & r
        else:
            combined = combined | r

    return combined


def _evaluate_single_condition(
    cond: dict,
    df: pd.DataFrame,
    daily_stats: dict | None,
    cache: dict | None = None,
) -> pd.Series:
    cond_type = cond.get("type", "")

    if cond_type == "indicator_comparison":
        return _eval_indicator_comparison(cond, df, daily_stats, cache)
    elif cond_type == "price_level_distance":
        return _eval_price_level_distance(cond, df, daily_stats, cache)
    elif cond_type == "candle_pattern":
        return _eval_candle_pattern(cond, df)
    else:
        return pd.Series(False, index=df.index)


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
    position = cond.get("position", "any")

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
        position_mask = source_series > level_series
    elif position == "below":
        position_mask = source_series < level_series
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
        daily_stats=daily_stats,
        cache=cache,
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
    tp_mode = risk.get("take_profit_mode", "Full")

    if tp_mode == "Partial" and risk.get("partial_take_profits"):
        # Partial Take-Profits: array of {distance_pct, capital_pct}
        raw_pts = risk["partial_take_profits"]
        partial_tps = []
        for pt in raw_pts:
            dist = pt.get("distance_pct", 0)
            cap = pt.get("capital_pct", 0)
            if dist > 0 and cap > 0:
                partial_tps.append({
                    "distance_pct": dist / 100.0,  # Convert to fraction
                    "capital_pct": cap / 100.0,
                })
        # Sort by distance ascending so nearest TP triggers first
        partial_tps.sort(key=lambda x: x["distance_pct"])
        if not partial_tps:
            partial_tps = None
        # tp_stop stays None — partial mode doesn't use a single TP
    elif risk.get("use_take_profit") and risk.get("take_profit"):
        tp = risk["take_profit"]
        if tp.get("type") == "Percentage":
            tp_stop = tp.get("value", 0) / 100.0

    return sl_stop, sl_trail, tp_stop, trail_pct, partial_tps
