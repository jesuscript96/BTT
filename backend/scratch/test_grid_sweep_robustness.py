import sys
import os
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Set path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# os.environ["DB_PROVIDER"] = "gcs"
os.environ["DISABLE_GCS_SYNC"] = "true"
os.environ["ALLOW_MOCK_DATA"] = "true"

from app.services.optimization_service import run_optimization_grid
from app.services.data_service import get_strategy, list_strategies

print("Listing available strategies...")
strategies = list_strategies()
for s in strategies:
    print(f"ID: {s['id']}, Name: {s['name']}")

# We will use the first available strategy
if not strategies:
    print("No strategies found in the database!")
    sys.exit(1)

strategy_id = strategies[0]["id"]
print(f"Using strategy: {strategies[0]['name']} (ID: {strategy_id})")

# Let's inspect its definition
strategy = get_strategy(strategy_id)
strategy_def = strategy["definition"]

# Let's look for a parameter we can optimize, e.g., indicator period or risk stop loss
# If it has exit_logic, we can optimize exit_logic.root_condition.conditions.0.source.period or similar
# Let's see what parameters are available
from app.services.optimization_service import extract_parameters
params = extract_parameters(strategy_def)
print(f"Extracted parameters count: {len(params)}")
for p in params:
    print(f"ID: {p['id']}, Label: {p['label']}, Min: {p['min']}, Max: {p['max']}, Step: {p['step']}, Path: {p['path']}")

if len(params) < 2:
    print("Strategy doesn't have enough parameters to run a 2D grid sweep!")
    sys.exit(0)

# Let's configure a 2D sweep using the first 2 parameters
param_configs = [
    {
        "id": params[0]["id"],
        "label": params[0]["label"],
        "path": params[0]["path"],
        "min": float(params[0]["min"]),
        "max": float(params[0]["max"]),
        "steps": 5
    },
    {
        "id": params[1]["id"],
        "label": params[1]["label"],
        "path": params[1]["path"],
        "min": float(params[1]["min"]),
        "max": float(params[1]["max"]),
        "steps": 5
    }
]

print("Running optimization grid sweep...")
dataset_id = "1ebec669-a407-40bb-918d-bbfa022fd339" # Pre-cached test dataset
backtest_params = {
    "init_cash": 10000.0,
    "risk_r": 100.0,
    "risk_type": "FIXED",
    "size_by_sl": False,
    "fees": 0.0,
    "fee_type": "PERCENT",
    "slippage": 0.0,
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
}

try:
    result = run_optimization_grid(
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        param_configs=param_configs,
        metric="sharpe",
        backtest_params=backtest_params
    )
    print("Grid sweep finished successfully!")
    print(f"Result keys: {list(result.keys())}")
    print(f"Axes shape: {result['shape']}")
    for i, p in enumerate(result["params"]):
        print(f"Param {i} ({p['label']}) values: {p['values']}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed: {e}")
