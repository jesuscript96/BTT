import sys
import os
import pandas as pd
import numpy as np

# Set path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.data_service import fetch_dataset_data, get_strategy
from app.services.strategy_engine import translate_strategy, compile_strategy_def

os.environ["DB_PROVIDER"] = "gcs"
os.environ["DISABLE_GCS_SYNC"] = "true"

dataset_id = "bd49cdb9-a9ff-47d1-8455-061732c1166f" # 3 meses Data RAPIDA
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
print("Strategy definition:", base_def)

precomputed_groups = list(intraday_df.groupby(["date", "ticker"]))
print(f"Precomputed groups: {len(precomputed_groups)}")

# Build qual lookup
qual_lookup = { (r["ticker"], str(r["date"])[:10]): r for r in qualifying_df.to_dict(orient="records") }

print("\n--- Running signal translation on first 15 groups ---")
groups_with_entries = 0
for i, ((date, ticker), group_df) in enumerate(precomputed_groups[:15]):
    group_df = group_df.sort_values("timestamp").reset_index(drop=True)
    daily_stats = qual_lookup.get((ticker, date), {})
    
    try:
        compiled_strat = compile_strategy_def(base_def)
        signals = translate_strategy(group_df, base_def, daily_stats, compiled=compiled_strat)
        entries_count = int(signals["entries"].sum())
        exits_count = int(signals["exits"].sum())
        print(f"Group {i:02d}: {ticker} on {date} | Entries: {entries_count} | Exits: {exits_count} | Stats keys: {list(daily_stats.keys())}")
        if entries_count > 0:
            groups_with_entries += 1
            # print some entry indices
            entry_idxs = np.where(signals["entries"])[0]
            print(f"  Entry indices: {entry_idxs[:5]}")
    except Exception as e:
        print(f"  Error on group {i}: {e}")

print(f"\nSummary: {groups_with_entries} out of 15 groups had entry signals.")
