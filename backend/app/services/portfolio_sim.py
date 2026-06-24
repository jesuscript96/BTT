"""
Lightweight numpy portfolio simulator.
Replaces vbt.Portfolio.from_signals() with ~0 memory overhead per day.

Supports: long/short, stop-loss (fixed & trailing), take-profit, fees, slippage.
Equity model: init_cash + sum(realized_pnl) + unrealized_pnl
"""

import numpy as np
from datetime import datetime, timezone



def simulate(
    close: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    direction: str = "longonly",
    init_cash: float = 10000.0,
    risk_r: float = 100.0,
    risk_type: str = "FIXED",
    fixed_ratio_delta: float = 500.0,
    size_by_sl: bool = False,
    fees: float = 0.0,
    fee_type: str = "PERCENT",  # "PERCENT" or "FLAT"
    slippage: float = 0.0,
    sl_stop: float | None = None,
    sl_trail: bool = False,
    tp_stop: float | None = None,
    tp_time_limit: float | str | None = None,
    accumulate: bool = False,
    max_reentries: int = -1,
    trail_pct: float | None = None,
    locates_cost: float = 0.0,
    locate_type: str = "FLAT",
    look_ahead_prevention: bool = True,
    patch_mask: np.ndarray | None = None,
    partial_take_profits: list | None = None,
    hs_type: str | None = None,
    hs_value: str | float | None = None,
    hs_operator: str | None = ">=",
    hs_offset_pct: float | None = 0.0,
    hods: np.ndarray | None = None,
    lods: np.ndarray | None = None,
    pm_highs: np.ndarray | None = None,
    pm_lows: np.ndarray | None = None,
    prev_highs: np.ndarray | None = None,
    prev_lows: np.ndarray | None = None,
    timestamps: np.ndarray | None = None,
    elapsed_limit: float = -1.0,
    elapsed_operator: str = "GREATER_THAN_OR_EQUAL",
) -> dict:
    n = len(close)
    is_long = direction == "longonly"

    equity = np.empty(n, dtype=np.float64)
    trades: list[dict] = []

    realized_pnl = 0.0
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    entry_time = 0
    entry_fee_amount = 0.0
    size = 0.0
    trade_sl_price = 0.0
    trail_extreme = 0.0
    mae = 0.0  # Maximum Adverse Excursion
    mfe = 0.0  # Maximum Favorable Excursion
    trail_activated = False
    original_size = 0.0  # Track original position size for partial TPs
    partial_tp_hits: list[bool] = []  # Track which partial TP levels have been hit

    # Risk amount tracking for reporting
    risk_amount = risk_r

    # Locates tracking (daily maximum short size)
    max_short_size_today = 0.0

    total_trades = 0
    prev_signal = False

    for i in range(n):
        # --- TEMPORARY PATCH FOR MISPRINTS ---
        # The user requested to ignore all entry and exit logic between 08:00 and 08:45
        # as a temporary workaround for misprints in the data. This will be removed in the future.
        is_restricted = patch_mask[i] if patch_mask is not None else False
        skip_exits = is_restricted and i != n - 1

        # ... existing logic ...
        # --- check exits before entries ---
        if in_position:
            exit_triggered = False
            exit_price = close[i]
            exit_reason = "Signal"
            eff_exit_idx = i

            if is_long:
                price_for_sl = low[i]
                price_for_tp = high[i]
            else:
                price_for_sl = high[i]
                price_for_tp = low[i]

            # stop-loss / trailing stop
            if not skip_exits:
                # 1. Hard Stop Logic
                if hs_type == "Market Structure (HOD/LOD)":
                    if is_long:
                        if price_for_sl <= trade_sl_price:
                            exit_triggered = True
                            exit_price = max(trade_sl_price, low[i])
                            exit_reason = "SL"
                    else:
                        if price_for_sl >= trade_sl_price:
                            exit_triggered = True
                            exit_price = min(trade_sl_price, high[i])
                            exit_reason = "SL"
                elif sl_stop is not None:
                    if is_long:
                        hard_sl_price = entry_price * (1 - sl_stop)
                        if price_for_sl <= hard_sl_price:
                            exit_triggered = True
                            exit_price = max(hard_sl_price, low[i])
                            exit_reason = "SL"
                    else:
                        hard_sl_price = entry_price * (1 + sl_stop)
                        if price_for_sl >= hard_sl_price:
                            exit_triggered = True
                            exit_price = min(hard_sl_price, high[i])
                            exit_reason = "SL"

                # 2. Trailing Stop Logic (Standard High-Water Mark)
                if sl_trail and trail_pct is not None:
                    if is_long:
                        # Check activation: price must go in favor by at least trail_pct
                        if not trail_activated:
                            if high[i] >= entry_price * (1 + trail_pct) - 1e-9:
                                trail_activated = True
                                trail_extreme = max(entry_price, high[i])

                        # Evaluate trailing stop if active
                        if trail_activated:
                            trail_extreme = max(trail_extreme, high[i])
                            trail_sl_price = trail_extreme - (entry_price * trail_pct)
                            
                            if price_for_sl <= trail_sl_price + 1e-9:
                                # Verify trailing stop doesn't override a better hard stop
                                if hs_type == "Market Structure (HOD/LOD)":
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 - sl_stop) if sl_stop is not None else -1e18
                                if trail_sl_price > hard_sl_price:
                                    exit_triggered = True
                                    exit_price = max(trail_sl_price, low[i])
                                    exit_reason = "Trailing"
                    else:
                        # Short: Check activation: price must go in favor by at least trail_pct (drops)
                        if not trail_activated:
                            if low[i] <= entry_price * (1 - trail_pct) + 1e-9:
                                trail_activated = True
                                trail_extreme = min(entry_price, low[i])

                        # Evaluate trailing stop if active
                        if trail_activated:
                            trail_extreme = min(trail_extreme, low[i])
                            trail_sl_price = trail_extreme + (entry_price * trail_pct)
                            
                            if price_for_sl >= trail_sl_price - 1e-9:
                                # Verify trailing stop doesn't override a better hard stop
                                if hs_type == "Market Structure (HOD/LOD)":
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 + sl_stop) if sl_stop is not None else 1e18
                                if trail_sl_price < hard_sl_price:
                                    exit_triggered = True
                                    exit_price = min(trail_sl_price, high[i])
                                    exit_reason = "Trailing"

            # take-profit (full mode — only if partial TPs are NOT configured)
            if not exit_triggered and not partial_take_profits and not skip_exits:
                if tp_stop is not None:
                    if is_long:
                        tp_level = entry_price * (1 + tp_stop)
                        if price_for_tp >= tp_level:
                            exit_triggered = True
                            exit_price = min(tp_level, high[i])
                            exit_reason = "TP"
                    else:
                        tp_level = entry_price * (1 - tp_stop)
                        if price_for_tp <= tp_level:
                            exit_triggered = True
                            exit_price = max(tp_level, low[i])
                            exit_reason = "TP"

                if not exit_triggered and tp_time_limit is not None and timestamps is not None:
                    if isinstance(tp_time_limit, str) and tp_time_limit.startswith("HOUR:"):
                        try:
                            parts = tp_time_limit.split(":")
                            tp_hour = int(parts[1])
                            tp_min = int(parts[2])
                        except:
                            tp_hour, tp_min = 0, 0
                        dt = datetime.fromtimestamp(timestamps[i] / 1e9, tz=timezone.utc)
                        if dt.hour > tp_hour or (dt.hour == tp_hour and dt.minute >= tp_min):
                            exit_triggered = True
                            exit_price = close[i]
                            exit_reason = "TP"
                    else:
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10
                        if elapsed_mins >= tp_time_limit:
                            exit_triggered = True
                            exit_price = close[i]
                            exit_reason = "TP"

            # --- Partial Take-Profits ---
            if not exit_triggered and partial_take_profits and not skip_exits:
                for pt_idx, pt in enumerate(partial_take_profits):
                    if partial_tp_hits[pt_idx]:
                        continue  # Already hit
                    dist_frac = pt["distance_pct"]
                    cap_frac = pt["capital_pct"]
                    
                    if dist_frac == "EOD":
                        if i == n - 1:
                            # It is the end of the day, trigger this EOD partial TP!
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = close[i]
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                if is_long:
                                    gross_pnl = (net_pt_exit - entry_price) * pt_size
                                else:
                                    gross_pnl = (entry_price - net_pt_exit) * pt_size
                                
                                if fee_type == "FLAT":
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP (EOD)",
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            # Not EOD yet, skip
                            continue
                    
                    elif isinstance(dist_frac, str) and dist_frac.startswith("TIME:"):
                        try:
                            tp_mins = float(dist_frac.split(":")[1])
                        except:
                            tp_mins = 0.0
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10 if timestamps is not None else 0.0
                        if elapsed_mins >= tp_mins:
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = close[i]
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                if is_long:
                                    gross_pnl = (net_pt_exit - entry_price) * pt_size
                                else:
                                    gross_pnl = (entry_price - net_pt_exit) * pt_size
                                
                                if fee_type == "FLAT":
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP (Time)",
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            continue
                    
                    elif isinstance(dist_frac, str) and dist_frac.startswith("HOUR:"):
                        try:
                            parts = dist_frac.split(":")
                            tp_hour = int(parts[1])
                            tp_min = int(parts[2])
                        except Exception:
                            tp_hour, tp_min = 0, 0
                        
                        if timestamps is not None:
                            dt = datetime.fromtimestamp(timestamps[i] / 1e9, tz=timezone.utc)
                            if dt.hour > tp_hour or (dt.hour == tp_hour and dt.minute >= tp_min):
                                partial_tp_hits[pt_idx] = True
                                pt_exit_price = close[i]
                                
                                slip = pt_exit_price * slippage
                                net_pt_exit = (pt_exit_price - slip) if is_long else (pt_exit_price + slip)
                                pt_size = original_size * cap_frac
                                pt_size = min(pt_size, size)
                                if pt_size > 0:
                                    if is_long:
                                        gross_pnl = (net_pt_exit - entry_price) * pt_size
                                    else:
                                        gross_pnl = (entry_price - net_pt_exit) * pt_size
                                    
                                    if fee_type == "FLAT":
                                        fee_amount = fees * 2
                                    else:
                                        fee_amount = abs(gross_pnl) * fees
                                    pnl = gross_pnl - fee_amount
                                    realized_pnl += pnl
                                    capital_at_risk = entry_price * pt_size
                                    ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                    trades.append({
                                        "entry_idx": entry_idx,
                                        "exit_idx": i,
                                        "entry_price": round(entry_price, 6),
                                        "exit_price": round(net_pt_exit, 6),
                                        "pnl": round(pnl, 4),
                                        "return_pct": round(ret_pct, 4),
                                        "direction": "Long" if is_long else "Short",
                                        "status": "Closed",
                                        "size": round(pt_size, 6),
                                        "exit_reason": "Partial TP (Hour)",
                                        "mae": round(mae, 4),
                                        "mfe": round(mfe, 4),
                                        "stop_loss": round(trade_sl_price, 6),
                                    })
                                    size -= pt_size
                                    if size <= 0.0001:
                                        in_position = False
                                        size = 0.0
                                        break
                        else:
                            continue
                    
                    elif is_long:
                        pt_level = entry_price * (1 + dist_frac)
                        if price_for_tp >= pt_level:
                            # Partial exit
                            partial_tp_hits[pt_idx] = True
                            # If it gapped above target at open, take the open, else the target
                            pt_exit_price = max(pt_level, open_[i])
                            pt_exit_price = min(pt_exit_price, high[i]) # Bound by high
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price - slip
                            # Close cap_frac of original position
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)  # Can't close more than remaining
                            if pt_size > 0:
                                gross_pnl = (net_pt_exit - entry_price) * pt_size
                                if fee_type == "FLAT":
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP",
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    # All position closed via partial TPs
                                    in_position = False
                                    size = 0.0
                                    break
                    else:
                        pt_level = entry_price * (1 - dist_frac)
                        if price_for_tp <= pt_level:
                            partial_tp_hits[pt_idx] = True
                            # If it gapped below target at open, take the open, else the target
                            pt_exit_price = min(pt_level, open_[i])
                            pt_exit_price = max(pt_exit_price, low[i]) # Bound by low
                            
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price + slip
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                gross_pnl = (entry_price - net_pt_exit) * pt_size
                                if fee_type == "FLAT":
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                trades.append({
                                    "entry_idx": entry_idx,
                                    "exit_idx": i,
                                    "entry_price": round(entry_price, 6),
                                    "exit_price": round(net_pt_exit, 6),
                                    "pnl": round(pnl, 4),
                                    "return_pct": round(ret_pct, 4),
                                    "direction": "Long" if is_long else "Short",
                                    "status": "Closed",
                                    "size": round(pt_size, 6),
                                    "exit_reason": "Partial TP",
                                    "mae": round(mae, 4),
                                    "mfe": round(mfe, 4),
                                    "stop_loss": round(trade_sl_price, 6),
                                })
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                # If all position was closed via partials, skip the rest of exit logic
                if not in_position:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = bool(entries[i])
                    continue

            # Track MAE and MFE as positive percentages based on absolute price excursions
            # We calculate this *before* forcing 'EOD' exits so we don't accidentally ignore wicks.
            # But we calculate it *after* setting exit_price for intrabar STOPS so we can bound the excursions.
            if not is_restricted:
                bound_low = low[i]
                bound_high = high[i]
                
                if exit_triggered and exit_reason in ["SL", "Trailing", "TP"]:
                    # Do not let the recorded excursion go further than the executed stop/TP price
                    if exit_reason in ["SL", "Trailing"]:
                        if is_long:
                            bound_low = max(low[i], exit_price)
                        else:
                            bound_high = min(high[i], exit_price)
                    elif exit_reason == "TP":
                        if is_long:
                            bound_high = min(high[i], exit_price)
                        else:
                            bound_low = max(low[i], exit_price)

                if is_long:
                    mae_pct = ((entry_price - bound_low) / entry_price) * 100
                    mfe_pct = ((bound_high - entry_price) / entry_price) * 100
                else:
                    mae_pct = ((bound_high - entry_price) / entry_price) * 100
                    mfe_pct = ((entry_price - bound_low) / entry_price) * 100
                    
                if mae_pct > mae:
                    mae = mae_pct
                if mfe_pct > mfe:
                    mfe = mfe_pct

            # elapsed time exit
            if not exit_triggered and elapsed_limit > 0 and timestamps is not None:
                elapsed_mins = (timestamps[i] - entry_time) / 6e10
                trigger = False
                if elapsed_operator in ("GREATER_THAN_OR_EQUAL", "GTE"):
                    trigger = (elapsed_mins >= elapsed_limit)
                elif elapsed_operator in ("GREATER_THAN", "GT"):
                    trigger = (elapsed_mins > elapsed_limit)
                elif elapsed_operator in ("LESS_THAN", "LT"):
                    trigger = (elapsed_mins < elapsed_limit)
                elif elapsed_operator in ("LESS_THAN_OR_EQUAL", "LTE"):
                    trigger = (elapsed_mins <= elapsed_limit)
                elif elapsed_operator in ("EQUAL", "EQ"):
                    trigger = (elapsed_mins == elapsed_limit)
                else:
                    trigger = (elapsed_mins >= elapsed_limit)

                if trigger:
                    exit_triggered = True
                    exit_price = close[i]
                    exit_reason = "Time Limit"

            # signal exit
            if not exit_triggered and exits[i] and not skip_exits:
                exit_triggered = True
                if look_ahead_prevention and i < n - 1:
                    exit_price = open_[i + 1]
                    eff_exit_idx = i + 1
                else:
                    exit_price = close[i]
                exit_reason = "Signal"

            # end-of-day forced close
            if not exit_triggered and i == n - 1:
                exit_triggered = True
                exit_price = close[i]
                exit_reason = "EOD"

            if exit_triggered:
                slip = exit_price * slippage
                net_exit = (exit_price - slip) if is_long else (exit_price + slip)
                
                # Gross PnL
                if is_long:
                    gross_pnl = (net_exit - entry_price) * size
                else:
                    gross_pnl = (entry_price - net_exit) * size

                # Fee calculation depends on fee_type
                if fee_type == "FLAT":
                    # Flat $ fee: charged once for entry + once for exit = 2x
                    fee_amount = fees * 2
                else:
                    # Percentage fee: applied on the gross PnL
                    fee_amount = abs(gross_pnl) * fees
                
                # Net PnL is Gross PnL minus Fees
                pnl = gross_pnl - fee_amount

                realized_pnl += pnl
                # For capital at risk, we just use the entry capital required
                capital_at_risk = entry_price * size
                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0

                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": eff_exit_idx,
                    "entry_price": round(entry_price, 6),
                    "exit_price": round(net_exit, 6),
                    "pnl": round(pnl, 4),
                    "fees": round(fee_amount, 4),
                    "return_pct": round(ret_pct, 4),
                    "direction": "Long" if is_long else "Short",
                    "status": "Closed",
                    "size": round(size, 6),
                    "exit_reason": exit_reason,
                    "mae": round(mae, 4),
                    "mfe": round(mfe, 4),
                    "stop_loss": round(trade_sl_price, 6),
                })
                in_position = False
                size = 0.0

        # --- check entries ---
        # Edge Detection: only enter when signal turns from False to True.
        # This prevents re-entering in the same 'signal block'.
        current_signal = bool(entries[i])
        is_signal_trigger = current_signal and not prev_signal
        
        if not in_position and is_signal_trigger and i < n - 1 and not is_restricted:
            # Re-entry logic:
            can_enter = True
            if max_reentries >= 0:
                if total_trades > max_reentries:
                    can_enter = False
            elif not accumulate and total_trades > 0:
                can_enter = False
            
            if can_enter:
                available_cash = init_cash + realized_pnl
                if available_cash <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal # Update for next loop
                    continue

                if look_ahead_prevention:
                    # Standard: enter on next open after signal
                    ep = open_[i + 1]
                    eff_entry_idx = i + 1
                else:
                    # Aggressive/Look-ahead: enter on current close
                    ep = close[i]
                    eff_entry_idx = i

                slip = ep * slippage
                entry_price = (ep + slip) if is_long else (ep - slip)
                if entry_price <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal # Update for next loop
                    continue

                # Fees are now calculated purely on exit Gross PnL
                
                # Calculate Risk Amount ($)
                if risk_type == "PERCENT":
                    risk_amount = available_cash * (risk_r / 100.0)
                elif risk_type == "FIXED_RATIO":
                    # Ryan Jones Fixed Ratio formula
                    # N = 0.5 + 0.5 * sqrt(1 + (8 * Profit / Delta))
                    if realized_pnl > 0 and fixed_ratio_delta > 0:
                        import math
                        n_units = 0.5 + 0.5 * math.sqrt(1 + (8 * realized_pnl / fixed_ratio_delta))
                    else:
                        n_units = 1.0
                    risk_amount = risk_r * n_units
                else:
                    risk_amount = risk_r

                # Determine Stop Loss Price
                stop_loss_price = 0.0
                if hs_type == "Market Structure (HOD/LOD)":
                    val_struct = entry_price * (0.95 if is_long else 1.05)
                    if hs_value == "HOD" and hods is not None:
                        val_struct = hods[i] if hods[i] > 0 else val_struct
                    elif hs_value == "LOD" and lods is not None:
                        val_struct = lods[i] if lods[i] > 0 else val_struct
                    elif hs_value == "PMH" and pm_highs is not None:
                        val_struct = pm_highs[i] if pm_highs[i] > 0 else val_struct
                    elif hs_value == "PML" and pm_lows is not None:
                        val_struct = pm_lows[i] if pm_lows[i] > 0 else val_struct
                    elif hs_value in ("Previous Max", "PrevMax") and prev_highs is not None:
                        val_struct = prev_highs[i] if prev_highs[i] > 0 else val_struct
                    elif hs_value in ("Previous Min", "PrevMin", "Previous Low", "PrevLow") and prev_lows is not None:
                        val_struct = prev_lows[i] if prev_lows[i] > 0 else val_struct
                    
                    # Calculate sl_offset
                    offset_pct = float(hs_offset_pct) if hs_offset_pct is not None else 0.0
                    offset_op = hs_operator or ">="
                    sign = 1.0 if offset_op in (">", ">=") else -1.0
                    sl_offset = sign * offset_pct / 100.0
                    stop_loss_price = val_struct * (1.0 + sl_offset)
                elif sl_stop is not None and sl_stop > 0:
                    stop_loss_price = entry_price * (1 - sl_stop) if is_long else entry_price * (1 + sl_stop)

                if size_by_sl:
                    dist = abs(entry_price - stop_loss_price) if stop_loss_price > 0.0 else 0.0
                    if dist > 0.0:
                        size = risk_amount / dist
                    else:
                        size = risk_amount / entry_price
                else:
                    # Traditional sizing: deploy risk_amount into the position
                    size = risk_amount / entry_price

                # Cap size by available cash
                max_size = available_cash / entry_price
                size = min(size, max_size)

                if size > 0:
                    # Track Max Short Size for Locates
                    if not is_long:
                        max_short_size_today = max(max_short_size_today, size)

                    in_position = True
                    entry_idx = eff_entry_idx
                    entry_time = timestamps[entry_idx] if timestamps is not None else 0
                    trade_sl_price = stop_loss_price
                    trail_extreme = entry_price
                    trail_activated = False
                    mae = 0.0
                    mfe = 0.0
                    original_size = size
                    partial_tp_hits = [False] * len(partial_take_profits) if partial_take_profits else []
                    total_trades += 1
                else:
                    equity[i] = available_cash
        
        # Always update signal state for next bar's edge detection
        prev_signal = current_signal

        # --- equity ---
        current_equity = init_cash + realized_pnl
        if in_position:
            if is_long:
                unrealized = (close[i] - entry_price) * size
            else:
                unrealized = (entry_price - close[i]) * size
            equity[i] = current_equity + unrealized
        else:
            equity[i] = current_equity

    # Deduct Daily Locates Fee
    import math
    if max_short_size_today > 0 and locates_cost > 0:
        if locate_type == "PERCENT":
            if risk_type == "PERCENT":
                day_risk_unit = init_cash * (risk_r / 100.0)
            else:
                day_risk_unit = risk_r
            cost_per_100 = day_risk_unit * (locates_cost / 100.0)
        else:
            cost_per_100 = locates_cost

        blocks_of_100 = math.ceil(max_short_size_today / 100.0)
        daily_locates_fee = blocks_of_100 * cost_per_100
        
        # We subtract it from the final equity tally
        # To ensure trade sum = equity curve change, we assign the deduction to the first short trade
        for t in trades:
            if t["direction"] == "Short":
                t["pnl"] = round(t["pnl"] - daily_locates_fee, 4)
                t["fees"] = round(t.get("fees", 0.0) + daily_locates_fee, 4)
                break
                
        # Update equity curve retroactively downwards so it reflects the end of day state
        # In a perfect world we would apply it exactly when the short is taken, 
        # but applying at EOF/assigning to trade PnL keeps accounting perfectly aligned
        for i in range(len(equity)):
            equity[i] -= daily_locates_fee

    # Always update signal state for next bar's edge detection
    prev_signal = current_signal

    # Finalize result
    results = {"equity": equity, "trades": trades}
    if risk_type == "PERCENT":
        results["last_risk_amount"] = risk_amount
    else:
        results["last_risk_amount"] = risk_r
        
    return results
