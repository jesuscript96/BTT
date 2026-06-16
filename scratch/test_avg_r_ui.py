import sys
import os
import numpy as np

# Set up paths
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from app.services.backtest_service import _aggregate_metrics

# Mock data
day_results = [{"total_trades": 2, "max_drawdown_pct": -2.0}]
trades = [
    {"pnl": 150.0, "r_multiple": 1.5, "date": "2026-06-01"},
    {"pnl": -100.0, "r_multiple": -1.0, "date": "2026-06-02"}
]
# Let's say we have 3 calendar days
global_eq = [{"time": 1770000000, "value": 10000.0}, {"time": 1770086400, "value": 10150.0}, {"time": 1770172800, "value": 10050.0}]
global_dd = [{"time": 1770000000, "value": 0.0}, {"time": 1770086400, "value": 0.0}, {"time": 1770172800, "value": -0.9852}]
init_cash = 10000.0
risk_r = 100.0

result = _aggregate_metrics(day_results, trades, global_eq, global_dd, init_cash, risk_r)
print("Calculation Result:")
for k, v in result.items():
    if k in ["r_squared", "avg_r_ui", "max_drawdown_pct", "total_pnl", "avg_return_per_day_pct"]:
        print(f"  {k}: {v}")

# Manual validation check
# Drawdowns = [0.0, 0.0, -0.9852]
# UI = sqrt((0 + 0 + (-0.9852)**2) / 3) = 0.9852 / sqrt(3) = 0.568804
# avg_return_per_day_pct = result["avg_return_per_day_pct"]
# expected_annualized_return_pct = avg_return_per_day_pct * 365.0
# expected_avg_r_ui = expected_annualized_return_pct / UI

drawdowns = np.array([0.0, 0.0, -0.9852])
expected_ui = float(np.sqrt(np.mean(drawdowns ** 2)))
avg_return_per_day_pct = result["avg_return_per_day_pct"]
expected_annualized_return_pct = avg_return_per_day_pct * 365.0
expected_avg_r_ui = expected_annualized_return_pct / expected_ui

print(f"UI: {expected_ui:.6f}")
print(f"Avg Return/Day %: {avg_return_per_day_pct:.6f}%")
print(f"Annualized Return %: {expected_annualized_return_pct:.6f}%")
print(f"Expected Ratio: {expected_avg_r_ui:.4f}")

assert abs(result["avg_r_ui"] - expected_avg_r_ui) < 0.05
print("SUCCESS: Calculations match expected values!")
