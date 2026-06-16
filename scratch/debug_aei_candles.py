import requests
import json
import pandas as pd
import numpy as np
import sys
import os

# Add backend to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.services.indicators import compute_indicator
from app.services.strategy_engine import _eval_price_level_distance, translate_strategy

# Fetch raw candles
url = "http://127.0.0.1:8000/api/candles"
params = {
    "dataset_id": "bd49cdb9-a9ff-47d1-8455-061732c1166f",
    "ticker": "AEI",
    "date": "2025-01-02"
}

res = requests.get(url, params=params)
if res.status_code != 200:
    print(f"Error fetching candles: {res.status_code} - {res.text}")
    sys.exit(1)

data = res.json()
candles_list = data.get("candles", [])
print(f"Loaded {len(candles_list)} candles")

# Convert to DataFrame in format expected by indicators
# Keys in API candles: ['time', 'open', 'high', 'low', 'close', 'volume', 'vwap']
# We need to construct a DataFrame with columns: open, high, low, close, volume, timestamp
# Note that timestamp needs to be string formatted datetime? Let's check what backend expects.
# In backtest_service.py:
#         arrays = {
#             "open": day_df["open"].values.astype(np.float64),
#             "high": day_df["high"].values.astype(np.float64),
#             "low": day_df["low"].values.astype(np.float64),
#             "close": day_df["close"].values.astype(np.float64),
#             "volume": day_df["volume"].values,
#             "timestamp": day_df["timestamp"].values,
#         }
# In compute_indicator:
#     timestamps = pd.to_datetime(df["timestamp"])

# Let's build the DataFrame
df = pd.DataFrame(candles_list)
# Convert time (unix timestamp) to datetime string
df["timestamp"] = pd.to_datetime(df["time"], unit="s").dt.strftime("%Y-%m-%d %H:%M:%S")

# Rename or ensure float type
df["open"] = df["open"].astype(float)
df["high"] = df["high"].astype(float)
df["low"] = df["low"].astype(float)
df["close"] = df["close"].astype(float)
df["volume"] = df["volume"].astype(float)

# Compute indicators manually
prev_max = compute_indicator(
    name="Previous max",
    df=df,
    ap_session="ap.PM",
)

acc_vol = compute_indicator(
    name="Accumulated Volume",
    df=df,
)

# Put indicators in df
df["prev_max"] = prev_max
df["acc_vol"] = acc_vol

# Let's inspect candles from 04:00 to 04:30
# Print table
print(f"{'Time':<20} | {'Open':<6} | {'High':<6} | {'Low':<6} | {'Close':<6} | {'Volume':<8} | {'AccVol':<10} | {'PrevMax':<8} | {'Dist%':<6} | {'PosMask':<7}")
print("-" * 105)

for i in range(len(df)):
    time_str = df.iloc[i]["timestamp"]
    t_part = time_str.split(" ")[1]
    if "04:00:00" <= t_part <= "04:30:00":
        o = df.iloc[i]["open"]
        h = df.iloc[i]["high"]
        l = df.iloc[i]["low"]
        c = df.iloc[i]["close"]
        v = df.iloc[i]["volume"]
        av = df.iloc[i]["acc_vol"]
        pm = df.iloc[i]["prev_max"]
        
        # calculate distance %
        dist = abs(c - pm) / pm * 100 if not np.isnan(pm) and pm != 0 else np.nan
        pos_mask = "BELOW" if c <= pm else "ABOVE"
        
        print(f"{time_str:<20} | {o:<6.2f} | {h:<6.2f} | {l:<6.2f} | {c:<6.2f} | {v:<8.0f} | {av:<10.0f} | {pm:<8.2f} | {dist:<6.2f} | {pos_mask:<7}")
