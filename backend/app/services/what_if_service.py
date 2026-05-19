import random
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from datetime import datetime

# Import the aggregate metrics helper from backtest_service
# We might need to handle imports carefully based on the project structure
from app.services.backtest_service import (
    _aggregate_metrics,
    _compute_global_equity_and_drawdown
)

def run_what_if(
    trades: List[Dict[str, Any]],
    params: Dict[str, Any],
    init_cash: float = 10000.0,
    risk_r: float = 100.0
) -> Dict[str, Any]:
    """
    Runs a simulation on existing trades based on the 'What-if' parameters.
    """
    if not trades:
        return {
            "trades": [],
            "global_equity": [],
            "global_drawdown": [],
            "aggregate_metrics": {}
        }

    # Sort trades by entry time to ensure chronological processing
    sorted_trades = sorted(trades, key=lambda x: x["entry_time"])
    
    # --- 1) Temporal Filters ---
    exclude_days = params.get("exclude_days", []) # [0, 1, 2, 3, 4] for Mon-Fri
    exclude_months = params.get("exclude_months", []) # ["Enero", ...]
    exclude_hour_start = params.get("exclude_hour_start") # int
    exclude_hour_end = params.get("exclude_hour_end") # int
    random_monthly_days = params.get("random_monthly_days", 0)

    # Prepare Month mapping — accepts both numeric indices (0-based from frontend)
    # and Spanish month name strings (legacy)
    month_map = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
        "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }
    exclude_months_idx = []
    for m in exclude_months:
        if isinstance(m, int):
            # Frontend sends 0-based index (0=Jan, 11=Dec) → convert to 1-based month
            exclude_months_idx.append(m + 1)
        elif isinstance(m, str) and m in month_map:
            exclude_months_idx.append(month_map[m])
        elif isinstance(m, str) and m.isdigit():
            exclude_months_idx.append(int(m) + 1)

    # Handle Random Monthly Days
    # We group trades by YYYY-MM and pick N random days to exclude
    days_to_exclude = set()
    if random_monthly_days > 0:
        trades_by_month = {}
        for t in sorted_trades:
            m_key = t["date"][:7] # YYYY-MM
            if m_key not in trades_by_month:
                trades_by_month[m_key] = set()
            trades_by_month[m_key].add(t["date"])
        
        for m_key, dates in trades_by_month.items():
            dates_list = sorted(list(dates))
            to_drop = random.sample(dates_list, min(len(dates_list), random_monthly_days))
            days_to_exclude.update(to_drop)

    filtered_trades = []
    
    # --- 2) Trade Limits & Simulation ---
    daily_counter = {} # date -> count
    max_trades_per_day = params.get("daily_max_trades", 0)
    max_concurrent = params.get("max_concurrent_trades", 0)
    
    open_trades = [] # List of exit_times for concurrent check

    for t in sorted_trades:
        # Exclusion checks
        if t["entry_weekday"] in exclude_days: continue
        if datetime.strptime(t["date"], "%Y-%m-%d").month in exclude_months_idx: continue
        if t["date"] in days_to_exclude: continue
        
        # Hour check
        if exclude_hour_start is not None and exclude_hour_end is not None:
            h = t["entry_hour"]
            # Interval check [start, end)
            if exclude_hour_start < exclude_hour_end:
                if exclude_hour_start <= h < exclude_hour_end: continue
            else: # Overnight interval e.g. 22:00 to 02:00
                if h >= exclude_hour_start or h < exclude_hour_end: continue

        # Daily limit
        if max_trades_per_day > 0:
            d = t["date"]
            daily_counter[d] = daily_counter.get(d, 0) + 1
            if daily_counter[d] > max_trades_per_day: continue

        # Concurrent limit
        if max_concurrent > 0:
            # Clean up closed trades
            entry_time = pd.to_datetime(t["entry_time"])
            open_trades = [ex for ex in open_trades if ex > entry_time]
            if len(open_trades) >= max_concurrent:
                continue
            open_trades.append(pd.to_datetime(t["exit_time"]))

        filtered_trades.append(t.copy())

    # --- 3) Alternative Size Management (Dynamic Post-hoc) ---
    size_mgmt_type = params.get("size_mgmt_type", "dd")
    dd_threshold = params.get("dd_threshold", 5)
    dd_reduction = params.get("dd_reduction", 50)
    sma_period = params.get("sma_period", 20)
    sma_reduction = params.get("sma_reduction", 50)

    # We need to simulate the equity curve sequentially to calculate DD or SMA 
    # and reduce size accordingly on the fly.
    if dd_threshold > 0 or sma_period > 0:
        current_eq = init_cash
        running_max = init_cash
        eq_history = [init_cash]
        
        for t in filtered_trades:
            # 1. Evaluate current conditions (Before applying trade)
            current_dd_pct = ((running_max - current_eq) / running_max * 100) if running_max > 0 else 0
            
            if len(eq_history) >= sma_period:
                sma_val = sum(eq_history[-sma_period:]) / sma_period
            else:
                sma_val = sum(eq_history) / len(eq_history)

            # 2. Decide size reduction factor
            reduce_factor = 1.0
            if size_mgmt_type == "dd":
                if current_dd_pct > dd_threshold:
                    reduce_factor = max(0.0, 1.0 - (dd_reduction / 100.0))
            elif size_mgmt_type == "sma":
                if current_eq < sma_val:
                    reduce_factor = max(0.0, 1.0 - (sma_reduction / 100.0))
            
            # 3. Apply reduction to the trade PnL and Size
            if reduce_factor < 1.0:
                t["size"] = t["size"] * reduce_factor
                t["pnl"] = t["pnl"] * reduce_factor

            # 4. Advance states
            current_eq += t["pnl"]
            if current_eq > running_max:
                running_max = current_eq
            eq_history.append(current_eq)


    # --- 4) Stress Test ---
    skip_top_pct = params.get("skip_top_pct", 0)
    extra_slippage = params.get("extra_slippage", 0)
    black_swan_count = params.get("black_swan_count", 0)
    black_swan_pct = params.get("black_swan_pct", 0)

    # Skip top %
    if skip_top_pct > 0 and filtered_trades:
        filtered_trades.sort(key=lambda x: x["pnl"], reverse=True)
        count_to_skip = int(len(filtered_trades) * (skip_top_pct / 100.0))
        filtered_trades = filtered_trades[count_to_skip:]
        # Resort chronologically after filtering top
        filtered_trades.sort(key=lambda x: x["entry_time"])

    # Extra Slippage & Recalculate PnL
    if extra_slippage > 0:
        for t in filtered_trades:
            # S = S_original - extra_slippage
            # PnL roughly follows the return change
            old_ret = t["return_pct"]
            new_ret = old_ret - extra_slippage
            # Proportional adjustment to PnL
            if old_ret != 0:
                t["pnl"] = (t["pnl"] * new_ret) / old_ret
            else:
                # If old_ret was 0, we estimate PnL from size * price * extra_slippage
                t["pnl"] -= (t["size"] * t["entry_price"] * (extra_slippage / 100.0))
            t["return_pct"] = new_ret

    # Black Swan (Random losses)
    if black_swan_count > 0 and filtered_trades:
        swan_indices = random.sample(range(len(filtered_trades)), min(len(filtered_trades), black_swan_count))
        for idx in swan_indices:
            t = filtered_trades[idx]
            # Replace trade with a significant loss
            t["return_pct"] = -abs(black_swan_pct) if black_swan_pct != 0 else -5.0
            t["pnl"] = -abs(t["size"] * t["entry_price"] * (abs(t["return_pct"]) / 100.0))
            t["exit_reason"] = "BLACK SWAN"

    # --- 5) Rebuild Equity & Finalize ---
    # We use the helpers from backtest_service to ensure consistency
    # Note: we pass monthly_expenses=0 for what-if often, unless requested
    monthly_expenses = params.get("monthly_expenses", 0.0)
    
    global_eq, global_dd, global_eq_exp = _compute_global_equity_and_drawdown(
        filtered_trades, init_cash, monthly_expenses
    )
    
    # For aggregate metrics, we need "day_results" but since it's a trade-level sim,
    # we can pass an empty list or construct simplified ones.
    # Actually, _aggregate_metrics handles empty day_results if it has global_eq
    # Let's check _aggregate_metrics in backtest_service.py to see if it can handle minimal day_results
    
    aggregate = _aggregate_metrics(
        day_results=[], 
        trades=filtered_trades, 
        global_eq=global_eq, 
        global_dd=global_dd, 
        init_cash=init_cash, 
        risk_r=risk_r,
        monthly_expenses=monthly_expenses
    )

    return {
        "trades": filtered_trades,
        "global_equity": global_eq,
        "global_drawdown": global_dd,
        "aggregate_metrics": aggregate
    }
