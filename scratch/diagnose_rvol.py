import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('backend'))
from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.database import get_db_connection
from app.services.indicators import compute_indicator

# 1. Fetch some test intraday data
conn = get_db_connection()
path = "gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=1/*.parquet"
df_1m = conn.execute(f"""
    SELECT "timestamp", open, high, low, close, volume
    FROM read_parquet('{path}', hive_partitioning=true)
    WHERE ticker = 'JFBR' AND date = DATE '2026-01-16'
    ORDER BY "timestamp"
""").fetchdf()

print(f"Total rows fetched: {len(df_1m)}")

# 2. Diagnose RVOL by bar (period 20)
rvol_20 = compute_indicator("RVOL by bar", df_1m, period=20)
df_1m["rvol_20"] = rvol_20

print("\n--- Diagnostic RVOL by bar (Period = 20) ---")
print(f"Total non-null RVOL values: {rvol_20.notnull().sum()}")
print(f"Total null RVOL values: {rvol_20.isnull().sum()}")

# Verify first non-null values
first_valid_idx = rvol_20.first_valid_index()
if first_valid_idx is not None:
    print(f"\nFirst valid index is: {first_valid_idx}")
    print(f"Timestamp of first valid: {df_1m.iloc[first_valid_idx]['timestamp']}")
    # Print the window leading to the first valid value
    print("\nData window for the first calculation:")
    window = df_1m.iloc[first_valid_idx-19 : first_valid_idx+1]
    print(window[['timestamp', 'volume', 'rvol_20']])
    
    # Calculate mathematically
    vol_values = window['volume'].values.astype(float)
    avg_vol_calc = vol_values.mean()
    curr_vol = vol_values[-1]
    rvol_calc = curr_vol / avg_vol_calc
    print(f"\nManual calculation: {curr_vol} / {avg_vol_calc:.2f} = {rvol_calc:.4f}")
    print(f"Indicator returned: {rvol_20.iloc[first_valid_idx]:.4f}")
    assert np.allclose(rvol_calc, rvol_20.iloc[first_valid_idx]), "Calculation mismatch!"
    print("SUCCESS: Manual calculation matches indicator output perfectly!")

# 3. Check for division by zero / zero volume bars
zero_vol_bars = df_1m[df_1m['volume'] == 0]
print(f"\nNumber of bars with volume = 0: {len(zero_vol_bars)}")
if not zero_vol_bars.empty:
    print("RVOL values on zero volume bars:")
    print(df_1m.loc[zero_vol_bars.index, ['timestamp', 'volume', 'rvol_20']].head(5))

# 4. Check statistical distribution of RVOL values
print("\nRVOL by bar stats summary:")
print(rvol_20.describe())
print(f"Percentage of bars with RVOL > 1: {(rvol_20 > 1.0).mean() * 100:.2f}%")
print(f"Percentage of bars with RVOL > 2: {(rvol_20 > 2.0).mean() * 100:.2f}%")
print(f"Percentage of bars with RVOL > 5: {(rvol_20 > 5.0).mean() * 100:.2f}%")
