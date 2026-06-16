import os
import sys
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator
from fastapi import HTTPException

# We'll test with the 188-pair dataset and mock_strategy_2 (ORB Short)
req = BacktestRequest(
    dataset_id='bd49cdb9-a9ff-47d1-8455-061732c1166f',
    strategy_id='mock_strategy_2',
    init_cash=10000.0,
    risk_r=100.0,
    risk_type='FIXED',
    size_by_sl=False,
    fees=0.0,
    slippage=0.0
)

print("Running backtest orchestration...")
try:
    res = run_backtest_orchestrator(req)
    print("Success!")
    print("Keys in results:", res.keys())
    print("Total trades:", len(res.get("trades", [])))
    print("Aggregate metrics summary:")
    print(res.get("aggregate_metrics"))
except HTTPException as he:
    print(f"HTTPException raised: status={he.status_code}, detail={he.detail}")
except Exception as e:
    print("General Exception raised:")
    import traceback
    traceback.print_exc()
