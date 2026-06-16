import sys
import os
import time
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), '../.env')))

from app.database import get_db_connection
from app.services.cache_service import get_hot_daily_cache

ticker = "MULN"

t0 = time.time()
# 1. Get hot cache
cache_df = get_hot_daily_cache()
ticker_cache = cache_df[(cache_df['ticker'] == ticker) & (cache_df['gap_pct'] >= 20.0)].copy()
print(f"Gap days count in cache: {len(ticker_cache)}")

if ticker_cache.empty:
    print("No gap days, returning empty.")
    sys.exit(0)

# 2. Determine needed year/month partitions
needed_partitions = set()
for timestamp in ticker_cache['timestamp']:
    dt = pd.to_datetime(timestamp)
    needed_partitions.add((dt.year, dt.month))
    # Also add next month in case the next 2 days fall into it
    next_day = dt + pd.Timedelta(days=5)
    needed_partitions.add((next_day.year, next_day.month))

print(f"Needed partitions: {needed_partitions}")

# 3. Build partition filter clause
clauses = []
for y, m in needed_partitions:
    clauses.append(f"(year = {y} AND month = {m})")
partition_filter = " OR ".join(clauses)

# 4. Query with partition pruning
con = get_db_connection()
query = f"""
    SELECT * FROM daily_metrics 
    WHERE ticker = '{ticker}' 
      AND ({partition_filter})
    ORDER BY timestamp ASC
"""
print("Querying...")
df = con.execute(query).fetchdf()
print(f"Query returned {len(df)} rows, time taken: {time.time() - t0:.2f}s")
if not df.empty:
    print(df[['timestamp', 'gap_pct', 'pm_high', 'open', 'close']].head(5))
