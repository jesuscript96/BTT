import os
import sys
import duckdb
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
cache_df['ticker'] = cache_df['ticker'].astype(str)
ticker_cache = cache_df[cache_df['ticker'] == ticker]
print(f"All rows in hot cache for {ticker}: {len(ticker_cache)}")
gap_cache = ticker_cache[ticker_cache['pmh_gap_pct'] >= 20.0]
print(f"Gap days (>=20%) in hot cache for {ticker}: {len(gap_cache)}")
if not gap_cache.empty:
    print(gap_cache[['timestamp', 'pmh_gap_pct']])
