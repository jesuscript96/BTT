"""
Runs backtests per ticker-date pair using translated strategy signals.
Pure numpy simulation — no vectorbt dependency.

Memory-optimised streaming architecture:
  Single-pass loop over groupby — signal generation + portfolio simulation
  happen for one day at a time so peak RSS stays well under 512 MB.
"""

import ctypes
import datetime
import gc
import logging
import sys
import time

import numpy as np
import pandas as pd

from app.services.strategy_engine import translate_strategy, _parse_risk_management, compile_strategy_def
from app.services.portfolio_sim import simulate

logger = logging.getLogger("backtester.engine")

# Pre-computed time boundaries for patch mask (avoid recreating per iteration)
_PATCH_START = datetime.time(8, 0)
_PATCH_END = datetime.time(8, 45)

# Cache for market session masks. Keyed by timestamp structure (not date),
# so all days with identical intraday structure share one entry.
_sessions_mask_cache: dict = {}



def _release_memory():
    if sys.platform == "linux":
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass


def run_backtest(
    intraday_df: pd.DataFrame = None,
    qualifying_df: pd.DataFrame = None,
    strategy_def: dict = None,
    init_cash: float = 10000.0,
    risk_r: float = 100.0,
    risk_type: str = "FIXED",
    fixed_ratio_delta: float = 500.0,
    size_by_sl: bool = False,
    fees: float = 0.0,
    fee_type: str = "PERCENT",
    slippage: float = 0.0,
    market_sessions: list[str] | None = None,
    custom_start_time: str | None = None,
    custom_end_time: str | None = None,
    locates_cost: float = 0.0,
    look_ahead_prevention: bool = False,
    day_group_iter=None,
    n_groups_hint: int = 0,
    monthly_expenses: float = 0.0,
    _signal_cache: dict | None = None,
    progress_callback=None,
) -> dict:
    t_total = time.time()

    qual_lookup = _build_qualifying_lookup(qualifying_df)
    del qualifying_df

    # Pre-compile strategy definition once — saves dict lookups per day inside the loop.
    compiled_strategy = compile_strategy_def(strategy_def) if strategy_def else None
    apply_day = strategy_def.get("apply_day", "gap_day") if strategy_def else "gap_day"

    empty_result = {
        "aggregate_metrics": _aggregate_metrics([], [], [], [], init_cash, risk_r),
        "day_results": [],
        "trades": [],
        "equity_curves": [],
        "global_equity": [],
        "global_drawdown": [],
    }

    # --- Choose data source: streaming iterator or monolithic DataFrame ---
    if day_group_iter is not None:
        group_source = day_group_iter
        n_groups = n_groups_hint
        logger.info(f"[INIT] streaming mode, ~{n_groups} groups expected")
    elif intraday_df is not None and not intraday_df.empty:
        grouped = intraday_df.groupby(["date", "ticker"])
        group_source = iter(grouped)
        n_groups = grouped.ngroups
        logger.info(f"[INIT] monolithic mode, {n_groups} groups")
    else:
        return empty_result

    all_trades: list[dict] = []
    all_equity: list[dict] = []
    day_results: list[dict] = []
    days_with_entries = 0
    scanned = 0
    t1 = time.time()

    # Tracking running stats for KELLY
    running_stats = {
        "win_count": 0,
        "loss_count": 0,
        "total_win_pnl": 0.0,
        "total_loss_pnl": 0.0,
        "win_rate": 0.5, # Default starting point
        "avg_win": 0.0,
        "avg_loss": 0.0
    }

    global_realized_pnl = 0.0
    current_date = None
    daily_pnl = 0.0

    for (date_raw, ticker_raw), day_df in group_source:
        scanned += 1
        if progress_callback is not None and scanned % 10 == 0:
            progress_callback(scanned, n_groups)
        day_df = day_df.sort_values("timestamp").reset_index(drop=True)
        if len(day_df) < 5:
            continue

        ticker = str(ticker_raw)
        date = str(date_raw)[:10]
        
        # When moving to a new day, add the previous day's PnL to the global pool
        if current_date is None:
            current_date = date
        elif date != current_date:
            global_realized_pnl += daily_pnl
            daily_pnl = 0.0
            current_date = date

        # Base cash for this sim run is initial + accumulated global PnL
        compounding_cash = init_cash + global_realized_pnl
        
        arrays = {
            "open": day_df["open"].values.astype(np.float64),
            "high": day_df["high"].values.astype(np.float64),
            "low": day_df["low"].values.astype(np.float64),
            "close": day_df["close"].values.astype(np.float64),
            "volume": day_df["volume"].values,
            "timestamp": day_df["timestamp"].values,
        }
        # Invert lookup from (ticker, date) to match original format
        daily_stats = qual_lookup.get((ticker_raw, date_raw), {})
        if daily_stats:
            daily_stats = _shift_daily_stats(daily_stats, apply_day)
        del day_df

        mini_df = pd.DataFrame(arrays)

        # --- Signal computation (with optional cache for risk-only optimization) ---
        cache_key = (ticker, date)

        if _signal_cache is not None and cache_key in _signal_cache:
            # Reuse cached entry/exit signals, only re-parse risk management
            cached = _signal_cache[cache_key]
            entries_arr = cached["entries"]
            exits_arr = cached["exits"]
            sig_direction = cached["direction"]
            sig_accept_reentries = cached["accept_reentries"]

            if not np.any(entries_arr):
                del mini_df
                continue

            # Re-parse risk management with current (modified) strategy_def
            risk = strategy_def.get("risk_management", {})
            sig_sl_stop, sig_sl_trail, sig_tp_stop, sig_trail_pct, sig_partial_tps = \
                _parse_risk_management(risk, mini_df, daily_stats, {})
        else:
            try:
                signals = translate_strategy(mini_df, strategy_def, daily_stats, compiled=compiled_strategy)
            except Exception:
                del mini_df
                continue
            if not signals["entries"].any():
                del mini_df, signals
                continue

            entries_arr = signals["entries"].values if hasattr(signals["entries"], "values") else np.asarray(signals["entries"])
            exits_arr = signals["exits"].values if hasattr(signals["exits"], "values") else np.asarray(signals["exits"])
            sig_direction = signals["direction"]
            sig_accept_reentries = signals.get("accept_reentries", False)
            sig_sl_stop = signals["sl_stop"]
            sig_sl_trail = signals["sl_trail"]
            sig_tp_stop = signals["tp_stop"]
            sig_trail_pct = signals.get("trail_pct")
            sig_partial_tps = signals.get("partial_take_profits")

            # Populate cache for subsequent optimization iterations
            if _signal_cache is not None:
                _signal_cache[cache_key] = {
                    "entries": entries_arr.copy(),
                    "exits": exits_arr.copy(),
                    "direction": sig_direction,
                    "accept_reentries": sig_accept_reentries,
                }

            del signals

        # --- Trim DataFrame and signals to the selected market session window ---
        # This is done AFTER signal translation so indicators have full-day context.
        # This ensures that the simulator's "last candle" (n-1) IS the session
        # boundary, so EOD exits happen at the end of the selected session.
        if market_sessions and "all" not in market_sessions:
            session_mask = _get_market_sessions_mask(
                mini_df["timestamp"], market_sessions, custom_start_time, custom_end_time
            )
            # Apply mask to mini_df and update arrays
            mini_df = mini_df[session_mask].reset_index(drop=True)
            if len(mini_df) < 2:
                del mini_df
                continue
            # Rebuild arrays from trimmed DataFrame
            arrays = {
                "open": mini_df["open"].values.astype(np.float64),
                "high": mini_df["high"].values.astype(np.float64),
                "low": mini_df["low"].values.astype(np.float64),
                "close": mini_df["close"].values.astype(np.float64),
                "volume": mini_df["volume"].values,
                "timestamp": mini_df["timestamp"].values,
            }
            
            # Apply mask to signals
            session_mask_np = session_mask.values if hasattr(session_mask, "values") else np.asarray(session_mask)
            entries_arr = entries_arr[session_mask_np]
            exits_arr = exits_arr[session_mask_np]

        # --- TEMPORARY PATCH FOR MISPRINTS ---
        # 8:00 to 8:45 restriction to ignore misprints
        ts_series = mini_df["timestamp"]
        if not pd.api.types.is_datetime64_any_dtype(ts_series):
            ts_series = pd.to_datetime(ts_series)
            
        # Avoid .dt.time which creates expensive python datetime.time objects
        patch_mask = (ts_series.dt.hour == 8) & (ts_series.dt.minute >= 0) & (ts_series.dt.minute < 45)
        patch_mask = patch_mask.values

        # If after masking we have no entries, skip simulation
        if not np.any(entries_arr):
            del mini_df
            continue

        try:
            sim_result = simulate(
                close=arrays["close"],
                open_=arrays["open"],
                high=arrays["high"],
                low=arrays["low"],
                entries=entries_arr,
                exits=exits_arr,
                direction=sig_direction,
                init_cash=compounding_cash,
                risk_r=risk_r,
                risk_type=risk_type,
                fixed_ratio_delta=fixed_ratio_delta,
                size_by_sl=size_by_sl,
                prev_stats=running_stats,
                fees=fees,
                fee_type=fee_type,
                slippage=slippage,
                locates_cost=locates_cost,
                look_ahead_prevention=look_ahead_prevention,
                sl_stop=sig_sl_stop,
                sl_trail=sig_sl_trail,
                tp_stop=sig_tp_stop,
                trail_pct=sig_trail_pct,
                accumulate=sig_accept_reentries,
                patch_mask=patch_mask,
                partial_take_profits=sig_partial_tps,
            )
        except Exception as exc:
            logger.warning(f"[STREAM] day {ticker} {date} failed: {exc}")
            del mini_df
            continue

        del mini_df

        eq_vals = sim_result["equity"]
        raw_trades = sim_result["trades"]

        if not raw_trades:
            del sim_result
            continue

        # Update running stats for Kelly Criterion
        for t in raw_trades:
            pnl = t["pnl"]
            daily_pnl += pnl  # Track today's PnL to roll over into tomorrow's compounding base
            if pnl > 0:
                running_stats["win_count"] += 1
                running_stats["total_win_pnl"] += pnl
            else:
                running_stats["loss_count"] += 1
                running_stats["total_loss_pnl"] += abs(pnl)
        
        total_finished = running_stats["win_count"] + running_stats["loss_count"]
        if total_finished > 0:
            running_stats["win_rate"] = running_stats["win_count"] / total_finished
            running_stats["avg_win"] = running_stats["total_win_pnl"] / running_stats["win_count"] if running_stats["win_count"] > 0 else 0.0
            running_stats["avg_loss"] = running_stats["total_loss_pnl"] / running_stats["loss_count"] if running_stats["loss_count"] > 0 else 0.0

        # Avoid pd.to_datetime parsing if array is already datetime kind natively
        ts_arr = arrays["timestamp"]
        if getattr(ts_arr.dtype, "kind", "") in ("M", "m"):
            timestamps = pd.Series(ts_arr)
            ts_epoch = ts_arr.astype("datetime64[s]").astype("int64")
        else:
            timestamps = pd.Series(pd.to_datetime(ts_arr))
            ts_epoch = timestamps.values.astype("datetime64[s]").astype("int64")

        # --- Calculate Risk Unit for "R" reporting ---
        if risk_type == "FIXED":
            risk_unit_dollar = risk_r
        elif risk_type == "PERCENT":
            risk_unit_dollar = compounding_cash * (risk_r / 100.0)
        elif risk_type == "KELLY":
            # In Kelly, 1R is the risk amount calculated by the formula
            # For reporting purposes, we use the risk amount used in the actual simulation
            risk_unit_dollar = sim_result.get("last_risk_amount", risk_r) 
        else:
            risk_unit_dollar = risk_r

        trades_records = _enrich_trades(
            raw_trades, timestamps, ticker, date, strategy_def, risk_unit_dollar,
            gap_pct=daily_stats.get("gap_pct"),
        )

        equity = _extract_equity_from_values(eq_vals, timestamps)

        stats = _extract_day_stats_from_values(eq_vals, ticker, date, trades_records, daily_stats.get("gap_pct"))

        all_equity.append({"ticker": ticker, "date": date, "equity": equity})
        all_trades.extend(trades_records)
        day_results.append(stats)
        days_with_entries += 1

        del sim_result, eq_vals, raw_trades, arrays, daily_stats

        if days_with_entries % 200 == 0:
            gc.collect()
            logger.info(
                f"[STREAM] {days_with_entries} days processed, "
                f"{scanned}/{n_groups} scanned ({round(time.time()-t1, 2)}s)"
            )

    # Final sweep of daily_pnl if the last day generated trades
    global_realized_pnl += daily_pnl

    del qual_lookup
    if intraday_df is not None:
        del intraday_df
    # Python's incremental GC handles these dels in background; no need to force.
    _release_memory()
    t_loop = time.time()
    total_days = days_with_entries
    print(f"[TIMING] loop completo ({total_days} días): {round(t_loop - t_total, 2)}s")
    logger.info(
        f"[STREAM] done: {days_with_entries} days with entries "
        f"({round(time.time()-t1, 2)}s)"
    )

    t4 = time.time()
    # Logic: global_eq is pure trades, global_eq_exp is trades - monthly_expenses
    global_eq, global_dd, global_eq_exp = _compute_global_equity_and_drawdown(
        all_trades, init_cash, monthly_expenses
    )
    aggregate = _aggregate_metrics(
        day_results, all_trades, global_eq, global_dd, init_cash, risk_r, monthly_expenses
    )
    logger.info(f"[AGG] aggregate+equity done ({round(time.time()-t4, 2)}s)")

    logger.info(
        f"[DONE] {len(day_results)} days, {len(all_trades)} trades, "
        f"total={round(time.time()-t_total, 2)}s"
    )

    return {
        "aggregate_metrics": aggregate,
        "day_results": day_results,
        "trades": all_trades,
        "equity_curves": all_equity,
        "global_equity": global_eq,
        "global_equity_expenses": global_eq_exp,
        "global_drawdown": global_dd,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shift_daily_stats(ds: dict, apply_day: str) -> dict:
    if not ds or apply_day == "gap_day":
        return ds

    ds = ds.copy()
    if apply_day == "gap_1_day":
        # Yesterday stats for T+1 is the gap day T
        ds["yesterday_high"] = ds.get("rth_high")
        ds["yesterday_low"] = ds.get("rth_low")
        ds["previous_close"] = ds.get("rth_close")
        ds["yesterday_open"] = ds.get("rth_open")
        ds["yesterday_volume"] = ds.get("rth_volume")

        # Today stats for T+1 is lead_1
        for key in ["rth_open", "rth_high", "rth_low", "rth_close", "rth_volume", "pm_high", "pm_low", "pm_volume"]:
            lead_key = f"lead_{key}_1"
            if lead_key in ds:
                ds[key] = ds[lead_key]

    elif apply_day == "gap_2_day":
        # Yesterday stats for T+2 is T+1 (lead_1)
        ds["yesterday_high"] = ds.get("lead_rth_high_1")
        ds["yesterday_low"] = ds.get("lead_rth_low_1")
        ds["previous_close"] = ds.get("lead_rth_close_1")
        ds["yesterday_open"] = ds.get("lead_rth_open_1")
        ds["yesterday_volume"] = ds.get("lead_rth_volume_1")

        # Today stats for T+2 is lead_2
        for key in ["rth_open", "rth_high", "rth_low", "rth_close", "rth_volume", "pm_high", "pm_low", "pm_volume"]:
            lead_key = f"lead_{key}_2"
            if lead_key in ds:
                ds[key] = ds[lead_key]

    return ds


def _build_qualifying_lookup(qualifying_df: pd.DataFrame) -> dict:
    if qualifying_df.empty:
        return {}
    # Vectorized: avoid slow iterrows() — convert entire DataFrame at once
    records = qualifying_df.to_dict(orient="records")
    return {
        (r["ticker"], str(r["date"])[:10]): r
        for r in records
    }


def _build_candles(ts_epoch: np.ndarray, arrays: dict) -> list[dict]:
    n = len(ts_epoch)
    candles = [None] * n
    for j in range(n):
        candles[j] = {
            "time": int(ts_epoch[j]),
            "open": float(arrays["open"][j]),
            "high": float(arrays["high"][j]),
            "low": float(arrays["low"][j]),
            "close": float(arrays["close"][j]),
            "volume": int(arrays["volume"][j]),
        }
    return candles


def _enrich_trades(
    raw_trades: list[dict],
    timestamps: pd.Series,
    ticker: str,
    date: str,
    strategy_def: dict,
    risk_unit_dollar: float,
    gap_pct: float | None = None,
) -> list[dict]:
    if not raw_trades:
        return []

    max_idx = len(timestamps) - 1
    # Convert timestamps to epoch seconds for chart marker matching
    ts_epoch = timestamps.values.astype("datetime64[s]").astype("int64")

    result = []
    for t in raw_trades:
        ei = min(t["entry_idx"], max_idx)
        xi = min(t["exit_idx"], max_idx)
        entry_ts = timestamps.iloc[ei]
        exit_ts = timestamps.iloc[xi]

        r_multiple = _compute_r_multiple(t["pnl"], risk_unit_dollar)

        result.append({
            "ticker": ticker,
            "date": date,
            "entry_time": str(entry_ts),
            "exit_time": str(exit_ts),
            "entry_idx": t["entry_idx"],
            "exit_idx": t["exit_idx"],
            # Epoch timestamps for correct chart marker placement
            "entry_time_epoch": int(ts_epoch[ei]),
            "exit_time_epoch": int(ts_epoch[xi]),
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "pnl": t["pnl"],
            "return_pct": t["return_pct"],
            "direction": t["direction"],
            "status": t["status"],
            "size": t["size"],
            "exit_reason": t["exit_reason"],
            "mae": t["mae"],
            "mfe": t.get("mfe", 0.0),
            "r_multiple": r_multiple,
            "entry_hour": entry_ts.hour,
            "entry_weekday": entry_ts.weekday(),
            "gap_pct": float(gap_pct) if gap_pct is not None else None,
        })
    return result



def _compute_r_multiple(pnl: float, risk_unit_dollar: float) -> float | None:
    """
    R-multiple is simply the PnL of the (partial) trade 
    divided by the 1R risk unit used for the whole trade.
    """
    if risk_unit_dollar <= 0:
        return None
    return round(pnl / risk_unit_dollar, 2)


# ---------------------------------------------------------------------------
# Equity extraction
# ---------------------------------------------------------------------------

_MAX_EQUITY_POINTS = 200


def _extract_equity_from_values(eq_vals: np.ndarray, timestamps: pd.Series) -> list[dict]:
    try:
        n = min(len(eq_vals), len(timestamps))
        if n == 0:
            return []
        ts_epoch = timestamps.iloc[:n].values.astype("datetime64[s]").astype("int64")
        vals = eq_vals[:n].astype(np.float64)
        if n > _MAX_EQUITY_POINTS:
            idx = np.linspace(0, n - 1, _MAX_EQUITY_POINTS, dtype=int)
            ts_epoch = ts_epoch[idx]
            vals = vals[idx]
        return [{"time": int(t), "value": float(v)} for t, v in zip(ts_epoch, vals)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Global equity & drawdown
# ---------------------------------------------------------------------------

def _compute_global_equity_and_drawdown(
    all_trades: list[dict],
    init_cash: float,
    monthly_expenses: float = 0.0
) -> tuple[list[dict], list[dict], list[dict]]:
    """Build equity curve as cumulative P&L per calendar day.

    Logic: start at init_cash, group trades by date, sum daily P&L,
    accumulate.  equity[day] = equity[prev_day] + sum(pnl of trades on day).
    """
    if not all_trades:
        return [], [], []

    # Group trade P&L by date
    daily_pnl: dict[str, float] = {}
    for trade in all_trades:
        date_str = trade.get("date", "")
        if not date_str:
            continue
        daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + trade.get("pnl", 0.0)

    if not daily_pnl:
        return [], [], []

    # Sort by date
    sorted_dates = sorted(daily_pnl.keys())

    # Construction: Point 0 = init_cash before any trades
    # Point i = end of day i
    equity_values = [init_cash]
    cumulative = init_cash
    for d in sorted_dates:
        cumulative += daily_pnl[d]
        equity_values.append(cumulative)

    values = np.array(equity_values, dtype=np.float64)

    # Use first date to infer a 'start' time (day before first trade)
    first_dt = pd.Timestamp(sorted_dates[0], tz="UTC")
    start_ts = int((first_dt - pd.Timedelta(days=1)).timestamp())
    times = [start_ts] + [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in sorted_dates]
    times_arr = np.array(times, dtype=np.int64)

    running_max = np.maximum.accumulate(values)
    dd_pct = np.where(running_max > 0, (values / running_max - 1) * 100, 0.0)

    # --- Compute Expenses Curve ---
    equity_exp_values = [init_cash]
    exp_cumulative = 0.0
    last_m = None

    for i, d in enumerate(sorted_dates):
        m = d[:7]  # YYYY-MM
        if last_m is None or m != last_m:
            exp_cumulative += monthly_expenses
            last_m = m
        equity_exp_values.append(equity_values[i + 1] - exp_cumulative)

    values_exp = np.array(equity_exp_values, dtype=np.float64)

    values_rounded = np.round(values, 2)
    values_exp_rounded = np.round(values_exp, 2)
    dd_rounded = np.round(dd_pct, 4)

    global_equity = [
        {"time": int(t), "value": float(v)} for t, v in zip(times_arr, values_rounded)
    ]
    global_equity_exp = [
        {"time": int(t), "value": float(v)} for t, v in zip(times_arr, values_exp_rounded)
    ]
    global_drawdown = [
        {"time": int(t), "value": float(d)} for t, d in zip(times_arr, dd_rounded)
    ]

    return global_equity, global_drawdown, global_equity_exp


# ---------------------------------------------------------------------------
# Per-day statistics
# ---------------------------------------------------------------------------

def _extract_day_stats_from_values(
    eq_vals: np.ndarray,
    ticker: str,
    date: str,
    trades_records: list[dict],
    gap_pct: float | None = None
) -> dict:
    empty = {
        "ticker": ticker, "date": date,
        "total_return_pct": 0, "max_drawdown_pct": 0, "win_rate_pct": 0,
        "total_trades": 0, "profit_factor": 0, "sharpe_ratio": 0,
        "sortino_ratio": 0, "expectancy": 0, "best_trade_pct": 0,
        "worst_trade_pct": 0, "init_value": 0, "end_value": 0,
        "gap_pct": float(gap_pct) if gap_pct is not None else None,
    }
    try:
        eq_arr = np.asarray(eq_vals, dtype=np.float64)
        if len(eq_arr) == 0:
            return empty

        start_val = float(eq_arr[0])
        end_val = float(eq_arr[-1])
        total_ret = (end_val / start_val - 1) * 100 if start_val > 0 else 0.0

        running_max = np.maximum.accumulate(eq_arr)
        dd_pct = np.where(running_max > 0, (eq_arr / running_max - 1) * 100, 0.0)
        max_dd = float(np.min(dd_pct))

        n_trades = len(trades_records)
        pnls = np.array([t["pnl"] for t in trades_records]) if trades_records else np.array([])
        wins = pnls[pnls > 0] if len(pnls) else np.array([])
        losses = pnls[pnls <= 0] if len(pnls) else np.array([])

        win_rate = (len(wins) / n_trades * 100) if n_trades > 0 else 0.0
        sum_wins = float(wins.sum()) if len(wins) else 0.0
        sum_losses = float(np.abs(losses.sum())) if len(losses) else 0.0
        profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else 0.0
        expectancy = float(pnls.mean()) if len(pnls) else 0.0

        rets_pct = np.array([t["return_pct"] for t in trades_records]) if trades_records else np.array([])
        best_trade = float(rets_pct.max()) if len(rets_pct) else 0.0
        worst_trade = float(rets_pct.min()) if len(rets_pct) else 0.0

        bar_returns = np.diff(eq_arr) / np.where(eq_arr[:-1] != 0, eq_arr[:-1], 1.0)
        std = float(np.std(bar_returns)) if len(bar_returns) > 1 else 0.0
        mean_r = float(np.mean(bar_returns)) if len(bar_returns) > 0 else 0.0
        ann_factor = np.sqrt(252 * 390)
        sharpe = (mean_r / std * ann_factor) if std > 0 else 0.0
        down_returns = bar_returns[bar_returns < 0]
        down_std = float(np.std(down_returns)) if len(down_returns) > 1 else 0.0
        sortino = (mean_r / down_std * ann_factor) if down_std > 0 else 0.0
    except Exception:
        return empty

    return {
        "ticker": ticker,
        "date": date,
        "total_return_pct": _safe_float(total_ret),
        "max_drawdown_pct": _safe_float(max_dd),
        "win_rate_pct": _safe_float(win_rate),
        "total_trades": n_trades,
        "profit_factor": _safe_float(profit_factor),
        "sharpe_ratio": _safe_float(sharpe),
        "sortino_ratio": _safe_float(sortino),
        "expectancy": _safe_float(expectancy),
        "best_trade_pct": _safe_float(best_trade),
        "worst_trade_pct": _safe_float(worst_trade),
        "init_value": _safe_float(start_val),
        "end_value": _safe_float(end_val),
        "gap_pct": float(gap_pct) if gap_pct is not None else None,
    }


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

def _aggregate_metrics(
    day_results: list[dict],
    trades: list[dict],
    global_eq: list[dict],
    global_dd: list[dict],
    init_cash: float,
    risk_r: float = 100,
    monthly_expenses: float = 0.0
) -> dict:
    empty = {
        "total_days": 0, "total_trades": 0, "win_rate_pct": 0,
        "avg_return_per_day_pct": 0, "total_return_pct": 0, "avg_sharpe": 0,
        "max_drawdown_pct": 0, "avg_profit_factor": 0, "avg_pnl": 0, "total_pnl": 0,
        "sortino_ratio": 0, "calmar_ratio": 0, "dd_return_ratio": 0,
        "r_squared": 0, "avg_mae": 0, "max_profit_pct": 0,
        "avg_win": 0, "avg_loss": 0, "max_consecutive_wins": 0,
        "max_consecutive_losses": 0, "expectancy": 0, "payoff_ratio": 0,
        "avg_r_per_day": 0,
    }
    if not day_results and not trades:
        return empty

    if not day_results and trades:
        unique_dates = {t.get("date", "")[:10] for t in trades if t.get("date")}
        total_days = len(unique_dates)
        total_trades = len(trades)
    else:
        total_days = len(day_results)
        total_trades = sum(d.get("total_trades", 0) for d in day_results)

    # Re-calculate total expenses for the net profit metric
    # (Since total_expenses was previously removed from loop)
    # We find number of unique months in trades
    all_months = sorted(list(set(t.get("date", "")[:7] for t in trades if t.get("date"))))
    total_expenses = len(all_months) * monthly_expenses
    
    pnls = np.array([t.get("pnl", 0) for t in trades]) if trades else np.array([])
    total_pnl_trades = float(pnls.sum()) if len(pnls) else 0.0
    total_pnl_net = total_pnl_trades - total_expenses
    winning_trades = int((pnls > 0).sum()) if len(pnls) else 0
    total_closed = len(pnls)
    win_rate = (winning_trades / total_closed * 100) if total_closed > 0 else 0

    # Calculate Total Return against Initial Cash
    # PnL / Init Cash gives the actual Return % for the period on the account size
    # PnL / Init Cash gives the actual Return % for the period on the account size
    total_pnl = float(pnls.sum()) if len(pnls) else 0.0
    total_return = (total_pnl / init_cash) * 100.0 if init_cash > 0 else 0.0

    # Build a continuous daily equity curve for accurate annualized volatility
    avg_sharpe = 0.0
    sortino_ratio = 0.0
    avg_return_per_day_pct = 0.0

    if total_days > 0 and trades:
        try:
            # Reconstruct daily PnL timeline
            daily_pnls: dict[str, float] = {}
            for t in trades:
                d = t.get("date", "")
                if d:
                    daily_pnls[d] = daily_pnls.get(d, 0.0) + t.get("pnl", 0.0)
            
            sorted_dates = sorted(daily_pnls.keys())
            first_date = pd.to_datetime(sorted_dates[0])
            last_date = pd.to_datetime(sorted_dates[-1])
            
            # Create a dense date range spanning from first trade day to last trade day
            all_dates = pd.date_range(start=first_date, end=last_date, freq='D')
            
            dense_eq = [init_cash]
            current_eq = init_cash
            
            for d in all_dates:
                d_str = d.strftime("%Y-%m-%d")
                current_eq += daily_pnls.get(d_str, 0.0)
                dense_eq.append(current_eq)
                
            eq_arr = np.array(dense_eq, dtype=np.float64)
            daily_rets = np.diff(eq_arr) / np.where(eq_arr[:-1] != 0, eq_arr[:-1], 1.0)
            
            std = float(np.std(daily_rets))
            mean_r = float(np.mean(daily_rets))
            avg_return_per_day_pct = mean_r * 100.0
            
            # Annualize (approx 365 calendar days or 252 trading days. Using 365 since frequency is 'D')
            avg_sharpe = (mean_r / std * np.sqrt(365)) if std > 0 else 0.0
            
            down_rets = daily_rets[daily_rets < 0]
            down_std = float(np.std(down_rets)) if len(down_rets) > 0 else 0.0
            sortino_ratio = (mean_r / down_std * np.sqrt(365)) if down_std > 0 else 0.0

        except Exception as e:
            logger.warning(f"Error computing dense metrics: {e}")

    # --- Drawdown Logic ---
    # Global Max Drawdown (overall lowest point in portfolio equity curve)
    # The global_dd array contains negative percentages representing the drawdown amount
    global_drawdowns = np.array([d["value"] for d in global_dd]) if global_dd else np.array([0])
    global_max_dd = float(global_drawdowns.min()) if len(global_drawdowns) else 0.0

    # Also consider the worst-case intraday point from any single day
    day_max_dds = np.array([d.get("max_drawdown_pct", 0) or 0 for d in day_results])
    worst_day_dd = float(day_max_dds.min()) if len(day_max_dds) else 0.0
    
    # The absolute Max DD is the worst between global closed-equity DD and any intraday DD
    final_max_dd = min(global_max_dd, worst_day_dd)

    # True Global Profit Factor
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    avg_pf = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

    avg_pnl = float(pnls.mean()) if len(pnls) else 0

    # --- New metrics ---
    wins = pnls[pnls > 0] if len(pnls) else np.array([])
    losses = pnls[pnls < 0] if len(pnls) else np.array([])
    avg_win = float(wins.mean()) if len(wins) else 0
    avg_loss = float(losses.mean()) if len(losses) else 0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # Expectancy
    expectancy = avg_pnl

    # Calmar = total return / abs(max dd) -> Using annualized return makes more sense, but simple total is standard here
    calmar_ratio = (total_return / abs(final_max_dd)) if final_max_dd != 0 else 0.0

    # DD/Return ratio -> How much max DD to achieve Total Return
    dd_return_ratio = (abs(final_max_dd) / total_return) if total_return != 0 else 0.0

    # R-Squared (how linear the equity curve is)
    # Use global equity values to compute R²
    if global_eq and len(global_eq) > 2:
        eq_vals = np.array([d["value"] for d in global_eq])
        x = np.arange(len(eq_vals))
        correlation = np.corrcoef(x, eq_vals)[0, 1]
        r_squared = float(correlation ** 2) if not np.isnan(correlation) else 0.0
    else:
        r_squared = 0.0

    # MAE (Maximum Adverse Excursion) — worst case across all trades. Note that MAE is a positive %
    maes = np.array([t.get("mae", 0) for t in trades]) if trades else np.array([])
    max_mae = float(maes.max()) if len(maes) else 0

    # Max profit run per day
    returns = np.array([d.get("total_return_pct", 0) or 0 for d in day_results])
    max_profit_pct = float(returns.max()) if len(returns) else 0

    # Consecutive wins/losses
    max_cons_wins = 0
    max_cons_losses = 0
    curr_wins = 0
    curr_losses = 0
    for p in pnls:
        if p > 0:
            curr_wins += 1
            curr_losses = 0
            max_cons_wins = max(max_cons_wins, curr_wins)
        else:
            curr_losses += 1
            curr_wins = 0
            max_cons_losses = max(max_cons_losses, curr_losses)

    return {
        "total_days": total_days,
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_return_per_day_pct": round(avg_return_per_day_pct, 4),
        "total_return_pct": round(total_return, 4),
        "avg_sharpe": round(avg_sharpe, 4),
        "max_drawdown_pct": round(final_max_dd, 4),
        "avg_profit_factor": round(avg_pf, 4),
        "avg_pnl": round(avg_pnl, 2),
        "total_pnl": round(float(pnls.sum()), 2) if len(pnls) else 0,
        "sortino_ratio": round(sortino_ratio, 4),
        "calmar_ratio": round(calmar_ratio, 4),
        "dd_return_ratio": round(dd_return_ratio, 4),
        "r_squared": round(r_squared, 4),
        "max_mae": round(max_mae, 2),
        "max_profit_pct": round(max_profit_pct, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_consecutive_wins": max_cons_wins,
        "max_consecutive_losses": max_cons_losses,
        "expectancy": round(expectancy, 2),
        "payoff_ratio": round(payoff_ratio, 4),
        "total_expenses": round(total_expenses, 2),
        "total_pnl_net": round(total_pnl_net, 2),
        "avg_r_per_day": round(total_pnl_trades / total_days / risk_r, 4) if total_days > 0 and risk_r > 0 else 0,
    }



def _get_market_sessions_mask(
    timestamps: pd.Series,
    sessions: list[str],
    custom_start: str | None = None,
    custom_end: str | None = None
) -> np.ndarray:
    if not sessions or "all" in sessions:
        return np.ones(len(timestamps), dtype=bool)

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(timestamps):
        timestamps = pd.to_datetime(timestamps)

    total_mins = timestamps.dt.hour * 60 + timestamps.dt.minute
    total_mins_arr = total_mins.values if hasattr(total_mins, "values") else np.asarray(total_mins)
    n = len(total_mins_arr)

    # Cache lookup: mask depends only on (sessions config, exact minute-of-day
    # sequence). Bytes-hash the minute array — O(n) memcpy is faster than
    # recomputing the mask, and always correct (handles holidays / gaps).
    if n > 0:
        mins_int16 = total_mins_arr.astype(np.int16, copy=False)
        cache_key = (
            tuple(sorted(sessions)),
            custom_start,
            custom_end,
            mins_int16.tobytes(),
        )
        cached = _sessions_mask_cache.get(cache_key)
        if cached is not None:
            return cached
    else:
        cache_key = None

    mask = np.zeros(n, dtype=bool)

    import datetime

    for s in sessions:
        s = s.lower().strip()
        if s in ("regular", "market"):
            s = "rth"
        if s == "pre":
            # 04:00 - 09:30 (240 - 570)
            mask |= (total_mins_arr >= 240) & (total_mins_arr < 570)
        elif s == "rth":
            # 09:30 - 16:00 (570 - 960)
            mask |= (total_mins_arr >= 570) & (total_mins_arr < 960)
        elif s == "post":
            # 16:00 - 20:00 (960 - 1200)
            mask |= (total_mins_arr >= 960) & (total_mins_arr < 1200)
        elif s == "custom" and custom_start and custom_end:
            try:
                c_start = datetime.datetime.strptime(custom_start, "%H:%M")
                c_end = datetime.datetime.strptime(custom_end, "%H:%M")
                s_mins = c_start.hour * 60 + c_start.minute
                e_mins = c_end.hour * 60 + c_end.minute
                mask |= (total_mins_arr >= s_mins) & (total_mins_arr < e_mins)
            except Exception:
                pass

    if cache_key is not None:
        _sessions_mask_cache[cache_key] = mask
    return mask

def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return v if not np.isnan(v) and not np.isinf(v) else None
    except (TypeError, ValueError):
        return None
