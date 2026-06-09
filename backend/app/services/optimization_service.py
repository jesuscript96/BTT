"""
Optimization service for parameter grid sweep and robust plateau analysis.
Extracts tunable parameters from strategy JSON, runs grid of backtests,
computes surface data and identifies robust parameter regions.
"""

import copy
import json
import logging
import time
from itertools import product

import numpy as np

from app.services.data_service import get_strategy, fetch_dataset_data
from app.services.backtest_service import run_backtest

logger = logging.getLogger("backtester.optimization")

# Global dict to track progress of long-running optimizations (in-memory for local use)
OPTIMIZATION_PROGRESS = {}

# Global dict to store completed optimization results (in-memory for local use)
OPTIMIZATION_RESULTS = {}

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
                # Generate clean integer steps based on matrix dimension (steps)
                if steps > 0:
                    step_size = max(1, int(round((v_max_int - v_min_int) / steps)))
                    values = [v_min_int + (i + 1) * step_size for i in range(steps)]
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
        OPTIMIZATION_PROGRESS[task_id] = 1.0

    # Fetch dataset once (fast, with DB-level date/preconditions filters)
    qualifying_df, intraday_df = fetch_dataset_data(
        dataset_id,
        req_start_date=start_date,
        req_end_date=end_date,
        preconditions=fetch_preconditions,
        apply_day=apply_day,
    )

    if task_id:
        OPTIMIZATION_PROGRESS[task_id] = 5.0

    # Apply date filters (fallback in case database didn't apply them)
    if start_date:
        intraday_df = intraday_df[intraday_df["date"].astype(str) >= start_date]
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) >= start_date]
    if end_date:
        intraday_df = intraday_df[intraday_df["date"].astype(str) <= end_date]
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) <= end_date]

    # Apply In-Sample split percentage (is_percent) filter to keep only IS days for optimization
    if is_percent < 100.0:
        unique_dates = sorted(intraday_df["date"].unique())
        n_dates = len(unique_dates)
        if n_dates > 0:
            cutoff_idx = max(1, int(n_dates * is_percent / 100.0))
            cutoff_date = unique_dates[cutoff_idx - 1]
            intraday_df = intraday_df[intraday_df["date"] <= cutoff_date]
            qualifying_df = qualifying_df[qualifying_df["date"] <= cutoff_date]
            logger.info(f"[OPT] In-Sample split filter applied: kept first {cutoff_idx} of {n_dates} dates (up to {cutoff_date}) using is_percent={is_percent}%")

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
    signal_cache = {} if is_risk_only else None

    if is_risk_only:
        logger.info("[OPT] Risk-only parameters detected — signal caching ENABLED")
    else:
        logger.info("[OPT] Indicator parameters detected — signal caching disabled")

    # Create grid points
    grid_points = list(product(*axes))
    n_dims = len(param_configs)
    shape = tuple(len(a) for a in axes)

    results_flat = np.full(len(grid_points), np.nan)
    details_flat = [None] * len(grid_points)

    logger.info(f"[OPT] Starting grid sweep: {len(grid_points)} points, shape={shape}")

    for idx, point in enumerate(grid_points):
        # Clone strategy definition and set parameter values
        modified_def = copy.deepcopy(base_def)
        for dim, val in enumerate(point):
            path = param_configs[dim]["path"]
            _set_nested_value(modified_def, path, val)

        # If optimizing preconditions, we must re-evaluate them for this point
        if opt_preconds:
            point_preconditions = modified_def.get("postgap_preconditions", [])
            from app.services.data_service import _evaluate_postgap_preconditions
            point_qualifying_df = _evaluate_postgap_preconditions(qualifying_df, point_preconditions)
            
            valid_keys = set(zip(point_qualifying_df["date"].astype(str), point_qualifying_df["ticker"]))
            point_groups = [g for g in precomputed_groups if (str(g[0][0])[:10], g[0][1]) in valid_keys]
            n_groups_point = len(point_groups)
        else:
            point_qualifying_df = qualifying_df
            point_groups = precomputed_groups
            n_groups_point = n_groups

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
                n_groups_hint=n_groups_point,
                _signal_cache=signal_cache,
            )
            agg = bt_result.get("aggregate_metrics", {})
            metric_val = agg.get(metric_key, 0)
            results_flat[idx] = float(metric_val) if metric_val is not None else np.nan
            details_flat[idx] = {
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
        except Exception as e:
            logger.warning(f"[OPT] Point {idx}/{len(grid_points)} failed: {e}")
            results_flat[idx] = np.nan
            details_flat[idx] = {}

        if task_id:
            prog = round(((idx + 1) / len(grid_points)) * 100, 2)
            OPTIMIZATION_PROGRESS[task_id] = prog
            if (idx + 1) % 5 == 0:
                logger.info(f"[PROGRESS] {task_id}: {prog}%")

        if (idx + 1) % 10 == 0:
            elapsed = round(time.time() - t0, 1)
            logger.info(f"[OPT] Progress: {idx+1}/{len(grid_points)} ({elapsed}s)")

    # Reshape to grid
    results_grid = results_flat.reshape(shape)

    # Run plateau analysis
    plateau = _compute_plateau_analysis(results_grid, axes, param_configs, details_flat, shape)

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
