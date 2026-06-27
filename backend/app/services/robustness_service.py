"""
Robustness analysis service.

Submits saved Baúl strategies (rows of `backtest_results`) to stress tests:
  * Module 1 — Monte Carlo bootstrap (resampling with replacement)
  * Module 2 — Walk-Forward Analysis (WFO, heavy → background task)
  * Module 3 — Locate/slippage sensitivity
  * Module 4 — Black Swan simulator + post-swan ruin metrics

Design rules (docs/robustez/06_PROMPT_MAESTRO_EJECUCION.md §1):
  * All logic lives here; routers only validate and delegate.
  * The engine is NEVER imported directly — we only call existing services
    (montecarlo_service, what_if_service, optimization_service, backtest_service).
  * The selector identifier is a `run_id` (= backtest_results.id). Trades are
    read from `results_json["trades"]`, NOT from the `strategies` table.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import numpy as np

from app.database import get_user_db_connection

# Base epoch for chart timestamps (mirrors montecarlo_service convention).
_BASE_TS = 1_000_000_000
_PERIOD_FACTOR = {
    "mes": 1.0 / 12.0, "month": 1.0 / 12.0,
    "trimestre": 1.0 / 4.0, "quarter": 1.0 / 4.0,
    "año": 1.0, "ano": 1.0, "year": 1.0, "anual": 1.0,
}
# Fallback trades/year when the run has no parseable dates (PRD §07: ~260
# trading days/year ⇒ a quarter ≈ 65 trades).
_DEFAULT_TRADES_PER_YEAR = 260.0


class RobustnessError(Exception):
    """Domain error carrying a stable code that the router maps to HTTP.

    Codes mirror docs/robustez/PRD_ROBUSTEZ.md §3.5:
      * INVALID_STRATEGY        -> 400
      * PARAMETER_OUT_OF_BOUNDS -> 400
      * PROCESSING_ERROR        -> 500
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _parse_results_json(raw) -> dict:
    """DuckDB JSON columns come back as str (when inserted via json.dumps) or
    already-decoded objects depending on the driver path. Normalise to dict."""
    if raw is None:
        return {}
    if isinstance(raw, (dict, list)):
        return raw  # already decoded
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RobustnessError(
            "PROCESSING_ERROR", "Stored backtest result is not valid JSON."
        ) from exc


def _load_trades(run_id: str, con=None) -> tuple[list[dict], dict]:
    """Load the trade list (and full results_json) for a saved Baúl run.

    `run_id` is a `backtest_results.id`. The connection is injectable so unit
    tests can pass an isolated in-memory DB without touching real data.

    Raises:
        RobustnessError(INVALID_STRATEGY) if the run does not exist.
        RobustnessError(INVALID_STRATEGY) if the run has zero trades
            (a bootstrap/sensitivity analysis is meaningless without trades).
    """
    own = con is None
    if con is None:
        con = get_user_db_connection(read_only=True)
    try:
        row = con.execute(
            "SELECT results_json FROM backtest_results WHERE id = ?", (run_id,)
        ).fetchone()
    finally:
        if own:
            con.close()

    if row is None:
        raise RobustnessError(
            "INVALID_STRATEGY",
            "La estrategia seleccionada no existe o no tiene un backtest válido ejecutado.",
        )

    results_json = _parse_results_json(row[0])
    trades = results_json.get("trades", []) or []
    if len(trades) == 0:
        raise RobustnessError(
            "INVALID_STRATEGY", "No trades available for bootstrap"
        )
    return trades, results_json


def _load_strategy_def(run_id: str, con=None) -> dict:
    """Load the strategy DEFINITION behind a saved run (needed by WFO to
    re-optimize). Resolves run -> strategy_ids[0] -> strategies.definition.

    Returns the parsed definition dict. Raises INVALID_STRATEGY if neither the
    run nor its strategy/definition can be resolved.
    """
    own = con is None
    if con is None:
        con = get_user_db_connection(read_only=True)
    try:
        row = con.execute(
            "SELECT strategy_ids FROM backtest_results WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RobustnessError(
                "INVALID_STRATEGY",
                "La estrategia seleccionada no existe o no tiene un backtest válido ejecutado.",
            )
        strategy_ids = _parse_results_json(row[0])
        if not strategy_ids:
            raise RobustnessError(
                "INVALID_STRATEGY", "El run guardado no referencia ninguna estrategia."
            )
        strat_row = con.execute(
            "SELECT definition FROM strategies WHERE id = ?", (strategy_ids[0],)
        ).fetchone()
    finally:
        if own:
            con.close()

    if strat_row is None:
        raise RobustnessError(
            "INVALID_STRATEGY", "La estrategia referenciada por el run no existe."
        )
    return _parse_results_json(strat_row[0])


def _net_profit(trades: list[dict]) -> float:
    """Sum of trade PnL (base net profit before extra frictions)."""
    return float(sum(t.get("pnl", 0.0) for t in trades))


def _extract_pnls(trades: list[dict]) -> list[float]:
    """PnL array used by every bootstrap module."""
    return [float(t.get("pnl", 0.0)) for t in trades]


# ──────────────────────────────────────────────────────────────────────────
# Shared bootstrap primitives (numpy)
# ──────────────────────────────────────────────────────────────────────────

def _years_span(trades: list[dict]) -> Optional[float]:
    """Span (in years) covered by the trade dates, or None if unparseable."""
    dates = []
    for t in trades:
        d = (t.get("date") or "")[:10]
        if not d:
            continue
        try:
            dates.append(datetime.strptime(d, "%Y-%m-%d"))
        except ValueError:
            continue
    if len(dates) < 2:
        return None
    span_days = (max(dates) - min(dates)).days
    return span_days / 365.25 if span_days > 0 else None


def _compute_k(trades: list[dict], n_trades_limit: int, period_unit: Optional[str]) -> int:
    """Number of bootstrap steps K (PRD Regla 1). With a period_unit, scale the
    historical trades/year by the period factor; otherwise use n_trades_limit."""
    M = len(trades)
    if not period_unit:
        return max(1, int(n_trades_limit))
    factor = _PERIOD_FACTOR.get(str(period_unit).strip().lower())
    if factor is None:
        return max(1, int(n_trades_limit))
    years = _years_span(trades)
    trades_per_year = (M / years) if (years and years > 0) else _DEFAULT_TRADES_PER_YEAR
    return max(1, int(round(trades_per_year * factor)))


def _bootstrap_curves(
    pnls: np.ndarray, init_cash: float, simulations: int, k: int, rng
) -> np.ndarray:
    """`simulations` equity curves of length k+1, sampling pnls WITH replacement.
    Shape: (simulations, k+1), first column = init_cash."""
    sampled = rng.choice(pnls, size=(simulations, k), replace=True)
    curves = np.empty((simulations, k + 1))
    curves[:, 0] = init_cash
    curves[:, 1:] = init_cash + np.cumsum(sampled, axis=1)
    return curves


def _max_drawdowns_pct(curves: np.ndarray) -> np.ndarray:
    """Per-curve maximum drawdown as a negative percentage."""
    running_max = np.maximum.accumulate(curves, axis=1)
    safe = np.where(running_max > 0, running_max, 1.0)
    dd = (curves - running_max) / safe
    return dd.min(axis=1) * 100.0


def _ruin_probability(curves: np.ndarray, ruin_threshold: float) -> float:
    """% of curves that EVER touch (≤) the ruin threshold."""
    touched = np.any(curves <= ruin_threshold, axis=1)
    return round(float(touched.mean()) * 100.0, 2)


def _curve_to_points(values: np.ndarray) -> list[dict]:
    return [
        {"time": _BASE_TS + j * 86400, "value": round(float(v), 2)}
        for j, v in enumerate(values)
    ]


# ──────────────────────────────────────────────────────────────────────────
# Module 1 — Monte Carlo bootstrap (with replacement)
# ──────────────────────────────────────────────────────────────────────────

def run_montecarlo_bootstrap(
    trades: list[dict],
    init_cash: float = 10000.0,
    simulations: int = 1000,
    ruin_pct: float = 10.0,
    n_trades_limit: int = 500,
    period_unit: Optional[str] = None,
    rng=None,
) -> dict:
    """PRD §2.6 Regla 1 + §3.1 response. `rng` is injectable for deterministic tests."""
    pnls = np.asarray(_extract_pnls(trades), dtype=float)
    if pnls.size == 0:
        raise RobustnessError("INVALID_STRATEGY", "No trades available for bootstrap")
    if simulations <= 0 or simulations > 10000:
        raise RobustnessError("PARAMETER_OUT_OF_BOUNDS", "simulations must be in (0, 10000].")
    if rng is None:
        rng = np.random.default_rng()

    k = _compute_k(trades, n_trades_limit, period_unit)
    curves = _bootstrap_curves(pnls, init_cash, simulations, k, rng)

    max_dds = _max_drawdowns_pct(curves)
    ruin_threshold = init_cash * (ruin_pct / 100.0)
    final_balances = curves[:, -1]

    percentiles: dict[str, list[dict]] = {}
    for p in (5, 25, 50, 75, 95):
        percentiles[f"p{p}"] = _curve_to_points(np.percentile(curves, p, axis=0))

    return {
        "simulations_run": int(simulations),
        "ruin_probability": _ruin_probability(curves, ruin_threshold),
        "worst_drawdown": round(float(max_dds.min()), 2),
        "median_drawdown": round(float(np.percentile(max_dds, 50)), 2),
        "extreme_drawdown_p95": round(float(np.percentile(max_dds, 5)), 2),
        "extreme_drawdown_p99": round(float(np.percentile(max_dds, 1)), 2),
        "probability_negative_return": round(
            float(np.mean(final_balances < init_cash)) * 100.0, 2
        ),
        "n_trades_calculated": int(k),
        "percentiles": percentiles,
    }


# ──────────────────────────────────────────────────────────────────────────
# Module 3 — Locate / slippage sensitivity
# ──────────────────────────────────────────────────────────────────────────

def _is_short(trade: dict) -> bool:
    return str(trade.get("direction", "")).lower() in ("short", "sell", "s")


def critical_locate_threshold(trades: list[dict]) -> Optional[float]:
    """PRD §2.6 Regla 3: locate %/share at which net profit = 0.
    Returns None if there are no shorts or the denominator is 0."""
    notional = sum(
        abs(float(t.get("size", 0.0)) * float(t.get("entry_price", 0.0)))
        for t in trades
        if _is_short(t)
    )
    if notional <= 0:
        return None
    np_base = _net_profit(trades)
    return round(np_base / notional * 100.0, 4)


def _frange(lo: float, hi: float, step: float) -> list[float]:
    out, v = [], lo
    if step <= 0:
        raise RobustnessError("PARAMETER_OUT_OF_BOUNDS", "locate step must be > 0.")
    while v <= hi + 1e-9:
        out.append(round(v, 4))
        v += step
    return out


def run_sensitivity(
    trades: list[dict],
    locate_range: dict,
    slippage_probability: float = 0.0,
    slippage_value: float = 0.0,
    init_cash: float = 10000.0,
    rng=None,
) -> dict:
    """PRD §3.3. One equity curve per locate level; analytical critical threshold.
    Optional stochastic slippage is applied to the working PnLs first."""
    if rng is None:
        rng = np.random.default_rng()
    lo = float(locate_range.get("min", 0.5))
    hi = float(locate_range.get("max", 3.0))
    step = float(locate_range.get("step", 0.5))
    locates = _frange(lo, hi, step)

    threshold = critical_locate_threshold(trades)

    # Per-trade notional for shorts (locate applies linearly to short notional).
    notional = np.array(
        [
            abs(float(t.get("size", 0.0)) * float(t.get("entry_price", 0.0)))
            if _is_short(t) else 0.0
            for t in trades
        ]
    )
    base_pnls = np.asarray(_extract_pnls(trades), dtype=float)

    # Stochastic slippage: with prob p%, subtract slippage_value from that trade's PnL.
    working = base_pnls.copy()
    if slippage_probability and slippage_probability > 0:
        hit = rng.random(working.size) < (slippage_probability / 100.0)
        working = working - hit * float(slippage_value)

    curves: dict[str, list[dict]] = {}
    for c in locates:
        net = working - notional * (c / 100.0)
        equity = init_cash + np.cumsum(net)
        equity = np.insert(equity, 0, init_cash)
        curves[f"locate_{c}"] = _curve_to_points(equity)

    return {"critical_locate_threshold": threshold, "curves": curves}


# ──────────────────────────────────────────────────────────────────────────
# Module 4 — Black Swan simulator + post-swan metrics
# ──────────────────────────────────────────────────────────────────────────

def _zone(ruin_pct: float, dd_pct: float) -> str:
    """PRD §07 minuta colors. dd_pct is a positive magnitude."""
    if ruin_pct < 5.0 and dd_pct < 20.0:
        return "GREEN"
    if ruin_pct <= 20.0 and dd_pct <= 40.0:
        return "YELLOW"
    return "RED"


def _avg_loss(pnls: np.ndarray) -> float:
    """Mean absolute loss across losing trades (0 if none)."""
    losses = pnls[pnls < 0]
    return float(np.abs(losses).mean()) if losses.size else 0.0


def run_black_swan(
    trades: list[dict],
    init_cash: float = 10000.0,
    black_swan_count: int = 3,
    severity_multiplier: float = 10.0,
    ruin_pct: float = 10.0,
    rng=None,
) -> dict:
    """PRD §2.6 Regla 4 + §3.4. Injects extreme losses, measures recovery time
    and post-swan ruin risk, and builds a position-size × severity matrix."""
    pnls = np.asarray(_extract_pnls(trades), dtype=float)
    if pnls.size == 0:
        raise RobustnessError("INVALID_STRATEGY", "No trades available for bootstrap")
    if rng is None:
        rng = np.random.default_rng()

    ruin_threshold = init_cash * (ruin_pct / 100.0)
    swan_loss = _avg_loss(pnls) * float(severity_multiplier)

    ttr = _time_to_recovery(pnls, init_cash, black_swan_count, swan_loss, rng)
    post_swan_risk = _post_swan_ruin_risk(
        pnls, init_cash, swan_loss * max(1, black_swan_count), ruin_threshold, rng
    )

    matrix = []
    for pos in (1.0, 2.0, 5.0):
        for sev in (severity_multiplier / 2.0, severity_multiplier):
            scaled = pnls * pos                       # larger position ⇒ larger swings
            cell_swan = _avg_loss(pnls) * sev * max(1, black_swan_count)
            curves = _bootstrap_curves(scaled, init_cash, 500, 100, rng)
            # Apply the swan as an upfront capital hit on each curve.
            curves = curves - cell_swan
            dd = float(np.abs(_max_drawdowns_pct(curves).min()))
            ruin = _ruin_probability(curves, ruin_threshold)
            matrix.append(
                {
                    "position_size_pct": round(pos, 2),
                    "severity_multiplier": round(sev, 2),
                    "ruin_probability": ruin,
                    "max_drawdown": round(dd, 2),
                    "zone": _zone(ruin, dd),
                }
            )

    return {
        "time_to_recovery_trades": ttr,
        "post_swan_ruin_risk_100t": post_swan_risk,
        "sensitivity_matrix": matrix,
    }


def _time_to_recovery(pnls, init_cash, count, swan_loss, rng, sims=200) -> int:
    """Average #trades to reclaim the pre-swan equity peak after the swan hits."""
    n = pnls.size
    ttrs = []
    for _ in range(sims):
        seq = rng.choice(pnls, size=n, replace=True)
        equity = init_cash + np.cumsum(seq)
        swan_at = int(rng.integers(0, n)) if n > 0 else 0
        peak = float(equity[swan_at])
        post = equity[swan_at:] - swan_loss * max(1, count)
        recovered = np.where(post >= peak)[0]
        if recovered.size:
            ttrs.append(int(recovered[0]))
    return int(round(float(np.mean(ttrs)))) if ttrs else 0


def _post_swan_ruin_risk(pnls, init_cash, total_swan_loss, ruin_threshold, rng) -> float:
    """PRD Regla 4: bootstrap 1000×100 starting from capital after the swan hit."""
    start_capital = init_cash - total_swan_loss
    if start_capital <= ruin_threshold:
        return 100.0
    curves = _bootstrap_curves(pnls, start_capital, 1000, 100, rng)
    return _ruin_probability(curves, ruin_threshold)


# ──────────────────────────────────────────────────────────────────────────
# Module 2 — Walk-Forward Analysis (WFO)
# Pure helpers (testable without the engine) + heavy orchestrator (background).
# ──────────────────────────────────────────────────────────────────────────

WFO_MAX_COMBOS = 50  # Decisión §07-A (reversible): cap del MVP.


def _walk_forward_windows(
    dates: list[str], is_pct: float, oos_pct: float, step_pct: float
) -> list[dict]:
    """Roll IS/OOS windows over the sorted unique dates.

    Anti-lookahead guarantee: within every window, every IS date is strictly
    before every OOS date (no overlap). Returns a list of
    {is: [...], oos: [...]} windows. A window is only emitted if both slices are
    non-empty (a full OOS block fits)."""
    n = len(dates)
    if n == 0:
        return []
    if not (0 < is_pct < 100 and 0 < oos_pct <= 100 and step_pct > 0):
        raise RobustnessError("PARAMETER_OUT_OF_BOUNDS", "Invalid IS/OOS/step percentages.")
    is_len = max(1, int(round(n * is_pct / 100.0)))
    oos_len = max(1, int(round(n * oos_pct / 100.0)))
    step = max(1, int(round(n * step_pct / 100.0)))

    windows = []
    i = 0
    while i + is_len + oos_len <= n:
        is_slice = dates[i : i + is_len]
        oos_slice = dates[i + is_len : i + is_len + oos_len]
        if is_slice and oos_slice:
            windows.append({"is": is_slice, "oos": oos_slice})
        i += step
    # Guarantee at least one window when there is room for IS + a partial OOS.
    if not windows and n > is_len:
        windows.append({"is": dates[:is_len], "oos": dates[is_len:]})
    return windows


def _wfe(oos_metric: float, is_metric: float) -> float:
    """Walk-Forward Efficiency (%). PRD Regla 2: IS metric ≤ 0 ⇒ 0.0 (avoid /0)."""
    if is_metric is None or is_metric <= 0:
        return 0.0
    return round(float(oos_metric) / float(is_metric) * 100.0, 2)


def _win_rate_penalty(is_win_rate: float, oos_win_rate: float) -> float:
    """PRD Regla 2: WinRate_IS − WinRate_OOS (percentage points)."""
    return round(float(is_win_rate) - float(oos_win_rate), 2)


def _build_param_axes(param_configs: list[dict], max_combos: int = WFO_MAX_COMBOS) -> list[dict]:
    """Turn request param_configs (min/max/steps) into explicit value arrays,
    capping the cartesian product at `max_combos` (MVP guard)."""
    axes = []
    for pc in param_configs:
        if pc.get("values"):
            values = list(pc["values"])
        else:
            steps = int(pc.get("steps", 5))
            values = list(
                np.linspace(float(pc.get("min", 1)), float(pc.get("max", 10)), max(1, steps))
            )
        axes.append({"id": pc.get("id"), "path": pc["path"], "values": values})

    # Cap the cartesian product: trim each axis proportionally until under the cap.
    def _product(a):
        p = 1
        for ax in a:
            p *= max(1, len(ax["values"]))
        return p

    while _product(axes) > max_combos:
        widest = max(axes, key=lambda ax: len(ax["values"]))
        if len(widest["values"]) <= 1:
            break
        widest["values"] = widest["values"][:: 2] if len(widest["values"]) > 2 else widest["values"][:1]
    return axes


def run_walk_forward(
    run_id: str,
    dataset_id: str,
    is_pct: float = 70.0,
    oos_pct: float = 30.0,
    step_pct: float = 30.0,
    metric: str = "sharpe",
    param_configs: Optional[list[dict]] = None,
    init_cash: float = 10000.0,
    progress_cb=None,
) -> dict:
    """Heavy WFO orchestrator (runs in a background task). Re-optimizes params on
    each IS window (via run_optimization_grid) and evaluates blind on OOS (via
    run_backtest_orchestrator). Engine imports are LAZY to keep the module light
    and the pure helpers unit-testable.

    `progress_cb(pct)` is an optional callback (the router wires it to set_progress).
    """
    # Lazy heavy imports (numba/duckdb engine path).
    from app.services.optimization_service import run_optimization_grid, _set_nested_value
    from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator
    from app.services.backtest_service import _aggregate_metrics  # noqa: F401 (parity helper)
    import copy

    param_configs = param_configs or []
    strategy_def = _load_strategy_def(run_id)
    trades, _ = _load_trades(run_id)

    # Date universe = sorted unique trade dates of the saved run.
    dates = sorted({(t.get("date") or "")[:10] for t in trades if t.get("date")})
    windows = _walk_forward_windows(dates, is_pct, oos_pct, step_pct)
    if not windows:
        raise RobustnessError("PARAMETER_OUT_OF_BOUNDS", "Not enough data for a single WFO window.")

    axes = _build_param_axes(param_configs)
    grid_configs = [{"id": a["id"], "path": a["path"], "values": a["values"]} for a in axes]

    is_metric_vals, oos_metric_vals = [], []
    is_win_rates, oos_win_rates = [], []
    oos_trades_all: list[dict] = []
    heatmap_rows: list[dict] = []

    for wi, win in enumerate(windows):
        is_start, is_end = win["is"][0], win["is"][-1]
        oos_start, oos_end = win["oos"][0], win["oos"][-1]

        # 1) Optimize on IS.
        grid = run_optimization_grid(
            strategy_id=None,
            dataset_id=dataset_id,
            param_configs=grid_configs,
            metric=metric,
            backtest_params={"start_date": is_start, "end_date": is_end, "init_cash": init_cash},
            strategy_definition=strategy_def,
        )
        best = _best_grid_cell(grid, grid_configs)
        is_metric_vals.append(best["score"])
        is_win_rates.append(best.get("win_rate", 0.0))

        # 2) Apply best params, evaluate BLIND on OOS.
        tuned = copy.deepcopy(strategy_def)
        for cfg, val in zip(grid_configs, best["values"]):
            _set_nested_value(tuned, cfg["path"], val)
        oos_res = run_backtest_orchestrator(
            BacktestRequest(
                dataset_id=dataset_id,
                strategy_definition=tuned,
                init_cash=init_cash,
                start_date=oos_start,
                end_date=oos_end,
            )
        )
        oos_agg = oos_res.get("aggregate_metrics", {}) or {}
        oos_metric_vals.append(_metric_from_aggregate(oos_agg, metric))
        oos_win_rates.append(oos_agg.get("win_rate_pct", 0.0) or 0.0)
        oos_trades_all.extend(oos_res.get("trades", []) or [])

        for combo, score in zip(best["all_combos"], best["all_scores"]):
            heatmap_rows.append({"values": list(combo), "is_score": round(float(score), 4)})

        if progress_cb:
            progress_cb(round((wi + 1) / len(windows) * 100.0, 1))

    is_metric = float(np.mean(is_metric_vals)) if is_metric_vals else 0.0
    oos_metric = float(np.mean(oos_metric_vals)) if oos_metric_vals else 0.0
    is_wr = float(np.mean(is_win_rates)) if is_win_rates else 0.0
    oos_wr = float(np.mean(oos_win_rates)) if oos_win_rates else 0.0
    oos_dd = _concatenated_oos_drawdown(oos_trades_all, init_cash)

    return {
        "status": "completed",
        "progress": 100.0,
        "wfe": _wfe(oos_metric, is_metric),
        "win_rate_penalty": _win_rate_penalty(is_wr, oos_wr),
        "oos_max_drawdown": oos_dd,
        "is_metrics": {metric: round(is_metric, 4), "win_rate": round(is_wr, 2)},
        "oos_metrics": {metric: round(oos_metric, 4), "win_rate": round(oos_wr, 2)},
        "heatmap_matrix": {
            "parameters": [c["id"] for c in grid_configs],
            "data": heatmap_rows,
        },
        "windows": len(windows),
    }


def _metric_from_aggregate(agg: dict, metric: str) -> float:
    """Map a WFO metric name to the canonical _aggregate_metrics keys."""
    key_map = {
        "sharpe": "avg_sharpe", "sortino": "sortino_ratio", "calmar": "calmar_ratio",
        "return": "total_return_pct", "profit_factor": "avg_profit_factor",
        "win_rate": "win_rate_pct",
    }
    return float(agg.get(key_map.get(metric, metric), agg.get(metric, 0.0)) or 0.0)


def _best_grid_cell(grid: dict, grid_configs: list[dict]) -> dict:
    """Pick the best parameter combination from a run_optimization_grid result.

    Returns {values, score, win_rate, all_combos, all_scores}. Tolerant to the
    grid shape (1D/2D) by walking grid_details with itertools.product."""
    import itertools

    axes_values = [cfg["values"] for cfg in grid_configs]
    combos = list(itertools.product(*axes_values)) if axes_values else [()]
    details = grid.get("grid_details") or {}
    scores = details.get("scores") or details.get("values") or grid.get("flat_scores")

    if scores is None:
        # Fall back: a flat list under the metric key, else neutral zeros.
        flat = []
        for v in details.values():
            if isinstance(v, list):
                flat = _flatten(v)
                break
        scores = flat or [0.0] * len(combos)
    else:
        scores = _flatten(scores)

    scores = (scores + [0.0] * len(combos))[: len(combos)]
    best_idx = int(np.argmax(scores)) if scores else 0
    return {
        "values": list(combos[best_idx]) if combos else [],
        "score": float(scores[best_idx]) if scores else 0.0,
        "win_rate": 0.0,
        "all_combos": combos,
        "all_scores": scores,
    }


def _flatten(x) -> list:
    out = []
    for v in x:
        if isinstance(v, list):
            out.extend(_flatten(v))
        else:
            out.append(v)
    return out


def _concatenated_oos_drawdown(trades: list[dict], init_cash: float) -> float:
    """Max drawdown (%) over the chronologically concatenated OOS trades."""
    if not trades:
        return 0.0
    ordered = sorted(trades, key=lambda t: str(t.get("entry_time", t.get("date", ""))))
    pnls = np.array([float(t.get("pnl", 0.0)) for t in ordered])
    equity = init_cash + np.cumsum(pnls)
    equity = np.insert(equity, 0, init_cash)
    running_max = np.maximum.accumulate(equity)
    safe = np.where(running_max > 0, running_max, 1.0)
    dd = (equity - running_max) / safe
    return round(float(dd.min()) * 100.0, 2)
