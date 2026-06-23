import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from app.services.portfolio_sim import simulate

def test_partial_tp_hour():
    # 10 bars, 1m timeframe starting at 11:25
    n = 10
    close = np.array([100.0] * n)
    open_ = np.array([100.0] * n)
    high = np.array([101.0] * n)
    low = np.array([99.0] * n)
    
    # Entry signal at bar 0 (11:25)
    entries = np.array([True] + [False] * (n - 1))
    exits = np.array([False] * n)
    
    # Timestamps in nanoseconds (using UTC timezone to match python datetime conversion)
    start_dt = datetime(2026, 6, 15, 11, 25, tzinfo=timezone.utc)
    ts_list = [int((start_dt + timedelta(minutes=i)).timestamp() * 1e9) for i in range(n)]
    timestamps = np.array(ts_list, dtype=np.int64)
    
    # Partial TP configuration: 50% at 11:28, 50% at 11:32
    partial_take_profits = [
        {"distance_pct": "HOUR:11:28", "capital_pct": 0.5},
        {"distance_pct": "HOUR:11:32", "capital_pct": 0.5}
    ]
    
    res = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        timestamps=timestamps,
        partial_take_profits=partial_take_profits,
    )
    
    trades = res["trades"]
    
    # We should have 2 partial exits
    assert len(trades) == 2, f"Expected 2 trades, got {len(trades)}"
    
    # First exit at index 3 (11:28)
    trade_1 = trades[0]
    assert trade_1["exit_idx"] == 3
    assert trade_1["exit_reason"] == "Partial TP (Hour)"
    
    # Second exit at index 7 (11:32)
    trade_2 = trades[1]
    assert trade_2["exit_idx"] == 7
    assert trade_2["exit_reason"] == "Partial TP (Hour)"
