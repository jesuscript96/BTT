import os
import duckdb
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load env variables from backend/.env
load_dotenv('backend/.env')

access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
if access_key and secret:
    con.execute(f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

# Get intraday data for BNGO on 2025-01-03
query = f"""
    SELECT timestamp, open, high, low, close, volume
    FROM read_parquet('gs://{bucket}/cold_storage/intraday_1m/year=2025/month=1/*.parquet', hive_partitioning=true)
    WHERE ticker = 'BNGO'
      AND CAST(timestamp AS DATE) = '2025-01-03'
    ORDER BY timestamp ASC
"""

df = con.execute(query).fetchdf()
con.close()

print(f"Total rows retrieved: {len(df)}")

# Let's import the indicator calculation logic
import sys
sys.path.append(os.path.abspath('backend'))
from app.services.indicators import compute_indicator

# Let's mock the daily stats (ds)
daily_stats = {
    "rth_open": 0.31,
    "pm_high": 0.398,
    "pm_low": 0.2548,
    "prev_close": 0.2553
}

# Scenario 1: Calculate PM Open on full untrimmed data
pm_open_full = compute_indicator(
    name="PM Open",
    df=df,
    daily_stats=daily_stats
)

print(f"\nScenario 1 (Full Untrimmed Data):")
print(f"  Premarket open calculated: {pm_open_full.iloc[0]} (first bar is {df['timestamp'].iloc[0]})")

# Scenario 2: Calculate PM Open on RTH-trimmed data (simulating how backtest trims session first)
df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
rth_mask = (df['timestamp_dt'].dt.time >= pd.Timestamp("09:30:00").time()) & (df['timestamp_dt'].dt.time <= pd.Timestamp("16:00:00").time())
df_rth = df[rth_mask].reset_index(drop=True)

pm_open_rth = compute_indicator(
    name="PM Open",
    df=df_rth,
    daily_stats=daily_stats
)

print(f"\nScenario 2 (RTH-Trimmed Data):")
print(f"  Premarket open calculated: {pm_open_rth.iloc[0]} (first bar is {df_rth['timestamp'].iloc[0]})")
print(f"  Daily stats rth_open: {daily_stats['rth_open']}")

# Let's inspect the actual RTH price action and where Close > PM Open would trigger
df_rth['pm_open_val'] = pm_open_rth
df_rth['condition_met'] = df_rth['close'] > df_rth['pm_open_val']

print("\n--- RTH Bars and Condition (Close > PM Open) ---")
for idx, row in df_rth.iterrows():
    t_str = row['timestamp_dt'].strftime('%H:%M')
    # Print the first few bars, and any bar where condition is met
    if idx < 10 or row['condition_met']:
        print(f"Time: {t_str} | Open: {row['open']:.4f} | Close: {row['close']:.4f} | PM Open: {row['pm_open_val']:.4f} | Condition Met: {row['condition_met']}")
        if row['condition_met']:
            # Show just 3 more rows after condition is met for the first time
            for offset in range(1, 4):
                if idx + offset < len(df_rth):
                    next_row = df_rth.iloc[idx + offset]
                    next_t_str = next_row['timestamp_dt'].strftime('%H:%M')
                    print(f"Time: {next_t_str} | Open: {next_row['open']:.4f} | Close: {next_row['close']:.4f} | PM Open: {next_row['pm_open_val']:.4f} | Condition Met: {next_row['condition_met']}")
            break
