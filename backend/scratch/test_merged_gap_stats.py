import sys
import os
import time
import pandas as pd
import yfinance as yf

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.routers.ticker_analysis import _fetch_yfinance_history, safe_mean
from app.services.cache_service import get_hot_daily_cache

ticker = "MULN"

t0 = time.time()
# 1. Fetch yfinance history
df = _fetch_yfinance_history(ticker)
print(f"yfinance history shape: {df.shape}, time: {time.time() - t0:.2f}s")

# 2. Get hot cache
t0 = time.time()
cache_df = get_hot_daily_cache()
print(f"Hot cache total shape: {cache_df.shape}, time: {time.time() - t0:.2f}s")

# 3. Merge
t0 = time.time()
ticker_cache = cache_df[cache_df['ticker'] == ticker].copy()
print(f"Ticker cache rows: {len(ticker_cache)}")

# Initialize columns to NaN in case they are missing
for col in ['pm_high', 'pm_low', 'pm_volume', 'pmh_gap_pct', 'pmh_fade_pct']:
    df[col] = None

if not ticker_cache.empty and not df.empty:
    # Normalize timestamps to date objects
    df['timestamp_dt'] = pd.to_datetime(df['timestamp']).dt.date
    ticker_cache['timestamp_dt'] = pd.to_datetime(ticker_cache['timestamp']).dt.date
    
    # We want columns: timestamp_dt, pm_high, pm_low, pm_volume, pmh_gap_pct, pmh_fade_pct
    cols_to_merge = ['timestamp_dt', 'pm_high', 'pm_low', 'pm_volume', 'pmh_gap_pct', 'pmh_fade_pct']
    cols_to_merge = [c for c in cols_to_merge if c in ticker_cache.columns]
    
    # Drop initialized columns from df before merging to avoid duplicate columns
    df = df.drop(columns=[c for c in cols_to_merge if c != 'timestamp_dt' and c in df.columns])
    
    df = pd.merge(df, ticker_cache[cols_to_merge], on='timestamp_dt', how='left')
    df = df.drop(columns=['timestamp_dt'])

print(f"Merged df shape: {df.shape}, time: {time.time() - t0:.2f}s")
print(f"Columns: {list(df.columns)}")
print(f"Rows with pm_high: {df['pm_high'].notna().sum() if 'pm_high' in df.columns else 0}")
