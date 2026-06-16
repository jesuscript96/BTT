import os
import sys
import time
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Add backend to sys.path
sys.path.insert(0, os.path.abspath('.'))

# Enable mock data to run locally and instantly
os.environ["ALLOW_MOCK_DATA"] = "true"

from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator
from fastapi import HTTPException

# Define a strategy definition with swing_option active
strategy_def = {
    "name": "Test Prefetch Swing",
    "bias": "short",
    "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [] # empty means entry on first RTH bar
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": []
        }
    },
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 5.0},
        "use_take_profit": True,
        "take_profit": {"type": "Percentage", "value": 10.0},
        "accept_reentries": False,
        "swing_option": {
            "active": True,
            "target_day": "gap_1_day"
        }
    }
}

req = BacktestRequest(
    dataset_id="mock_dataset_1",
    strategy_definition=strategy_def,
    init_cash=10000.0,
    risk_r=100.0,
    risk_type='FIXED',
    size_by_sl=False,
    fees=0.0,
    slippage=0.0,
    start_date="2025-10-01",
    end_date="2025-10-31"
)

print("Running backtest orchestration with Swing Option...")
t0 = time.time()
try:
    res = run_backtest_orchestrator(req)
    t1 = time.time()
    print("Success!")
    print(f"Total orchestration execution time: {round(t1 - t0, 2)}s")
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
