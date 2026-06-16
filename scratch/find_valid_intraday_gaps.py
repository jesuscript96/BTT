import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import pandas as pd
from app.database import get_db_connection
from app.services.cache_service import load_hot_daily_cache, get_hot_daily_cache

load_hot_daily_cache()
cache_df = get_hot_daily_cache()
cache_df['ticker'] = cache_df['ticker'].astype(str)

# Get top tickers with gaps in 2024
gaps_2024 = cache_df[(cache_df['pmh_gap_pct'] >= 20.0) & (cache_df['year'] >= 2024)].copy()
print(f"Total gaps in 2024+: {len(gaps_2024)}")

# We will test the first 30 gap days to find one with intraday rows
con = get_db_connection()
found = 0
for idx, row in gaps_2024.head(50).iterrows():
    ticker = row['ticker']
    d_str = pd.to_datetime(row['timestamp']).strftime('%Y-%m-%d')
    y, m = row['year'], row['month']
    
    try:
        query = f"""
            SELECT COUNT(*) FROM intraday_1m
            WHERE ticker = ? 
              AND year = ? AND month = ?
              AND CAST(date AS DATE) = DATE '{d_str}'
        """
        count = con.execute(query, [ticker, int(y), int(m)]).fetchone()[0]
        if count > 0:
            print(f"Found match: ticker={ticker}, date={d_str}, count={count}")
            found += 1
            if found >= 5:
                break
    except Exception as e:
        print(f"Error checking {ticker} on {d_str}: {e}")
con.close()
