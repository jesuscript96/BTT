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
cast_gaps = cache_df[(cache_df['ticker'] == 'CAST') & (cache_df['pmh_gap_pct'] >= 20.0)]
print("CAST gap days in cache:")
print(cast_gaps[['timestamp', 'pmh_gap_pct']])

target_dates = pd.to_datetime(cast_gaps['timestamp']).dt.strftime('%Y-%m-%d').tolist()
print(f"Target dates: {target_dates}")

# Let's run the query for CAST in intraday_1m
con = get_db_connection()
ym_dates = {}
for d_str in target_dates:
    dt = pd.to_datetime(d_str)
    ym_dates.setdefault((dt.year, dt.month), []).append(d_str)

print("YM dates:", ym_dates)

clauses = []
for (y, m), ds in ym_dates.items():
    date_list_str = ", ".join(f"DATE '{d}'" for d in ds)
    clauses.append(f"(year = {y} AND month = {m} AND CAST(date AS DATE) IN ({date_list_str}))")

if clauses:
    partition_filter = " OR ".join(clauses)
    query = f"""
        SELECT COUNT(*) FROM intraday_1m
        WHERE ticker = 'CAST'
          AND ({partition_filter})
    """
    count = con.execute(query).fetchone()
    print(f"Intraday rows for CAST on target dates: {count}")
else:
    print("No clauses constructed!")
con.close()
