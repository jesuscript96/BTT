import duckdb
import json
import pandas as pd
import numpy as np
import os
import copy

from app.database import get_db_connection
from app.services.data_service import fetch_qualifying_data, get_strategy
from app.services.backtest_service import run_backtest
from app.db.gcs_cache import get_connection, _select_intraday_glob_for_month, _fetch_and_cache_month

# Setup environment to mimic FastAPI
os.environ["DB_PROVIDER"] = "gcs"
os.environ["DISABLE_GCS_SYNC"] = "true"

dataset_id = "c3c3fb1a-a93e-42e8-9da8-e012267005ed"
strategy_id = "0ea5ed69-c8e7-4938-9e1b-2b5a92992a64"

# Fetch strategy
strategy = get_strategy(strategy_id)
strategy_def = strategy["definition"]

print("Strategy Name:", strategy_def.get("name"))

# Fetch qualifying data
qualifying_df = fetch_qualifying_data(
    dataset_id,
    req_start_date=None,
    req_end_date=None,
    preconditions=strategy_def.get("postgap_preconditions", []),
    apply_day=strategy_def.get("apply_day", "gap_day"),
)

# Fetch intraday data
dates = pd.to_datetime(qualifying_df["date"])
ym_pairs = sorted(set(zip(dates.dt.year, dates.dt.month)))

chunks = []
conn = get_connection()
for year, month in ym_pairs[:2]: # First 2 months
    month_mask = (dates.dt.year == year) & (dates.dt.month == month)
    valid_pairs_month = qualifying_df.loc[month_mask, ["ticker", "date"]].drop_duplicates().copy()
    if valid_pairs_month.empty:
        continue
    valid_pairs_month["date"] = pd.to_datetime(valid_pairs_month["date"]).dt.strftime("%Y-%m-%d")
    path = _select_intraday_glob_for_month(conn, year, month)
    if path is None:
        continue
    chunk = _fetch_and_cache_month(year, month, path, valid_pairs_month, batch_size=500, mi=1, n_months=1)
    if chunk is not None and not chunk.empty:
        chunks.append(chunk)

intraday_df = pd.concat(chunks, ignore_index=True)
valid_pairs = qualifying_df[["ticker", "date"]].drop_duplicates().copy()
valid_pairs["date"] = valid_pairs["date"].astype(str)
intraday_df["date"] = intraday_df["date"].astype(str)
intraday_df = intraday_df.merge(valid_pairs, on=["ticker", "date"], how="inner")

precomputed_groups = list(intraday_df.groupby(["date", "ticker"]))

for offset_val in range(1, 11):
    modified_def = copy.deepcopy(strategy_def)
    modified_def["entry_logic"]["root_condition"]["conditions"][0]["target"]["offset"] = offset_val
    
    bt_result = run_backtest(
        qualifying_df=qualifying_df,
        strategy_def=modified_def,
        init_cash=10000,
        risk_r=100,
        risk_type="FIXED",
        day_group_iter=iter(precomputed_groups),
        n_groups_hint=len(precomputed_groups),
    )
    print(f"Offset={offset_val}: Trades={len(bt_result['trades'])}")
