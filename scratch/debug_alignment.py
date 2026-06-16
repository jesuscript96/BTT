import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('backend'))
from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.database import get_db_connection
from app.services.strategy_engine import _resample_if_needed, _align_signals_to_1m

conn = get_db_connection()
path = "gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=1/*.parquet"
df_1m = conn.execute(f"""
    SELECT "timestamp", open, high, low, close, volume
    FROM read_parquet('{path}', hive_partitioning=true)
    WHERE ticker = 'JFBR' AND date = DATE '2026-01-16'
    ORDER BY "timestamp"
""").fetchdf()

df_15m = _resample_if_needed(df_1m, "15m")
df_15m["acc_volume"] = df_15m["volume"].cumsum()

# Let's mock a signal: True when acc_volume > 100,000,000
signals_tf = df_15m["acc_volume"] > 100000000.0
print("Number of True signals in 15m:", signals_tf.sum())

# Let's test original alignment
orig_aligned = _align_signals_to_1m(signals_tf, df_1m, "15m")
print("Original alignment True count:", orig_aligned.sum())
if orig_aligned.any():
    first_true_idx = orig_aligned.idxmax()
    print("Original first True 1m bar:", df_1m.iloc[first_true_idx]["timestamp"])

# Let's test the proposed alignment
def proposed_align(signals_tf: pd.Series, df_1m: pd.DataFrame, timeframe: str) -> pd.Series:
    ts_1m = pd.to_datetime(df_1m["timestamp"])
    df_with_ts = df_1m.set_index(ts_1m)
    
    tf_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h"}
    freq = tf_map.get(timeframe, "1min")
    
    # Get resampler indices mapping
    resampler = df_with_ts.resample(freq)
    bucket_indices = resampler.indices
    
    # Filter non-empty buckets
    non_empty_buckets = {k: v for k, v in bucket_indices.items() if len(v) > 0}
    sorted_keys = sorted(non_empty_buckets.keys())
    
    result = pd.Series(False, index=df_1m.index)
    
    delta = pd.to_timedelta(freq)
    for i, T in enumerate(sorted_keys):
        if not signals_tf.iloc[i]:
            continue
        
        T_next = T + delta
        next_indices = bucket_indices.get(T_next, [])
        if len(next_indices) > 0:
            result.iloc[next_indices] = True
            
    return result

prop_aligned = proposed_align(signals_tf, df_1m, "15m")
print("Proposed alignment True count:", prop_aligned.sum())
if prop_aligned.any():
    first_true_idx_prop = prop_aligned.idxmax()
    print("Proposed first True 1m bar:", df_1m.iloc[first_true_idx_prop]["timestamp"])
