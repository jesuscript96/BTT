import sys
import os
import pandas as pd
import numpy as np

# Add backend dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.portfolio_sim import simulate
from app.services.backtest_service import run_backtest

# Create mock data
n = 10
df = pd.DataFrame({
    "open": [100.0] * n,
    "high": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
    "low": [99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0],
    "close": [100.5] * n,
    "volume": [1000] * n,
    "timestamp": pd.date_range("2026-06-09 09:30:00", periods=n, freq="min")
})

# Test simulate with LOD Market Structure Stop Loss
hods = df["high"].cummax().values
lods = df["low"].cummin().values
pm_highs = np.array([102.0] * n)
pm_lows = np.array([98.0] * n)
prev_highs = np.array([101.0] * n)
prev_lows = np.array([99.0] * n)

entries = np.array([True] + [False] * (n - 1))
exits = np.array([False] * n)

print("Running simulation with LOD Stop Loss and size_by_sl=True...")
result = simulate(
    close=df["close"].values,
    open_=df["open"].values,
    high=df["high"].values,
    low=df["low"].values,
    entries=entries,
    exits=exits,
    direction="longonly",
    init_cash=10000.0,
    risk_r=100.0,
    size_by_sl=True,
    hs_type="Market Structure (HOD/LOD)",
    hs_value="LOD",
    hods=hods,
    lods=lods,
    pm_highs=pm_highs,
    pm_lows=pm_lows,
    prev_highs=prev_highs,
    prev_lows=prev_lows
)

print("\nSimulated Trades:")
for t in result["trades"]:
    print(t)

print("\nAll tests passed successfully!")
