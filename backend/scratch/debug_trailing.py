import numpy as np

def debug_simulate(
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
    fees: float = 0.0,
    fee_type: str = "PERCENT",
    slippage: float = 0.0,
    sl_stop: float | None = None,
    sl_trail: bool = False,
    tp_stop: float | None = None,
    accumulate: bool = False,
    trail_pct: float | None = None,
    locates_cost: float = 0.0,
    look_ahead_prevention: bool = True,
    patch_mask: np.ndarray | None = None,
):
    n = len(close)
    is_long = direction == "longonly"

    equity = np.empty(n, dtype=np.float64)
    trades = []

    realized_pnl = 0.0
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    size = 0.0
    trail_extreme = 0.0
    mae = 0.0
    mfe = 0.0
    trail_activated = False
    original_size = 0.0
    partial_take_profits = None
    partial_tp_hits = []

    total_trades = 0
    prev_signal = False

    for i in range(n):
        is_restricted = patch_mask[i] if patch_mask is not None else False
        skip_exits = is_restricted and i != n - 1

        print(f"\n--- Bar {i} ---")
        print(f"  in_position: {in_position}")
        print(f"  Open: {open_[i]}, High: {high[i]}, Low: {low[i]}, Close: {close[i]}")

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

            if not skip_exits:
                # 1. Hard Stop
                if sl_stop is not None:
                    if is_long:
                        hard_sl_price = entry_price * (1 - sl_stop)
                        print(f"  Hard SL Long check: low={price_for_sl}, hard_sl_price={hard_sl_price}")
                        if price_for_sl <= hard_sl_price:
                            exit_triggered = True
                            exit_price = max(hard_sl_price, low[i])
                            exit_reason = "SL"
                    else:
                        hard_sl_price = entry_price * (1 + sl_stop)
                        print(f"  Hard SL Short check: high={price_for_sl}, hard_sl_price={hard_sl_price}")
                        if price_for_sl >= hard_sl_price:
                            exit_triggered = True
                            exit_price = min(hard_sl_price, high[i])
                            exit_reason = "SL"

                # 2. Trailing Stop
                if sl_trail and trail_pct is not None:
                    if is_long:
                        print(f"  Trailing Long check: trail_activated={trail_activated}")
                        if not trail_activated:
                            print(f"    Checking activation: high={high[i]} >= entry_price * (1 + trail_pct) - 1e-9={entry_price * (1 + trail_pct) - 1e-9}")
                            if high[i] >= entry_price * (1 + trail_pct) - 1e-9:
                                trail_activated = True
                                trail_extreme = max(entry_price, high[i])
                                print(f"    Trailing activated! trail_extreme={trail_extreme}")

                        if trail_activated:
                            trail_extreme = max(trail_extreme, high[i])
                            trail_sl_price = trail_extreme - (entry_price * trail_pct)
                            print(f"    Evaluating exit: low={price_for_sl} <= trail_sl_price={trail_sl_price}")
                            if price_for_sl <= trail_sl_price:
                                hard_sl_price = entry_price * (1 - sl_stop) if sl_stop is not None else -1e18
                                print(f"      Checking if trail_sl_price > hard_sl_price: {trail_sl_price} > {hard_sl_price}")
                                if trail_sl_price > hard_sl_price:
                                    exit_triggered = True
                                    exit_price = max(trail_sl_price, low[i])
                                    exit_reason = "Trailing"
                                    print(f"      Trailing stop hit! exit_price={exit_price}")
                    else:
                        print(f"  Trailing Short check: trail_activated={trail_activated}")
                        if not trail_activated:
                            print(f"    Checking activation: low={low[i]} <= entry_price * (1 - trail_pct) + 1e-9={entry_price * (1 - trail_pct) + 1e-9}")
                            if low[i] <= entry_price * (1 - trail_pct) + 1e-9:
                                trail_activated = True
                                trail_extreme = min(entry_price, low[i])
                                print(f"    Trailing activated! trail_extreme={trail_extreme}")

                        if trail_activated:
                            trail_extreme = min(trail_extreme, low[i])
                            trail_sl_price = trail_extreme + (entry_price * trail_pct)
                            print(f"    Evaluating exit: high={price_for_sl} >= trail_sl_price={trail_sl_price}")
                            if price_for_sl >= trail_sl_price:
                                hard_sl_price = entry_price * (1 + sl_stop) if sl_stop is not None else 1e18
                                print(f"      Checking if trail_sl_price < hard_sl_price: {trail_sl_price} < {hard_sl_price}")
                                if trail_sl_price < hard_sl_price:
                                    exit_triggered = True
                                    exit_price = min(trail_sl_price, high[i])
                                    exit_reason = "Trailing"
                                    print(f"      Trailing stop hit! exit_price={exit_price}")

            # EOD
            if not exit_triggered and i == n - 1:
                exit_triggered = True
                exit_price = close[i]
                exit_reason = "EOD"
                print(f"  EOD hit: exit_price={exit_price}")

            if exit_triggered:
                print(f"  Exit triggered! Reason={exit_reason}, Price={exit_price}")
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": eff_exit_idx,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                })
                in_position = False

        # check entries
        current_signal = bool(entries[i])
        is_signal_trigger = current_signal and not prev_signal
        print(f"  current_signal={current_signal}, prev_signal={prev_signal}, is_signal_trigger={is_signal_trigger}")

        if not in_position and is_signal_trigger and i < n - 1 and not is_restricted:
            can_enter = True
            if can_enter:
                available_cash = init_cash + realized_pnl
                if look_ahead_prevention:
                    ep = open_[i + 1]
                    eff_entry_idx = i + 1
                else:
                    ep = close[i]
                    eff_entry_idx = i

                entry_price = ep
                in_position = True
                entry_idx = eff_entry_idx
                trail_extreme = entry_price
                trail_activated = False
                size = available_cash / entry_price
                print(f"  Entered position! entry_price={entry_price}, entry_idx={entry_idx}, size={size}")

        prev_signal = current_signal

debug_simulate(
    close=np.array([100.0, 110.0, 100.0, 100.0]),
    open_=np.array([100.0, 100.0, 110.0, 100.0]),
    high=np.array([100.0, 110.0, 110.0, 100.0]),
    low=np.array([100.0, 100.0, 100.0, 100.0]),
    entries=np.array([True, False, False, False]),
    exits=np.array([False, False, False, False]),
    direction="longonly",
    init_cash=10000.0,
    risk_r=100.0,
    risk_type="FIXED",
    sl_trail=True,
    trail_pct=0.10,
    sl_stop=0.20
)
