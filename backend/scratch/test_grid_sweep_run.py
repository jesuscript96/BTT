import sys
import os
import pandas as pd
import numpy as np

# 1. Connect directly to users.duckdb
import duckdb
original_connect = duckdb.connect

# Set path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.data_service import fetch_dataset_data, get_strategy
from app.services.backtest_service import run_backtest
from app.services.strategy_engine import translate_strategy, compile_strategy_def

os.environ["DB_PROVIDER"] = "gcs"
os.environ["DISABLE_GCS_SYNC"] = "true"

dataset_id = "10358a6a-a0f4-4664-8b89-de579652dc74" # Dataset from logs
strategy_id = "mock_strategy_2"

print("Fetching dataset...")
try:
    qualifying_df, intraday_df = fetch_dataset_data(dataset_id)
    print(f"Fetched qualifying: {len(qualifying_df)} rows, intraday: {len(intraday_df)} rows")
except Exception as e:
    print(f"Error fetching dataset: {e}")
    sys.exit(1)

if qualifying_df.empty or intraday_df.empty:
    print("Dataset data is empty!")
    sys.exit(1)

strategy = get_strategy(strategy_id)
if not strategy:
    print("Strategy not found!")
    sys.exit(1)

base_def = strategy["definition"]
print(f"Strategy loaded: {strategy['name']}")

# Check one day's signals
precomputed_groups = list(intraday_df.groupby(["date", "ticker"]))
print(f"Precomputed groups: {len(precomputed_groups)}")

# Let's inspect the first group
(date, ticker), group_df = precomputed_groups[0]
print(f"Inspecting group 0: date={date}, ticker={ticker}, rows={len(group_df)}")

# Let's run translate_strategy for this group
group_df = group_df.sort_values("timestamp").reset_index(drop=True)
# Get daily stats for this group from qualifying_df
qual_lookup = { (r["ticker"], str(r["date"])[:10]): r for r in qualifying_df.to_dict(orient="records") }
daily_stats = qual_lookup.get((ticker, date), {})
print(f"Daily stats for {ticker} on {date}: {daily_stats}")

try:
    compiled_strat = compile_strategy_def(base_def)
    signals = translate_strategy(group_df, base_def, daily_stats, compiled=compiled_strat)
    entries_any = signals["entries"].any()
    exits_any = signals["exits"].any()
    print(f"Signal translation for {ticker} on {date}: entries_any={entries_any}, exits_any={exits_any}")
except Exception as e:
    print(f"Error translating strategy: {e}")

# Run backtest
print("Running run_backtest with precomputed groups...")
bt_result = run_backtest(
    qualifying_df=qualifying_df,
    strategy_def=base_def,
    init_cash=10000,
    risk_r=100,
    risk_type="FIXED",
    size_by_sl=False,
    fees=0,
    fee_type="PERCENT",
    slippage=0,
    day_group_iter=iter(precomputed_groups),
    n_groups_hint=len(precomputed_groups),
)
print("Backtest result:")
print(f"Trades: {len(bt_result.get('trades', []))}")
print(f"Day results count: {len(bt_result.get('day_results', []))}")
