"""Minimal test: datetime.date vs string in pandas index operations"""
import pandas as pd
import datetime
import numpy as np

# Create a DataFrame with string index
df = pd.DataFrame({
    "rth_high": [100.0, 102.0, 101.0, 103.0, 99.0],
    "rth_low": [98.0, 99.0, 97.0, 100.0, 96.0],
}, index=["2022-06-06", "2022-06-07", "2022-06-08", "2022-06-09", "2022-06-10"])

print("Index dtype:", df.index.dtype)
print("Index values:", df.index.tolist())

# Test with string
target_str = "2022-06-10"
print(f"\n--- String target: '{target_str}' ---")
print(f"  In index? {target_str in df.index}")
try:
    pos = df.index.get_loc(target_str)
    print(f"  get_loc: {pos}")
    lookback = 3
    start = max(0, pos - lookback)
    h = df["rth_high"].iloc[start:pos].max()
    print(f"  High of last {lookback}: {h}")
except Exception as e:
    print(f"  get_loc ERROR: {e}")

# Test with datetime.date
target_date = datetime.date(2022, 6, 10)
print(f"\n--- datetime.date target: {target_date} (type: {type(target_date)}) ---")
print(f"  In index? {target_date in df.index}")
try:
    pos = df.index.get_loc(target_date)
    print(f"  get_loc: {pos}")
    lookback = 3
    start = max(0, pos - lookback)
    h = df["rth_high"].iloc[start:pos].max()
    print(f"  High of last {lookback}: {h}")
except Exception as e:
    print(f"  get_loc ERROR: {e}")

# Test with str() of datetime.date  
target_str2 = str(datetime.date(2022, 6, 10))
print(f"\n--- str(datetime.date) target: '{target_str2}' (type: {type(target_str2)}) ---")
print(f"  In index? {target_str2 in df.index}")
try:
    pos = df.index.get_loc(target_str2)
    print(f"  get_loc: {pos}")
except Exception as e:
    print(f"  get_loc ERROR: {e}")

# Test with Timestamp
target_ts = pd.Timestamp("2022-06-10")
print(f"\n--- Timestamp target: {target_ts} (type: {type(target_ts)}) ---")
print(f"  In index? {target_ts in df.index}")
try:
    pos = df.index.get_loc(target_ts)
    print(f"  get_loc: {pos}")
except Exception as e:
    print(f"  get_loc ERROR: {e}")
