import os
import sys
import time
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.services.cache_service import load_hot_daily_cache, get_hot_daily_cache
from app.database import get_db_connection
import pandas as pd

print("1. Loading hot daily cache...")
t0 = time.time()
load_hot_daily_cache()
cache_df = get_hot_daily_cache()
print(f"Loaded hot daily cache in {time.time() - t0:.2f}s, size: {len(cache_df) if cache_df is not None else 0}")

ticker = "AACG"
ticker_cache = cache_df[(cache_df['ticker'] == ticker) & (cache_df['pmh_gap_pct'] >= 20.0)]
print(f"Gap days in cache for {ticker}: {len(ticker_cache)}")

needed_partitions = set()
for timestamp in ticker_cache['timestamp']:
    dt = pd.to_datetime(timestamp)
    needed_partitions.add((dt.year, dt.month))
    next_day = dt + pd.Timedelta(days=5)
    needed_partitions.add((next_day.year, next_day.month))

print("Needed partitions:", needed_partitions)

clauses = []
for y, m in needed_partitions:
    clauses.append(f"(year = {y} AND month = {m})")
partition_filter = " OR ".join(clauses)

con = get_db_connection()

print("2. Running daily_metrics query...")
t0 = time.time()
query = f"""
    SELECT * FROM daily_metrics 
    WHERE ticker = ? 
      AND ({partition_filter})
    ORDER BY timestamp ASC
"""
df = con.execute(query, [ticker]).fetchdf()
print(f"Finished daily_metrics query in {time.time() - t0:.2f}s, rows: {len(df)}")

if df.empty:
    print("DataFrame is empty!")
    sys.exit(0)

# Ensure chronologically sorted
if 'timestamp' in df.columns:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)

gap_indices = df[df['pmh_gap_pct'] >= 20.0].index.tolist() if 'pmh_gap_pct' in df.columns else []
print(f"Gap indices in df: {gap_indices}")

offset = 0
target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
sub_df = df.loc[target_indices].copy()
target_dates = pd.to_datetime(sub_df['timestamp']).dt.strftime('%Y-%m-%d').tolist()
print(f"Target dates for offset {offset}: {target_dates}")

print("3. Querying compute_price_change_chart...")
t0 = time.time()
from app.routers.ticker_analysis import compute_price_change_chart
chart_data = compute_price_change_chart(ticker, target_dates)
print(f"Finished compute_price_change_chart in {time.time() - t0:.2f}s, chart points: {len(chart_data)}")
