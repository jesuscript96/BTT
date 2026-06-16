import os
import sys
import pandas as pd
import numpy as np

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.database import get_db_connection
from app.services.indicators import compute_indicator
from app.init_db import init_db

# 1. Initialize DB views first
init_db()

# 2. Get connection
con = get_db_connection()

# 3. Fetch candles for AEI on 2025-01-02
df = con.execute("""
    SELECT timestamp, open, high, low, close, volume 
    FROM massive.intraday_1m 
    WHERE ticker = 'AEI' AND CAST(timestamp AS DATE) = '2025-01-02'
    ORDER BY timestamp
""").fetchdf()

print(f"Loaded {len(df)} candles.")
if len(df) > 0:
    # Let's compute 'Previous max' from indicators
    prev_max = compute_indicator(
        name="Previous max",
        df=df,
        ap_session="ap.PM"
    )
    df["prev_max"] = prev_max
    
    # Calculate distance pct and position mask using our FIXED logic
    df["distance_pct"] = abs(df["close"] - df["prev_max"]) / df["prev_max"] * 100
    df["position_mask_new"] = df["close"] <= df["prev_max"]
    df["condition_new"] = (df["distance_pct"] < 10.0) & df["position_mask_new"]
    
    # Also check the OLD logic (strict < and pos fallback bug if position was None)
    df["position_mask_old_strict"] = df["close"] < df["prev_max"]
    df["condition_old_strict"] = (df["distance_pct"] < 10.0) & df["position_mask_old_strict"]
    df["condition_old_any"] = (df["distance_pct"] < 10.0)
    
    pd.set_option('display.max_rows', 100)
    print("\nTracing calculations for first 30 bars:")
    # Format timestamp for printing
    df["time_str"] = df["timestamp"].dt.strftime("%H:%M")
    print(df[["time_str", "open", "high", "low", "close", "prev_max", "distance_pct", "position_mask_new", "condition_new", "condition_old_strict", "condition_old_any"]].head(30))
else:
    print("No candles found.")
