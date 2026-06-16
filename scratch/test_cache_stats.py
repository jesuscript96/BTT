import os
import sys
import time
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

from app.services.cache_service import load_hot_daily_cache, get_hot_daily_cache

print("Loading hot cache...")
load_hot_daily_cache()
cache_df = get_hot_daily_cache()

ticker = "VSME"
df = cache_df[cache_df['ticker'] == ticker].copy()
print(f"Total rows in cache for {ticker}: {len(df)}")

if 'timestamp' in df.columns:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)

# Locate gap indices
gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist()
print(f"Gap indices: {gap_indices}")

for offset in [0, 1, 2]:
    target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
    sub_df = df.loc[target_indices].copy()
    
    o = sub_df['rth_open']
    h = sub_df['rth_high']
    l = sub_df['rth_low']
    c = sub_df['rth_close']
    
    high_spike = (h - o) / o * 100
    low_spike = (o - l) / o * 100
    rthh_fade = (h - c) / h * 100
    neg_close = (c < o).astype(float) * 100
    mid_point = (h + l) / 2.0
    close_below_vwap = (c < mid_point).astype(float) * 100
    
    pm_fade = None
    close_above_pmh = None
    if 'pm_high' in sub_df.columns:
        pm_h = sub_df['pm_high']
        pm_fade = (pm_h - o) / pm_h * 100
        pm_fade = pm_fade.mask(pm_h <= 0, None)
        close_above_pmh = (c > pm_h).astype(float) * 100
        close_above_pmh = close_above_pmh.mask(pm_h <= 0, None)
        
    def safe_mean(s):
        if s is None or s.empty:
            return None
        val = s.mean()
        return float(val) if not pd.isna(val) else None

    print(f"Offset {offset} ({len(sub_df)} rows):")
    print(f"  high_rth_spike_avg: {safe_mean(high_spike)}")
    print(f"  pm_fade_avg: {safe_mean(pm_fade)}")
    print(f"  neg_close_freq: {safe_mean(neg_close)}")
