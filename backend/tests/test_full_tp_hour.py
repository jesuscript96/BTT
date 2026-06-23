import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from app.services.portfolio_sim import simulate

def test_full_tp_hour():
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
    
    # Full TP configuration by hour at 11:28
    tp_time_limit = "HOUR:11:28"
    
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
        tp_time_limit=tp_time_limit,
    )
    
    trades = res["trades"]
    
    # We should have exactly 1 trade exited at 11:28 (index 3)
    assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
    
    trade = trades[0]
    assert trade["exit_idx"] == 3
    assert trade["exit_reason"] == "TP"
