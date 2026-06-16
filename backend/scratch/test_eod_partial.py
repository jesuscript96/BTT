import sys
import os
import numpy as np

# Adjust path to import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.portfolio_sim import simulate

# Create 5 bars of data
close = np.array([100.0, 101.0, 102.0, 103.0, 104.0], dtype=np.float64)
open_ = np.array([100.0, 100.0, 101.0, 102.0, 103.0], dtype=np.float64)
high = np.array([100.5, 101.5, 102.5, 103.5, 104.5], dtype=np.float64)
low = np.array([99.5, 99.8, 100.8, 101.8, 102.8], dtype=np.float64)

# Entry signal at bar 0. No exit signal.
entries = np.array([True, False, False, False, False], dtype=bool)
exits = np.array([False, False, False, False, False], dtype=bool)

# Setup 2 partial take profits:
# - 50% capital at 2% distance (entry is at open_ of bar 1 = 100.0. 2% target = 102.0, which is reached at high of bar 2 = 102.5).
# - 50% capital at EOD (triggered at bar 4 close = 104.0).
partial_take_profits = [
    {"distance_pct": 0.02, "capital_pct": 0.5},
    {"distance_pct": "EOD", "capital_pct": 0.5}
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
    fees=0.0,
    slippage=0.0,
    partial_take_profits=partial_take_profits,
    accumulate=False,
    look_ahead_prevention=True,  # enter on next open (bar 1 open = 100.0)
)

print("Trades:")
for t in res["trades"]:
    print(t)

assert len(res["trades"]) == 2, f"Expected 2 trades, got {len(res['trades'])}"
t1, t2 = res["trades"]
assert t1["exit_reason"] == "Partial TP", f"Expected Partial TP, got {t1['exit_reason']}"
assert t1["exit_idx"] == 2, f"Expected first partial to exit at bar 2, got {t1['exit_idx']}"
assert t2["exit_reason"] == "Partial TP (EOD)", f"Expected Partial TP (EOD), got {t2['exit_reason']}"
assert t2["exit_idx"] == 4, f"Expected second partial to exit at bar 4, got {t2['exit_idx']}"
print("TEST 1 SUCCESSFUL!")

# Test Case 2: Partial take profits sum to less than 100% (e.g. 50% at 2% distance, 25% at EOD)
# The remaining 25% should exit via standard EOD forced close.
partial_take_profits = [
    {"distance_pct": 0.02, "capital_pct": 0.5},
    {"distance_pct": "EOD", "capital_pct": 0.25}
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
    fees=0.0,
    slippage=0.0,
    partial_take_profits=partial_take_profits,
    accumulate=False,
    look_ahead_prevention=True,
)

print("\nTrades for Test Case 2:")
for t in res["trades"]:
    print(t)

assert len(res["trades"]) == 3, f"Expected 3 trades, got {len(res['trades'])}"
t1, t2, t3 = res["trades"]
assert t1["exit_reason"] == "Partial TP" and t1["size"] == 0.5
assert t2["exit_reason"] == "Partial TP (EOD)" and t2["size"] == 0.25
assert t3["exit_reason"] == "EOD" and t3["size"] == 0.25

print("TEST 2 SUCCESSFUL!")

