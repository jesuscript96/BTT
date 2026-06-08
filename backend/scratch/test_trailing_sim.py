import os
import sys
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.services.portfolio_sim import simulate

def test_long_trailing():
    print("=== Testing LONG Trailing Stop ===")
    # entry at 100, trail of 10%
    # Bar 0: Entry at 100
    # Bar 1: Hits 110 (+10%), activates trailing stop at 100
    # Bar 2: Drops to 100, should exit at 100 (breakeven)
    open_ = np.array([100.0, 100.0, 110.0, 100.0])
    high  = np.array([100.0, 110.0, 110.0, 100.0])
    low   = np.array([100.0, 100.0, 100.0, 100.0])
    close = np.array([100.0, 110.0, 100.0, 100.0])
    
    entries = np.array([True, False, False, False])
    exits   = np.array([False, False, False, False])
    
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
        sl_trail=True,
        trail_pct=0.10, # 10%
        sl_stop=0.20 # 20% hard stop
    )
    
    trades = res["trades"]
    print("Trades returned:", trades)
    assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
    trade = trades[0]
    assert trade["exit_reason"] == "Trailing", f"Expected exit reason Trailing, got {trade['exit_reason']}"
    assert abs(trade["exit_price"] - 100.0) < 0.01, f"Expected exit price 100.0, got {trade['exit_price']}"
    print("LONG Trailing Stop verification SUCCESSFUL!")

def test_short_trailing():
    print("\n=== Testing SHORT Trailing Stop ===")
    # entry at 100, trail of 10%
    # Bar 0: Entry (short) at 100
    # Bar 1: Drops to 90 (-10%), activates trailing stop at 100
    # Bar 2: Rises to 100, should exit at 100 (breakeven)
    open_ = np.array([100.0, 100.0, 90.0, 100.0])
    high  = np.array([100.0, 100.0, 100.0, 100.0])
    low   = np.array([100.0, 90.0,  90.0, 100.0])
    close = np.array([100.0, 90.0,  100.0, 100.0])
    
    entries = np.array([True, False, False, False])
    exits   = np.array([False, False, False, False])
    
    res = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="shortonly",
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        sl_trail=True,
        trail_pct=0.10, # 10%
        sl_stop=0.20 # 20% hard stop
    )
    
    trades = res["trades"]
    print("Trades returned:", trades)
    assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
    trade = trades[0]
    assert trade["exit_reason"] == "Trailing", f"Expected exit reason Trailing, got {trade['exit_reason']}"
    assert abs(trade["exit_price"] - 100.0) < 0.01, f"Expected exit price 100.0, got {trade['exit_price']}"
    print("SHORT Trailing Stop verification SUCCESSFUL!")

if __name__ == "__main__":
    try:
        test_long_trailing()
        test_short_trailing()
        print("\nAll unit tests passed successfully!")
    except AssertionError as ae:
        print(f"Assertion failed: {ae}")
    except Exception as e:
        print(f"Error: {e}")
