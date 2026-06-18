"""
Optimization service for parameter grid sweep and robust plateau analysis.
Extracts tunable parameters from strategy JSON, runs grid of backtests,
computes surface data and identifies robust parameter regions.
"""

import copy
import json
import logging
import math
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

import numpy as np
import pandas as pd

from app.services.data_service import (
    get_strategy,
    fetch_dataset_data,
    fetch_qualifying_data,
    _evaluate_postgap_preconditions,
)
from app.db.gcs_cache import (
    _fetch_and_cache_month,
    _select_intraday_glob_for_month,
    get_connection,
    INTRADAY_BATCH_SIZE,
)
from app.services.backtest_service import run_backtest
from app.redis_client import get_redis

logger = logging.getLogger("backtester.optimization")

# Global dict to track progress of long-running optimizations (in-memory for local use)
OPTIMIZATION_PROGRESS = {}

# Global dict to store completed optimization results (in-memory for local use)
OPTIMIZATION_RESULTS = {}


# ─── Redis-backed accessors for progress / results ──────────────────────────
# Redis lets progress and results survive restarts/redeploys and be shared
# across API workers. When get_redis() returns None (Redis unavailable) every
# accessor falls back to the in-memory dicts above, so behavior is identical to
# the original single-process implementation.
_OPT_REDIS_TTL = 3600  # 1h — longer than any realistic sweep


def _json_default(o):
    """Encoder fallback so optimization results (which may carry numpy scalars
    or arrays inside `details`) serialize cleanly to JSON for Redis."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def set_progress(task_id: str, value: float) -> None:
    """Store optimization progress (float 0.0-100.0). Redis when available,
    in-memory dict as fallback."""
    r = get_redis()
    if r:
        try:
            r.setex(f"opt:progress:{task_id}", _OPT_REDIS_TTL, json.dumps(value))
            return
        except Exception as e:
            logger.warning(f"[REDIS] set progress failed for {task_id}: {e}")
    OPTIMIZATION_PROGRESS[task_id] = value


def get_progress(task_id: str, default: float = 0.0):
    """Read optimization progress. Checks Redis first, then the in-memory dict
    (which also catches a value that fell back on a Redis write error)."""
    r = get_redis()
    if r:
        try:
            raw = r.get(f"opt:progress:{task_id}")
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"[REDIS] get progress failed for {task_id}: {e}")
    return OPTIMIZATION_PROGRESS.get(task_id, default)


def store_result(task_id: str, result) -> None:
    """Store a completed optimization result. An Exception is serialized to
    {"error": str(e)} — NEVER pickled. Successful results (dicts) are
    JSON-serialized. Redis when available, in-memory dict as fallback."""
    r = get_redis()
    if r:
        if isinstance(result, Exception):
            payload = {"__opt_error__": True, "error": str(result)}
        else:
            payload = {"__opt_error__": False, "result": result}
        try:
            r.setex(
                f"opt:result:{task_id}",
                _OPT_REDIS_TTL,
                json.dumps(payload, default=_json_default),
            )
            return
        except Exception as e:
            logger.warning(f"[REDIS] set result failed for {task_id}: {e}")
    # In-memory fallback keeps the original semantics (stores dict or Exception)
    OPTIMIZATION_RESULTS[task_id] = result


def pop_result(task_id: str):
    """Pop a completed result and clear its progress entry.

    Returns a 3-tuple (found: bool, is_error: bool, payload). payload is the
    result dict on success or the error message string on failure.
    """
    r = get_redis()
    if r:
        try:
            raw = r.get(f"opt:result:{task_id}")
            if raw is not None:
                r.delete(f"opt:result:{task_id}")
                r.delete(f"opt:progress:{task_id}")
                env = json.loads(raw)
                if env.get("__opt_error__"):
                    return True, True, env.get("error", "Unknown error")
                return True, False, env.get("result")
        except Exception as e:
            logger.warning(f"[REDIS] pop result failed for {task_id}: {e}")
    # In-memory fallback (also catches a result that fell back on a Redis error)
    if task_id in OPTIMIZATION_RESULTS:
        result = OPTIMIZATION_RESULTS.pop(task_id)
        OPTIMIZATION_PROGRESS.pop(task_id, None)
        if isinstance(result, Exception):
            return True, True, str(result)
        return True, False, result
    return False, False, None

# Dataset context for forked grid workers. Populated by run_optimization_grid
# right before the pool forks so children inherit it via copy-on-write instead
# of pickling the dataset per task; cleared after the sweep. Only valid while
# a sweep is running (one optimization at a time per process).
_GRID_CTX = {}

# Per-process signal cache for risk-only sweeps. Each forked worker fills its
# own copy across the chunks it processes; stays empty in the parent.
_WORKER_SIGNAL_CACHE = {}

# Performance metrics we can optimise for
METRICS = {
    "sharpe": "avg_sharpe",
    "total_return": "total_return_pct",
    "max_drawdown": "max_drawdown_pct",
    "profit_factor": "avg_profit_factor",
    "win_rate": "win_rate_pct",
    "expectancy": "expectancy",
    "calmar": "calmar_ratio",
    "sortino": "sortino_ratio",
    "dd_return": "dd_return_ratio",
    "avg_r_ui": "avg_r_ui",
}


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------

def extract_parameters(strategy_def: dict) -> list[dict]:
    """Walk the strategy JSON and extract all tunable numerical parameters."""
    params = []
    _seen = set()

    def _add(param_id: str, label: str, value, category: str, path: str,
             min_val=None, max_val=None, step=None, is_int_param=False):
        if param_id in _seen or value is None:
            return
        _seen.add(param_id)
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        # Skip parameters with value 0 — they represent disabled features
        # (e.g., SL=0 means no stop loss, TP=0 means no take profit)
        if v == 0:
            return
        
        if is_int_param:
            v_step = 1.0
            v_min = float(max(0, int(v - 5))) if min_val is None else float(min_val)
            v_max = float(int(v + 10)) if max_val is None else float(max_val)
        else:
            v_step = float(step or _auto_step(v))
            v_min = float(min_val or max(0, v * 0.25))
            v_max = float(max_val or max(v * 3, v + 10))

        params.append({
            "id": param_id,
            "label": label,
            "current_value": v,
            "category": category,
            "path": path,
            "min": v_min,
            "max": v_max,
            "step": v_step,
        })

    def _auto_step(v):
        if v == 0:
            return 1
        if v >= 100:
            return 10
        if v >= 10:
            return 1
        if v >= 1:
            return 0.5
        return 0.1

    # --- Entry/Exit logic conditions ---
    for logic_key, logic_label in [("entry_logic", "Entry"), ("exit_logic", "Exit")]:
        logic = strategy_def.get(logic_key) or {}
        root = logic.get("root_condition") or {}
        _extract_from_condition_group(root, logic_label, f"{logic_key}.root_condition",
                                      params, _seen, _add)

    # --- Risk management ---
    rm = strategy_def.get("risk_management") or {}
    
    # Hard Stop
    if rm.get("use_hard_stop") is not False:
        hs = rm.get("hard_stop")
        if hs:
            val = hs.get("value")
            if val is not None:
                is_numeric = False
                try:
                    float_val = float(val)
                    is_numeric = True
                except (ValueError, TypeError):
                    pass
                if is_numeric:
                    _add("risk.hard_stop.value",
                         f"Stop Loss ({hs.get('type', 'Pct')})",
                         val, "Risk", "risk_management.hard_stop.value",
                         min_val=0.1, max_val=max(float_val * 4, 20) if val else 20, step=0.5)

    # Take Profit & Partials
    if rm.get("use_take_profit") is not False:
        tp_mode = rm.get("take_profit_mode", "Full")
        
        if tp_mode == "Full":
            tp = rm.get("take_profit")
            if tp:
                val = tp.get("value")
                if val is not None:
                    _add("risk.take_profit.value",
                         f"Take Profit ({tp.get('type', 'Pct')})",
                         val, "Risk", "risk_management.take_profit.value",
                         min_val=0.5, max_val=max(float(val) * 4, 30) if val else 30, step=0.5)
        elif tp_mode == "Partial":
            for i, ptp in enumerate(rm.get("partial_take_profits") or []):
                _add(f"risk.partial_tp.{i}.distance_pct",
                     f"Parcial {i+1} Distancia %",
                     ptp.get("distance_pct") if ptp else None, "Risk",
                     f"risk_management.partial_take_profits.{i}.distance_pct",
                     min_val=0.5, step=0.5)
                _add(f"risk.partial_tp.{i}.capital_pct",
                     f"Parcial {i+1} Capital %",
                     ptp.get("capital_pct") if ptp else None, "Risk",
                     f"risk_management.partial_take_profits.{i}.capital_pct",
                     min_val=5, max_val=100, step=5)

    # Trailing Stop
    trailing = rm.get("trailing_stop") or {}
    if trailing.get("active") is True:
        val = trailing.get("buffer_pct")
        if val is not None:
            _add("risk.trailing.buffer_pct",
                 "Trailing Buffer %",
                 val, "Risk", "risk_management.trailing_stop.buffer_pct",
                 min_val=0.1, max_val=5.0, step=0.1)

    # --- Preconditions ---
    for i, precond in enumerate(strategy_def.get("postgap_preconditions") or []):
        if not precond or not isinstance(precond, dict):
            continue
        metric = precond.get("metric")
        day_label = "T" if precond.get("day") == "gap_day" else "T+1"
        
        # If it has a value (e.g. volume, candle_range_pct)
        val = precond.get("value")
        if val is not None:
            if metric == "volume":
                _add(f"precond.{i}.value",
                     f"Precond {day_label} Volume",
                     val, "Precondition", f"postgap_preconditions.{i}.value",
                     min_val=max(10000.0, float(val) * 0.25), max_val=float(val) * 4.0, step=50000.0)
            elif metric == "candle_range_pct":
                _add(f"precond.{i}.value",
                     f"Precond {day_label} Rango Vela %",
                     val, "Precondition", f"postgap_preconditions.{i}.value",
                     min_val=0.1, max_val=max(float(val) * 3.0, 10.0), step=0.25)
            else:
                _add(f"precond.{i}.value",
                     f"Precond {day_label} {metric} Valor",
                     val, "Precondition", f"postgap_preconditions.{i}.value")

        # If it has a sma_period
        sma_p = precond.get("sma_period")
        if sma_p is not None:
            _add(f"precond.{i}.sma_period",
                 f"Precond {day_label} SMA Periodo",
                 sma_p, "Precondition", f"postgap_preconditions.{i}.sma_period",
                 min_val=5.0, max_val=200.0, step=5.0, is_int_param=True)

    return params


def _extract_from_condition_group(group, logic_label, path, params, seen, add_fn):
    """Recursively extract parameters from condition groups."""
    if not group or not isinstance(group, dict):
        return

    conditions = group.get("conditions") or []
    for i, cond in enumerate(conditions):
        if not cond or not isinstance(cond, dict):
            continue
        cond_type = cond.get("type", "")
        cond_path = f"{path}.conditions.{i}"

        if cond_type == "group":
            _extract_from_condition_group(cond, logic_label, cond_path, params, seen, add_fn)
        elif cond_type == "indicator_comparison":
            _extract_indicator_params(cond.get("source") or {}, logic_label,
                                       f"{cond_path}.source", add_fn)
            target = cond.get("target")
            if isinstance(target, dict):
                _extract_indicator_params(target, logic_label,
                                           f"{cond_path}.target", add_fn)
            elif isinstance(target, (int, float)):
                src_name = (cond.get("source") or {}).get("name", "Indicator")
                add_fn(f"{cond_path}.target",
                       f"{logic_label} {src_name} Target Value",
                       target, "Condition", f"{cond_path}.target")
        elif cond_type == "price_level_distance":
            _extract_indicator_params(cond.get("source") or {}, logic_label,
                                       f"{cond_path}.source", add_fn)
            _extract_indicator_params(cond.get("level") or {}, logic_label,
                                       f"{cond_path}.level", add_fn)
            val_pct = cond.get("value_pct")
            if val_pct is not None:
                src_name = (cond.get("source") or {}).get("name", "Price")
                lvl_name = (cond.get("level") or {}).get("name", "Level")
                add_fn(f"{cond_path}.value_pct",
                       f"{logic_label} Dist ({src_name}-{lvl_name}) %",
                       val_pct, "Condition", f"{cond_path}.value_pct",
                       min_val=0.1, max_val=max(val_pct * 5, 10), step=0.25)
        elif cond_type == "candle_pattern":
            lookback = cond.get("lookback")
            if lookback is not None:
                add_fn(f"{cond_path}.lookback",
                       f"{logic_label} Candle Lookback",
                       lookback, "Condition", f"{cond_path}.lookback",
                       min_val=1, max_val=10, step=1, is_int_param=True)
            consecutive_count = cond.get("consecutive_count")
            if consecutive_count is not None:
                add_fn(f"{cond_path}.consecutive_count",
                       f"{logic_label} Candle Consecutive Count",
                       consecutive_count, "Condition", f"{cond_path}.consecutive_count",
                       min_val=1, max_val=10, step=1, is_int_param=True)


def _extract_indicator_params(cfg, logic_label, path, add_fn):
    """Extract indicator config parameters."""
    if not cfg or not isinstance(cfg, dict):
        return
    name = cfg.get("name", "")
    
    int_keys = [
        "period", "period2", "period3", "offset", "consecutive_count",
        "time_hour", "time_minute", "days_lookback", "orb_minutes",
        "time_from_hour", "time_from_minute", "range_minutes", "deviationLevel"
    ]
    float_keys = [
        "stdDev", "multiplier", "overbought", "oversold", "return_pct",
        "reversionPercentage", "min_af", "max_af"
    ]

    for param_key in int_keys:
        val = cfg.get(param_key)
        if val is not None:
            label = f"{logic_label} {name} {param_key}"
            param_id = f"{path}.{param_key}"
            add_fn(param_id, label, val, "Indicator", f"{path}.{param_key}", is_int_param=True)

    for param_key in float_keys:
        val = cfg.get(param_key)
        if val is not None:
            label = f"{logic_label} {name} {param_key}"
            param_id = f"{path}.{param_key}"
            add_fn(param_id, label, val, "Indicator", f"{path}.{param_key}", is_int_param=False)


# ---------------------------------------------------------------------------
# Grid sweep
# ---------------------------------------------------------------------------

def _set_nested_value(obj, path: str, value):
    """Set a value in a nested dict/list given a dot-separated path."""
    keys = path.split(".")
    
    # Cast value to int if it's an integer parameter
    last_key = keys[-1]
    if last_key in {"period", "period2", "period3", "offset", "consecutive_count", 
                    "time_hour", "time_minute", "days_lookback", "orb_minutes", 
                    "time_from_hour", "time_from_minute", "range_minutes", 
                    "deviationLevel", "sma_period", "lookback"}:
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            pass

    current = obj
    for k in keys[:-1]:
        if isinstance(current, list):
            k = int(k)
        current = current[k] if isinstance(current, list) else current.get(k, {})
    last_key = keys[-1]
    if isinstance(current, list):
        current[int(last_key)] = value
    else:
        current[last_key] = value


def _run_grid_point(idx: int, ctx: dict, signal_cache: dict | None):
    """Run one grid point. Returns (idx, metric_val_or_nan, detail_dict)."""
    point = ctx["grid_points"][idx]
    param_configs = ctx["param_configs"]
    qualifying_df = ctx["qualifying_df"]
    precomputed_groups = ctx["precomputed_groups"]
    backtest_params = ctx["backtest_params"]

    modified_def = copy.deepcopy(ctx["base_def"])
    for dim, val in enumerate(point):
        _set_nested_value(modified_def, param_configs[dim]["path"], val)

    # If optimizing preconditions, we must re-evaluate them for this point
    if ctx["opt_preconds"]:
        point_preconditions = modified_def.get("postgap_preconditions", [])
        point_qualifying_df = _evaluate_postgap_preconditions(qualifying_df, point_preconditions)
        valid_keys = set(zip(point_qualifying_df["date"].astype(str), point_qualifying_df["ticker"]))
        point_groups = [g for g in precomputed_groups if (str(g[0][0])[:10], g[0][1]) in valid_keys]
    else:
        point_qualifying_df = qualifying_df
        point_groups = precomputed_groups

    try:
        bt_result = run_backtest(
            qualifying_df=point_qualifying_df,
            strategy_def=modified_def,
            init_cash=backtest_params.get("init_cash", 10000),
            risk_r=backtest_params.get("risk_r", 100),
            risk_type=backtest_params.get("risk_type", "FIXED"),
            size_by_sl=backtest_params.get("size_by_sl", False),
            fees=backtest_params.get("fees", 0),
            fee_type=backtest_params.get("fee_type", "PERCENT"),
            slippage=backtest_params.get("slippage", 0),
            market_sessions=backtest_params.get("market_sessions"),
            custom_start_time=backtest_params.get("custom_start_time"),
            custom_end_time=backtest_params.get("custom_end_time"),
            locates_cost=backtest_params.get("locates_cost", 0),
            look_ahead_prevention=backtest_params.get("look_ahead_prevention", False),
            day_group_iter=iter(point_groups),
            n_groups_hint=len(point_groups),
            _signal_cache=signal_cache,
        )
        agg = bt_result.get("aggregate_metrics", {})
        metric_val = agg.get(ctx["metric_key"], 0)
        detail = {
            "sharpe": agg.get("avg_sharpe", 0),
            "total_return": agg.get("total_return_pct", 0),
            "max_drawdown": agg.get("max_drawdown_pct", 0),
            "profit_factor": agg.get("avg_profit_factor", 0),
            "win_rate": agg.get("win_rate_pct", 0),
            "expectancy": agg.get("expectancy", 0),
            "total_trades": agg.get("total_trades", 0),
            "dd_return": agg.get("dd_return_ratio", 0),
            "avg_r_ui": agg.get("avg_r_ui", 0),
        }
        return idx, (float(metric_val) if metric_val is not None else np.nan), detail
    except Exception as e:
        logger.warning(f"[OPT] Point {idx} failed: {e}")
        return idx, np.nan, {}


def _run_grid_chunk(idx_list: list[int]):
    """Worker for a contiguous chunk of grid points — runs in a forked child.

    Reads the dataset from _GRID_CTX inherited at fork time; only the index
    list and the per-point results cross the process boundary. The signal
    cache persists in the child across chunks, so each worker translates the
    strategy signals at most once per (ticker, date) on risk-only sweeps.
    """
    ctx = _GRID_CTX
    signal_cache = _WORKER_SIGNAL_CACHE if ctx.get("is_risk_only") else None
    return [_run_grid_point(idx, ctx, signal_cache) for idx in idx_list]


def run_optimization_grid(
    strategy_id: str,
    dataset_id: str,
    param_configs: list[dict],
    metric: str,
    backtest_params: dict,
    task_id: str | None = None,
    strategy_definition: dict | None = None,
) -> dict:
    """
    Run a grid of backtests varying selected parameters.

    param_configs: [{"id": "...", "path": "...", "values": [v1, v2, ...]}]
    metric: key from METRICS dict
    backtest_params: base backtest parameters (init_cash, risk_r, etc.)

    Returns: {
        "params": [...],
        "grid": [[...]], or [[[...]]] for 3D,
        "grid_details": {metric_key: value for each cell},
        "plateau_analysis": {...}
    }
    """
    t0 = time.time()

    if strategy_id == "draft" and strategy_definition:
        base_def = strategy_definition
    else:
        strategy = get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        base_def = strategy["definition"]

    metric_key = METRICS.get(metric, metric)

    # Build value arrays
    axes = []
    for pc in param_configs:
        values = pc.get("values", [])
        if not values:
            v_min = pc.get("min", 1)
            v_max = pc.get("max", 20)
            steps = pc.get("steps", 10)
            
            # Check if this is an integer parameter
            is_int = False
            last_key = pc.get("path", "").split(".")[-1]
            if last_key in {"period", "period2", "period3", "offset", "consecutive_count", 
                            "time_hour", "time_minute", "days_lookback", "orb_minutes", 
                            "time_from_hour", "time_from_minute", "range_minutes", 
                            "deviationLevel", "sma_period", "lookback"}:
                is_int = True

            if is_int:
                v_min_int = int(round(v_min))
                v_max_int = int(round(v_max))
                # Generate clean integer steps based on matrix dimension (steps) without overshooting
                if v_min_int == v_max_int:
                    values = [v_min_int]
                elif steps > 0:
                    raw_vals = np.linspace(v_min_int, v_max_int, steps)
                    values = sorted(list(set(int(round(x)) for x in raw_vals)))
                else:
                    values = [v_min_int]
            else:
                values = np.linspace(v_min, v_max, steps).tolist()
        axes.append(values)

    base_preconditions = base_def.get("postgap_preconditions") or []
    apply_day = base_def.get("apply_day", "gap_day")

    opt_preconds = any(pc.get("path", "").startswith("postgap_preconditions") for pc in param_configs)
    fetch_preconditions = [] if opt_preconds else base_preconditions

    start_date = backtest_params.get("start_date")
    end_date = backtest_params.get("end_date")
    is_percent = backtest_params.get("is_percent", 100.0)

    if task_id:
        set_progress(task_id, 1.0)

    # 1. Fetch daily qualifying data first to find unique dates and apply IS split
    qualifying_df = fetch_qualifying_data(
        dataset_id,
        req_start_date=start_date,
        req_end_date=end_date,
        preconditions=fetch_preconditions,
        apply_day=apply_day,
    )
    if qualifying_df.empty:
        raise ValueError("No data for selected period/preconditions")

    # Determine In-Sample cutoff date using qualifying_df dates
    opt_end_date = end_date
    if is_percent < 100.0:
        unique_dates = sorted(qualifying_df["date"].unique())
        n_dates = len(unique_dates)
        if n_dates > 0:
            cutoff_idx = max(1, int(n_dates * is_percent / 100.0))
            cutoff_date = unique_dates[cutoff_idx - 1]
            qualifying_df = qualifying_df[qualifying_df["date"] <= cutoff_date]
            opt_end_date = cutoff_date
            logger.info(f"[OPT] In-Sample split filter applied on qualifying dates: kept {len(qualifying_df)} rows up to {cutoff_date} using is_percent={is_percent}%")

    # Convert dates to strings to prevent comparison errors between datetime.date and string
    if start_date:
        start_date = str(start_date)
    if opt_end_date:
        opt_end_date = str(opt_end_date)

    # Apply fallbacks for start_date / end_date
    if start_date:
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) >= start_date]
    if opt_end_date:
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) <= opt_end_date]

    if task_id:
        set_progress(task_id, 2.0)

    # 2. Fetch intraday data only for the resolved In-Sample dates.
    # Uses the SAME per-month disk cache layer as the streaming backtest path
    # (_fetch_and_cache_month): identical cache keys mean the months the
    # dataset precache already wrote to disk are CACHE HITs here, instead of
    # re-downloading everything from GCS on every optimization run.
    dates = pd.to_datetime(qualifying_df["date"])
    ym_pairs = sorted(set(zip(dates.dt.year, dates.dt.month)))

    chunks = []
    n_chunks = len(ym_pairs)
    conn = get_connection()
    for i, (year, month) in enumerate(ym_pairs):
        month_mask = (dates.dt.year == year) & (dates.dt.month == month)
        valid_pairs_month = qualifying_df.loc[month_mask, ["ticker", "date"]].drop_duplicates().copy()
        if valid_pairs_month.empty:
            continue
        # String dates: required by the cache-key json and matches the
        # streaming caller so precache-written months hash identically
        valid_pairs_month["date"] = pd.to_datetime(valid_pairs_month["date"]).dt.strftime("%Y-%m-%d")

        path = _select_intraday_glob_for_month(conn, year, month)
        if path is None:
            logger.warning(f"[OPT] {year}-{month:02d}: no intraday parquet found (skipped)")
            continue

        chunk = _fetch_and_cache_month(
            year, month, path, valid_pairs_month,
            batch_size=max(1, int(INTRADAY_BATCH_SIZE)),
            mi=i + 1,
            n_months=n_chunks,
        )
        if chunk is not None and not chunk.empty:
            chunks.append(chunk)
        if task_id:
            # Load progress goes smoothly from 2.0% to 5.0%
            prog_val = round(2.0 + ((i + 1) / n_chunks) * 3.0, 2)
            set_progress(task_id, prog_val)

    if not chunks:
        intraday_df = pd.DataFrame()
    else:
        intraday_df = pd.concat(chunks, ignore_index=True)
        # Filter to exact (ticker, date) pairs
        valid_pairs = qualifying_df[["ticker", "date"]].drop_duplicates().copy()
        valid_pairs["date"] = valid_pairs["date"].astype(str)
        intraday_df["date"] = intraday_df["date"].astype(str)
        intraday_df = intraday_df.merge(valid_pairs, on=["ticker", "date"], how="inner")

    # Apply date filters to intraday as fallback
    if start_date:
        intraday_df = intraday_df[intraday_df["date"].astype(str) >= start_date]
    if opt_end_date:
        intraday_df = intraday_df[intraday_df["date"].astype(str) <= opt_end_date]

    if task_id:
        set_progress(task_id, 5.0)

    if qualifying_df.empty or intraday_df.empty:
        raise ValueError("No data for selected period/preconditions")

    # --- OPTIMIZATION: Pre-group data once ---
    precomputed_groups = list(intraday_df.groupby(["date", "ticker"]))
    n_groups = len(precomputed_groups)
    logger.info(f"[OPT] Pre-grouped {n_groups} day/ticker groups")

    # --- OPTIMIZATION: Detect risk-only parameters ---
    is_risk_only = all(
        pc["path"].startswith("risk_management.")
        for pc in param_configs
    )
    if is_risk_only:
        logger.info("[OPT] Risk-only parameters detected — signal caching ENABLED")
    else:
        logger.info("[OPT] Indicator parameters detected — signal caching disabled")

    # Create grid points
    grid_points = list(product(*axes))
    n_dims = len(param_configs)
    shape = tuple(len(a) for a in axes)

    n_points = len(grid_points)
    results_flat = np.full(n_points, np.nan)
    details_flat = [None] * n_points

    # Parallel sweep requires fork (COW data sharing); on spawn platforms
    # (Windows) the dataset would be pickled per worker, so fall back.
    n_workers = max(1, min((os.cpu_count() or 1) - 1, n_points, 8))
    use_parallel = n_workers > 1 and "fork" in multiprocessing.get_all_start_methods()

    ctx = {
        "grid_points": grid_points,
        "base_def": base_def,
        "param_configs": param_configs,
        "opt_preconds": opt_preconds,
        "qualifying_df": qualifying_df,
        "precomputed_groups": precomputed_groups,
        "backtest_params": backtest_params,
        "metric_key": metric_key,
        "is_risk_only": is_risk_only,
    }

    logger.info(
        f"[OPT] Starting grid sweep: {n_points} points, shape={shape}, "
        f"mode={f'parallel x{n_workers}' if use_parallel else 'sequential'}"
    )

    if use_parallel:
        # Pre-warm the daily OHLC cache in the parent so forked children
        # inherit it and never open DuckDB (connections don't survive fork).
        try:
            from app.services.indicators import prefetch_daily_ohlc
            prefetch_daily_ohlc(list(qualifying_df["ticker"].unique()))
        except Exception as e:
            logger.warning(f"[OPT] prefetch_daily_ohlc pre-warm failed: {e}")

        _GRID_CTX.update(ctx)
        try:
            chunk_size = max(1, math.ceil(n_points / (n_workers * 4)))
            chunks = [
                list(range(i, min(i + chunk_size, n_points)))
                for i in range(0, n_points, chunk_size)
            ]
            completed = 0
            mp_ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp_ctx) as pool:
                futures = {pool.submit(_run_grid_chunk, chunk): chunk for chunk in chunks}
                for future in as_completed(futures):
                    chunk = futures[future]
                    try:
                        for idx, metric_val, detail in future.result():
                            results_flat[idx] = metric_val
                            details_flat[idx] = detail
                    except Exception as e:
                        logger.error(f"[OPT] Chunk {chunk[0]}-{chunk[-1]} failed: {e}")
                        for idx in chunk:
                            results_flat[idx] = np.nan
                            details_flat[idx] = {}
                    completed += len(chunk)
                    if task_id:
                        prog = round(5.0 + (completed / n_points) * 95.0, 2)
                        set_progress(task_id, prog)
                    elapsed = round(time.time() - t0, 1)
                    logger.info(f"[OPT] Progress: {completed}/{n_points} ({elapsed}s)")
        finally:
            _GRID_CTX.clear()
    else:
        signal_cache = {} if is_risk_only else None
        for idx in range(n_points):
            _, metric_val, detail = _run_grid_point(idx, ctx, signal_cache)
            results_flat[idx] = metric_val
            details_flat[idx] = detail

            if task_id:
                prog = round(5.0 + ((idx + 1) / n_points) * 95.0, 2)
                set_progress(task_id, prog)
                if (idx + 1) % 5 == 0:
                    logger.info(f"[PROGRESS] {task_id}: {prog}%")

            if (idx + 1) % 10 == 0:
                elapsed = round(time.time() - t0, 1)
                logger.info(f"[OPT] Progress: {idx+1}/{n_points} ({elapsed}s)")

    # Reshape to grid
    results_grid = results_flat.reshape(shape)

    # Run plateau analysis for the main metric
    plateau = _compute_plateau_analysis(results_grid, axes, param_configs, details_flat, shape)

    # Run plateau analysis for all other available metrics
    plateau_analyses = {}
    if details_flat and details_flat[0]:
        available_keys = [k for k in details_flat[0].keys() if k in METRICS]
        for m_key in available_keys:
            try:
                m_flat = np.array([
                    (d.get(m_key, 0.0) if (d and d.get(m_key) is not None) else 0.0)
                    for d in details_flat
                ])
                m_grid = m_flat.reshape(shape)
                plateau_analyses[m_key] = _compute_plateau_analysis(
                    m_grid, axes, param_configs, details_flat, shape
                )
            except Exception as e:
                logger.warning(f"[OPT] Failed to compute plateau analysis for {m_key}: {e}")

    elapsed = round(time.time() - t0, 1)
    logger.info(f"[OPT] Grid sweep complete in {elapsed}s")


    # Replace NaN with None for JSON serialization
    def clean(v):
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            return None
        return v

    return {
        "params": [
            {"id": pc["id"], "label": pc.get("label", pc["id"]), "values": axes[i]}
            for i, pc in enumerate(param_configs)
        ],
        "grid": [[clean(v) for v in row] for row in results_grid.tolist()]
                 if n_dims == 2 else results_grid.tolist(),
        "metric": metric,
        "metric_label": metric,
        "details": [d if d else {} for d in details_flat],
        "shape": list(shape),
        "plateau_analysis": plateau,
        "plateau_analyses": plateau_analyses,
        "elapsed_seconds": elapsed,
    }


# ---------------------------------------------------------------------------
# Plateau analysis
# ---------------------------------------------------------------------------

def _compute_plateau_analysis(
    grid: np.ndarray,
    axes: list[list],
    param_configs: list[dict],
    details_flat: list,
    shape: tuple,
) -> dict:
    """
    Compute robust plateau analysis:
    - Robust Plateau: region with lowest gradient (most stable)
    - Local Stability: max neighbor-averaged metric
    - Robust Center: geometric center of the most stable zone
    """
    n_dims = len(shape)
    if n_dims < 2:
        return {}

    # Replace NaN with 0 for analysis
    clean_grid = np.nan_to_num(grid, nan=0.0)

    # --- Gradient-based plateau detection ---
    # Compute gradient magnitude
    gradients = np.gradient(clean_grid)
    if isinstance(gradients, np.ndarray):
        grad_magnitude = np.abs(gradients)
    else:
        grad_magnitude = np.sqrt(sum(g**2 for g in gradients))

    # Neighbor average (local stability metric)
    from scipy.ndimage import uniform_filter
    neighbor_avg = uniform_filter(clean_grid, size=3, mode='nearest')
    neighbor_var = uniform_filter((clean_grid - neighbor_avg)**2, size=3, mode='nearest')

    # Stability score: high metric value + low variance
    max_val = np.max(np.abs(clean_grid)) if np.max(np.abs(clean_grid)) > 0 else 1.0
    stability_score = neighbor_avg / max_val - np.sqrt(neighbor_var) / max_val

    # Find the peak
    peak_idx = np.unravel_index(np.argmax(clean_grid), shape)
    peak_value = float(clean_grid[peak_idx])
    peak_coords = {
        param_configs[d]["label"]: float(axes[d][peak_idx[d]])
        for d in range(n_dims)
    }

    # Find robust plateau: region with highest stability score
    # Use a threshold: all cells within top 20% stability
    threshold = np.percentile(stability_score, 80)
    plateau_mask = stability_score >= threshold

    # Find the connected region with highest average performance
    plateau_indices = np.argwhere(plateau_mask)
    if len(plateau_indices) == 0:
        plateau_indices = np.argwhere(clean_grid >= np.percentile(clean_grid, 75))

    plateau_values = [clean_grid[tuple(idx)] for idx in plateau_indices]
    plateau_mean = float(np.mean(plateau_values)) if plateau_values else 0
    plateau_std = float(np.std(plateau_values)) if plateau_values else 0

    # Geometric center of plateau
    if len(plateau_indices) > 0:
        center_grid_idx = np.mean(plateau_indices, axis=0)
        robust_center = {}
        for d in range(n_dims):
            idx = int(round(center_grid_idx[d]))
            idx = min(idx, len(axes[d]) - 1)
            robust_center[param_configs[d]["label"]] = float(axes[d][idx])
    else:
        robust_center = peak_coords

    # Get plateau metrics (PF, Return/DD at the plateau center)
    center_flat_idx = 0
    if len(plateau_indices) > 0:
        center = [int(round(c)) for c in center_grid_idx]
        center = [min(c, s - 1) for c, s in zip(center, shape)]
        center_flat_idx = int(np.ravel_multi_index(center, shape))

    center_details = details_flat[center_flat_idx] if center_flat_idx < len(details_flat) and details_flat[center_flat_idx] else {}

    # Best stability point
    best_stability_idx = np.unravel_index(np.argmax(stability_score), shape)
    best_stability_value = float(clean_grid[best_stability_idx])
    best_stability_flat = int(np.ravel_multi_index(best_stability_idx, shape))
    best_stability_details = details_flat[best_stability_flat] if best_stability_flat < len(details_flat) and details_flat[best_stability_flat] else {}

    degradation = peak_value - plateau_mean if peak_value != 0 else 0

    return {
        "peak": {
            "value": _safe(peak_value),
            "coordinates": peak_coords,
        },
        "robust_plateau": {
            "mean_value": _safe(plateau_mean),
            "std_value": _safe(plateau_std),
            "size": int(len(plateau_indices)),
            "profit_factor": _safe(center_details.get("profit_factor", 0)),
            "return_dd": _safe(center_details.get("dd_return", 0)),
            "total_return": _safe(center_details.get("total_return", 0)),
        },
        "local_stability": {
            "best_value": _safe(best_stability_value),
            "coordinates": {
                param_configs[d]["label"]: float(axes[d][best_stability_idx[d]])
                for d in range(n_dims)
            },
            "profit_factor": _safe(best_stability_details.get("profit_factor", 0)),
            "return_dd": _safe(best_stability_details.get("dd_return", 0)),
        },
        "robust_center": {
            "coordinates": robust_center,
            "degradation_from_peak": _safe(degradation),
        },
    }


def _safe(v):
    if v is None:
        return None
    try:
        f = float(v)
        return f if not (np.isnan(f) or np.isinf(f)) else None
    except (TypeError, ValueError):
        return None
