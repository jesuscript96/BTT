"""
Numba JIT core for portfolio_sim.simulate() (F2).

This module holds ONLY the numeric hot loop. It is a faithful, line-for-line
port of the Python loop in ``portfolio_sim.simulate`` with one rule: every
floating-point operation is performed in the SAME order and the SAME way, so
the result is bit-identical (Golden B tolerance 0).

Hard rules for tol-0 equivalence:
  * fastmath is OFF (default) — never enable it (it would reorder FP ops).
  * single-thread — no parallel/prange (determinism + this is one ticker-day).
  * round() is NOT done here — the Python wrapper rounds when it rebuilds the
    trade dicts, exactly as the original code did.
  * strings/None/pandas never cross into here — the wrapper maps everything to
    int enums + flag-guarded zero arrays before calling.

The core returns flat homogeneous arrays (one row per trade); the wrapper in
portfolio_sim.py reassembles the exact trade dicts and applies the daily
locates fee (which runs once, off the hot path).
"""

import math
import numpy as np
from numba import njit

# --- direction ---
# (is_long is passed as a bool; no enum needed)

# --- risk sizing types ---
RISK_PERCENT = 0
RISK_FIXED = 1
RISK_HSQRT = 2   # "FIXED_RATIO" (Ryan Jones)

# --- fee types ---
FEE_PERCENT = 0
FEE_FLAT = 1

# --- hard-stop value source ---
HS_NONE = 0
HS_HOD = 1
HS_LOD = 2
HS_PMH = 3
HS_PML = 4
HS_PREVMAX = 5
HS_PREVMIN = 6

# --- exit reason codes (each maps 1:1 to an exact exit_reason string) ---
REASON_SL = 0            # "SL"
REASON_TP = 1            # "TP"
REASON_TIME = 2          # "Time Limit"
REASON_EOD = 3           # "EOD"
REASON_SIGNAL = 4        # "Signal"
REASON_TRAILING = 5      # "Trailing"
REASON_PARTIAL = 6       # "Partial TP"
REASON_PARTIAL_EOD = 7   # "Partial TP (EOD)"
REASON_PARTIAL_TIME = 8  # "Partial TP (Time)"
REASON_PARTIAL_HOUR = 9  # "Partial TP (Hour)"

# --- elapsed-time comparator codes ---
ELAPSED_GTE = 0
ELAPSED_GT = 1
ELAPSED_LT = 2
ELAPSED_LTE = 3
ELAPSED_EQ = 4

# --- partial TP type codes ---
PT_PCT = 0
PT_EOD = 1
PT_TIME = 2
PT_HOUR = 3


@njit(cache=True)
def _core_simulate_jit(
    close, open_, high, low, entries, exits,
    is_long,
    init_cash, risk_r,
    risk_type_code,
    fixed_ratio_delta,
    size_by_sl,
    fees, fee_type_code,
    slippage,
    has_sl_stop, sl_stop,
    sl_trail,
    has_tp_stop, tp_stop,
    tp_time_mode, tp_time_value, tp_hour, tp_min,
    accumulate,
    max_reentries,
    has_trail_pct, trail_pct,
    look_ahead_prevention,
    hs_type_code, hs_value_code, sl_offset,
    has_hods, hods,
    has_lods, lods,
    has_pm_high, pm_highs,
    has_pm_low, pm_lows,
    has_prev_high, prev_highs,
    has_prev_low, prev_lows,
    has_timestamps, timestamps,
    has_hours, row_hours, row_minutes,
    elapsed_limit, elapsed_op_code,
    n_pt, pt_type, pt_value, pt_cap_frac, pt_hour, pt_min,
):
    n = len(close)

    equity = np.empty(n, dtype=np.float64)

    # Per-trade result arrays (upper bound: each bar can emit up to n_pt partials
    # plus one full exit).
    cap = n * (n_pt + 1) + 4
    r_entry_idx = np.empty(cap, dtype=np.int64)
    r_exit_idx = np.empty(cap, dtype=np.int64)
    r_entry_px = np.empty(cap, dtype=np.float64)
    r_exit_px = np.empty(cap, dtype=np.float64)
    r_pnl = np.empty(cap, dtype=np.float64)
    r_fees = np.empty(cap, dtype=np.float64)
    r_return_pct = np.empty(cap, dtype=np.float64)
    r_size = np.empty(cap, dtype=np.float64)
    r_reason = np.empty(cap, dtype=np.int64)
    r_mae = np.empty(cap, dtype=np.float64)
    r_mfe = np.empty(cap, dtype=np.float64)
    r_stop = np.empty(cap, dtype=np.float64)
    k = 0

    realized_pnl = 0.0
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    entry_time = 0
    size = 0.0
    trade_sl_price = 0.0
    trail_extreme = 0.0
    mae = 0.0
    mfe = 0.0
    trail_activated = False
    original_size = 0.0
    partial_tp_hits = np.zeros(n_pt if n_pt > 0 else 1, dtype=np.bool_)

    risk_amount = risk_r
    max_short_size_today = 0.0
    total_trades = 0
    prev_signal = False

    for i in range(n):
        # Misprint patch removed (data NBBO-clipped at source): no bar restriction.
        # Constants keep the inert restriction branches below (const-folded by numba).
        is_restricted = False
        skip_exits = False

        if in_position:
            exit_triggered = False
            exit_price = close[i]
            exit_reason_code = REASON_SIGNAL
            eff_exit_idx = i

            if is_long:
                price_for_sl = low[i]
                price_for_tp = high[i]
            else:
                price_for_sl = high[i]
                price_for_tp = low[i]

            # stop-loss / trailing stop
            if not skip_exits:
                # 1. Hard Stop
                if hs_type_code == 1:  # Market Structure (HOD/LOD)
                    if is_long:
                        if price_for_sl <= trade_sl_price:
                            exit_triggered = True
                            exit_price = max(trade_sl_price, low[i])
                            exit_reason_code = REASON_SL
                    else:
                        if price_for_sl >= trade_sl_price:
                            exit_triggered = True
                            exit_price = min(trade_sl_price, high[i])
                            exit_reason_code = REASON_SL
                elif has_sl_stop:
                    if is_long:
                        hard_sl_price = entry_price * (1 - sl_stop)
                        if price_for_sl <= hard_sl_price:
                            exit_triggered = True
                            exit_price = max(hard_sl_price, low[i])
                            exit_reason_code = REASON_SL
                    else:
                        hard_sl_price = entry_price * (1 + sl_stop)
                        if price_for_sl >= hard_sl_price:
                            exit_triggered = True
                            exit_price = min(hard_sl_price, high[i])
                            exit_reason_code = REASON_SL

                # 2. Trailing Stop (high-water mark)
                if sl_trail and has_trail_pct:
                    if is_long:
                        if not trail_activated:
                            if high[i] >= entry_price * (1 + trail_pct) - 1e-9:
                                trail_activated = True
                                trail_extreme = max(entry_price, high[i])
                        if trail_activated:
                            trail_extreme = max(trail_extreme, high[i])
                            trail_sl_price = trail_extreme - (entry_price * trail_pct)
                            if price_for_sl <= trail_sl_price + 1e-9:
                                if hs_type_code == 1:
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 - sl_stop) if has_sl_stop else -1e18
                                if trail_sl_price > hard_sl_price:
                                    exit_triggered = True
                                    exit_price = max(trail_sl_price, low[i])
                                    exit_reason_code = REASON_TRAILING
                    else:
                        if not trail_activated:
                            if low[i] <= entry_price * (1 - trail_pct) + 1e-9:
                                trail_activated = True
                                trail_extreme = min(entry_price, low[i])
                        if trail_activated:
                            trail_extreme = min(trail_extreme, low[i])
                            trail_sl_price = trail_extreme + (entry_price * trail_pct)
                            if price_for_sl >= trail_sl_price - 1e-9:
                                if hs_type_code == 1:
                                    hard_sl_price = trade_sl_price
                                else:
                                    hard_sl_price = entry_price * (1 + sl_stop) if has_sl_stop else 1e18
                                if trail_sl_price < hard_sl_price:
                                    exit_triggered = True
                                    exit_price = min(trail_sl_price, high[i])
                                    exit_reason_code = REASON_TRAILING

            # take-profit (full mode — only if partial TPs are NOT configured)
            if (not exit_triggered) and (n_pt == 0) and (not skip_exits):
                if has_tp_stop:
                    if is_long:
                        tp_level = entry_price * (1 + tp_stop)
                        if price_for_tp >= tp_level:
                            exit_triggered = True
                            exit_price = min(tp_level, high[i])
                            exit_reason_code = REASON_TP
                    else:
                        tp_level = entry_price * (1 - tp_stop)
                        if price_for_tp <= tp_level:
                            exit_triggered = True
                            exit_price = max(tp_level, low[i])
                            exit_reason_code = REASON_TP

                if (not exit_triggered) and (tp_time_mode != 0) and has_timestamps:
                    if tp_time_mode == 2:  # HOUR:h:m
                        if has_hours:
                            if row_hours[i] > tp_hour or (row_hours[i] == tp_hour and row_minutes[i] >= tp_min):
                                exit_triggered = True
                                exit_price = close[i]
                                exit_reason_code = REASON_TP
                    else:  # minutes
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10
                        if elapsed_mins >= tp_time_value:
                            exit_triggered = True
                            exit_price = close[i]
                            exit_reason_code = REASON_TP

            # --- Partial Take-Profits ---
            if (not exit_triggered) and (n_pt > 0) and (not skip_exits):
                for pt_idx in range(n_pt):
                    if partial_tp_hits[pt_idx]:
                        continue
                    dist_type = pt_type[pt_idx]
                    cap_frac = pt_cap_frac[pt_idx]

                    if dist_type == PT_EOD:
                        if i == n - 1:
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
                                if fee_type_code == FEE_FLAT:
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                r_entry_idx[k] = entry_idx
                                r_exit_idx[k] = i
                                r_entry_px[k] = entry_price
                                r_exit_px[k] = net_pt_exit
                                r_pnl[k] = pnl
                                r_fees[k] = 0.0
                                r_return_pct[k] = ret_pct
                                r_size[k] = pt_size
                                r_reason[k] = REASON_PARTIAL_EOD
                                r_mae[k] = mae
                                r_mfe[k] = mfe
                                r_stop[k] = trade_sl_price
                                k += 1
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            continue

                    elif dist_type == PT_TIME:
                        tp_mins = pt_value[pt_idx]
                        elapsed_mins = (timestamps[i] - entry_time) / 6e10 if has_timestamps else 0.0
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
                                if fee_type_code == FEE_FLAT:
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                r_entry_idx[k] = entry_idx
                                r_exit_idx[k] = i
                                r_entry_px[k] = entry_price
                                r_exit_px[k] = net_pt_exit
                                r_pnl[k] = pnl
                                r_fees[k] = 0.0
                                r_return_pct[k] = ret_pct
                                r_size[k] = pt_size
                                r_reason[k] = REASON_PARTIAL_TIME
                                r_mae[k] = mae
                                r_mfe[k] = mfe
                                r_stop[k] = trade_sl_price
                                k += 1
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                        else:
                            continue

                    elif dist_type == PT_HOUR:
                        tp_h = pt_hour[pt_idx]
                        tp_m = pt_min[pt_idx]
                        if has_timestamps and has_hours:
                            if row_hours[i] > tp_h or (row_hours[i] == tp_h and row_minutes[i] >= tp_m):
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
                                    if fee_type_code == FEE_FLAT:
                                        fee_amount = fees * 2
                                    else:
                                        fee_amount = abs(gross_pnl) * fees
                                    pnl = gross_pnl - fee_amount
                                    realized_pnl += pnl
                                    capital_at_risk = entry_price * pt_size
                                    ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                    r_entry_idx[k] = entry_idx
                                    r_exit_idx[k] = i
                                    r_entry_px[k] = entry_price
                                    r_exit_px[k] = net_pt_exit
                                    r_pnl[k] = pnl
                                    r_fees[k] = 0.0
                                    r_return_pct[k] = ret_pct
                                    r_size[k] = pt_size
                                    r_reason[k] = REASON_PARTIAL_HOUR
                                    r_mae[k] = mae
                                    r_mfe[k] = mfe
                                    r_stop[k] = trade_sl_price
                                    k += 1
                                    size -= pt_size
                                    if size <= 0.0001:
                                        in_position = False
                                        size = 0.0
                                        break
                        else:
                            continue

                    elif is_long:
                        pt_level = entry_price * (1 + pt_value[pt_idx])
                        if price_for_tp >= pt_level:
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = max(pt_level, open_[i])
                            pt_exit_price = min(pt_exit_price, high[i])
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price - slip
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                gross_pnl = (net_pt_exit - entry_price) * pt_size
                                if fee_type_code == FEE_FLAT:
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                r_entry_idx[k] = entry_idx
                                r_exit_idx[k] = i
                                r_entry_px[k] = entry_price
                                r_exit_px[k] = net_pt_exit
                                r_pnl[k] = pnl
                                r_fees[k] = 0.0
                                r_return_pct[k] = ret_pct
                                r_size[k] = pt_size
                                r_reason[k] = REASON_PARTIAL
                                r_mae[k] = mae
                                r_mfe[k] = mfe
                                r_stop[k] = trade_sl_price
                                k += 1
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                    else:
                        pt_level = entry_price * (1 - pt_value[pt_idx])
                        if price_for_tp <= pt_level:
                            partial_tp_hits[pt_idx] = True
                            pt_exit_price = min(pt_level, open_[i])
                            pt_exit_price = max(pt_exit_price, low[i])
                            slip = pt_exit_price * slippage
                            net_pt_exit = pt_exit_price + slip
                            pt_size = original_size * cap_frac
                            pt_size = min(pt_size, size)
                            if pt_size > 0:
                                gross_pnl = (entry_price - net_pt_exit) * pt_size
                                if fee_type_code == FEE_FLAT:
                                    fee_amount = fees * 2
                                else:
                                    fee_amount = abs(gross_pnl) * fees
                                pnl = gross_pnl - fee_amount
                                realized_pnl += pnl
                                capital_at_risk = entry_price * pt_size
                                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0
                                r_entry_idx[k] = entry_idx
                                r_exit_idx[k] = i
                                r_entry_px[k] = entry_price
                                r_exit_px[k] = net_pt_exit
                                r_pnl[k] = pnl
                                r_fees[k] = 0.0
                                r_return_pct[k] = ret_pct
                                r_size[k] = pt_size
                                r_reason[k] = REASON_PARTIAL
                                r_mae[k] = mae
                                r_mfe[k] = mfe
                                r_stop[k] = trade_sl_price
                                k += 1
                                size -= pt_size
                                if size <= 0.0001:
                                    in_position = False
                                    size = 0.0
                                    break
                if not in_position:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = entries[i]
                    continue

            # Track MAE / MFE
            if not is_restricted:
                bound_low = low[i]
                bound_high = high[i]
                if exit_triggered and (exit_reason_code == REASON_SL or exit_reason_code == REASON_TRAILING or exit_reason_code == REASON_TP):
                    if exit_reason_code == REASON_SL or exit_reason_code == REASON_TRAILING:
                        if is_long:
                            bound_low = max(low[i], exit_price)
                        else:
                            bound_high = min(high[i], exit_price)
                    else:  # TP
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
            if (not exit_triggered) and elapsed_limit > 0 and has_timestamps:
                elapsed_mins = (timestamps[i] - entry_time) / 6e10
                trigger = False
                if elapsed_op_code == ELAPSED_GTE:
                    trigger = (elapsed_mins >= elapsed_limit)
                elif elapsed_op_code == ELAPSED_GT:
                    trigger = (elapsed_mins > elapsed_limit)
                elif elapsed_op_code == ELAPSED_LT:
                    trigger = (elapsed_mins < elapsed_limit)
                elif elapsed_op_code == ELAPSED_LTE:
                    trigger = (elapsed_mins <= elapsed_limit)
                elif elapsed_op_code == ELAPSED_EQ:
                    trigger = (elapsed_mins == elapsed_limit)
                else:
                    trigger = (elapsed_mins >= elapsed_limit)

                if trigger:
                    exit_triggered = True
                    exit_price = close[i]
                    exit_reason_code = REASON_TIME

            # signal exit
            if (not exit_triggered) and exits[i] and (not skip_exits):
                exit_triggered = True
                if look_ahead_prevention and i < n - 1:
                    exit_price = open_[i + 1]
                    eff_exit_idx = i + 1
                else:
                    exit_price = close[i]
                exit_reason_code = REASON_SIGNAL

            # end-of-day forced close
            if (not exit_triggered) and i == n - 1:
                exit_triggered = True
                exit_price = close[i]
                exit_reason_code = REASON_EOD

            if exit_triggered:
                slip = exit_price * slippage
                net_exit = (exit_price - slip) if is_long else (exit_price + slip)
                if is_long:
                    gross_pnl = (net_exit - entry_price) * size
                else:
                    gross_pnl = (entry_price - net_exit) * size
                if fee_type_code == FEE_FLAT:
                    fee_amount = fees * 2
                else:
                    fee_amount = abs(gross_pnl) * fees
                pnl = gross_pnl - fee_amount
                realized_pnl += pnl
                capital_at_risk = entry_price * size
                ret_pct = (pnl / capital_at_risk) * 100 if capital_at_risk > 0 else 0.0

                r_entry_idx[k] = entry_idx
                r_exit_idx[k] = eff_exit_idx
                r_entry_px[k] = entry_price
                r_exit_px[k] = net_exit
                r_pnl[k] = pnl
                r_fees[k] = fee_amount
                r_return_pct[k] = ret_pct
                r_size[k] = size
                r_reason[k] = exit_reason_code
                r_mae[k] = mae
                r_mfe[k] = mfe
                r_stop[k] = trade_sl_price
                k += 1
                in_position = False
                size = 0.0

        # --- check entries ---
        current_signal = entries[i]
        is_signal_trigger = current_signal and not prev_signal

        if (not in_position) and is_signal_trigger and i < n - 1 and (not is_restricted):
            can_enter = True
            if max_reentries >= 0:
                if total_trades > max_reentries:
                    can_enter = False
            elif (not accumulate) and total_trades > 0:
                can_enter = False

            if can_enter:
                available_cash = init_cash + realized_pnl
                if available_cash <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal
                    continue

                if look_ahead_prevention:
                    ep = open_[i + 1]
                    eff_entry_idx = i + 1
                else:
                    ep = close[i]
                    eff_entry_idx = i

                slip = ep * slippage
                entry_price = (ep + slip) if is_long else (ep - slip)
                if entry_price <= 0:
                    equity[i] = init_cash + realized_pnl
                    prev_signal = current_signal
                    continue

                # Risk amount ($)
                if risk_type_code == RISK_PERCENT:
                    risk_amount = available_cash * (risk_r / 100.0)
                elif risk_type_code == RISK_HSQRT:
                    if realized_pnl > 0 and fixed_ratio_delta > 0:
                        n_units = 0.5 + 0.5 * math.sqrt(1 + (8 * realized_pnl / fixed_ratio_delta))
                    else:
                        n_units = 1.0
                    risk_amount = risk_r * n_units
                else:
                    risk_amount = risk_r

                # Stop loss price
                stop_loss_price = 0.0
                if hs_type_code == 1:  # Market Structure (HOD/LOD)
                    val_struct = entry_price * (0.95 if is_long else 1.05)
                    if hs_value_code == HS_HOD and has_hods:
                        val_struct = hods[i] if hods[i] > 0 else val_struct
                    elif hs_value_code == HS_LOD and has_lods:
                        val_struct = lods[i] if lods[i] > 0 else val_struct
                    elif hs_value_code == HS_PMH and has_pm_high:
                        val_struct = pm_highs[i] if pm_highs[i] > 0 else val_struct
                    elif hs_value_code == HS_PML and has_pm_low:
                        val_struct = pm_lows[i] if pm_lows[i] > 0 else val_struct
                    elif hs_value_code == HS_PREVMAX and has_prev_high:
                        val_struct = prev_highs[i] if prev_highs[i] > 0 else val_struct
                    elif hs_value_code == HS_PREVMIN and has_prev_low:
                        val_struct = prev_lows[i] if prev_lows[i] > 0 else val_struct
                    stop_loss_price = val_struct * (1.0 + sl_offset)
                elif has_sl_stop and sl_stop > 0:
                    stop_loss_price = entry_price * (1 - sl_stop) if is_long else entry_price * (1 + sl_stop)

                if size_by_sl:
                    dist = abs(entry_price - stop_loss_price) if stop_loss_price > 0.0 else 0.0
                    if dist > 0.0:
                        size = risk_amount / dist
                    else:
                        size = risk_amount / entry_price
                else:
                    size = risk_amount / entry_price

                max_size = available_cash / entry_price
                size = min(size, max_size)

                if size > 0:
                    if not is_long:
                        max_short_size_today = max(max_short_size_today, size)
                    in_position = True
                    entry_idx = eff_entry_idx
                    entry_time = timestamps[entry_idx] if has_timestamps else 0
                    trade_sl_price = stop_loss_price
                    trail_extreme = entry_price
                    trail_activated = False
                    mae = 0.0
                    mfe = 0.0
                    original_size = size
                    for x in range(n_pt):
                        partial_tp_hits[x] = False
                    total_trades += 1
                else:
                    equity[i] = available_cash

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

    return (
        equity, k,
        r_entry_idx, r_exit_idx, r_entry_px, r_exit_px, r_pnl, r_fees,
        r_return_pct, r_size, r_reason, r_mae, r_mfe, r_stop,
        max_short_size_today, risk_amount,
    )
