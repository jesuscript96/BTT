"""
Run two backtests in the SAME process to measure in-RAM cache effect
(simulates a warm backend serving multiple requests).
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app.database  # forces load_dotenv

from app.services.backtest_orchestrator import (
    run_backtest_orchestrator,
    BacktestRequest,
)

req = BacktestRequest(
    dataset_id="d7fa4ce2-6ebf-4bc5-aa20-dac96a139ff9",
    strategy_id="6c540796-756d-4df7-9908-8f4745acd513",
    init_cash=10000.0,
    risk_r=100.0,
    fees=0.01,
    slippage=0.01,
    market_sessions=["rth"],
    look_ahead_prevention=True,
)

print("\n=== RUN 1 (cold process) ===")
t1 = time.time()
r1 = run_backtest_orchestrator(req)
w1 = time.time() - t1
print(f"WALL #1: {w1:.3f}s  trades={r1.get('aggregate_metrics',{}).get('total_trades')}")

print("\n=== RUN 2 (warm process — same Python VM) ===")
t2 = time.time()
r2 = run_backtest_orchestrator(req)
w2 = time.time() - t2
print(f"WALL #2: {w2:.3f}s  trades={r2.get('aggregate_metrics',{}).get('total_trades')}")

print("\n=== RUN 3 (still warm) ===")
t3 = time.time()
r3 = run_backtest_orchestrator(req)
w3 = time.time() - t3
print(f"WALL #3: {w3:.3f}s  trades={r3.get('aggregate_metrics',{}).get('total_trades')}")

print(f"\nSUMMARY:")
print(f"  Run 1 (cold): {w1:.3f}s")
print(f"  Run 2 (warm): {w2:.3f}s  → savings: {w1-w2:.3f}s ({(1-w2/w1)*100:.1f}%)")
print(f"  Run 3 (warm): {w3:.3f}s  → savings vs cold: {w1-w3:.3f}s ({(1-w3/w1)*100:.1f}%)")
