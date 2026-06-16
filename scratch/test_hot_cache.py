import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.database import get_db_connection
from app.services.cache_service import load_hot_daily_cache, get_hot_daily_cache

load_hot_daily_cache()
cache_df = get_hot_daily_cache()
if cache_df is not None:
    print(f"Total rows in hot cache: {len(cache_df)}")
    ticker = 'SPCX'
    # Match how get_gap_stats_all_days does it:
    # ticker_cache = cache_df[(cache_df['ticker'] == ticker) & (cache_df['pmh_gap_pct'] >= 20.0)]
    # Note that 'ticker' was converted to category, so compare as string
    cache_df['ticker'] = cache_df['ticker'].astype(str)
    spcx_all = cache_df[cache_df['ticker'] == ticker]
    print(f"All rows for SPCX in hot cache: {len(spcx_all)}")
    spcx_gaps = cache_df[(cache_df['ticker'] == ticker) & (cache_df['pmh_gap_pct'] >= 20.0)]
    print(f"SPCX gap days (pmh_gap_pct >= 20.0): {len(spcx_gaps)}")
    if not spcx_gaps.empty:
        print(spcx_gaps[['timestamp', 'pmh_gap_pct']])
else:
    print("Hot cache is None!")
