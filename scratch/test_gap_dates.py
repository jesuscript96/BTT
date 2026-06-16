import pandas as pd
import duckdb
from app.database import get_db_connection
from app.services.cache_service import get_hot_daily_cache

ticker = "KIDZ"

print("--- Querying all daily_metrics rows for KIDZ from DuckDB ---")
con = get_db_connection()
df_db = con.execute("SELECT timestamp, open, close, gap_pct FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetchdf()
print("Total rows in DB:", len(df_db))
db_gaps = df_db[df_db['gap_pct'] >= 20.0]
print("Gaps >= 20% in DB:")
for idx, row in db_gaps.iterrows():
    print(f"  {row['timestamp']} | Gap: {row['gap_pct']:.2f}% | Open: {row['open']} | Close: {row['close']}")

print("\n--- Querying Hot Daily Cache for KIDZ ---")
cache_df = get_hot_daily_cache()
if cache_df is not None and not cache_df.empty:
    cache_gaps = cache_df[(cache_df['ticker'] == ticker) & (cache_df['gap_pct'] >= 20.0)]
    print(f"Gaps >= 20% in Cache (Total: {len(cache_gaps)}):")
    for idx, row in cache_gaps.iterrows():
        print(f"  {row['timestamp']} | Gap: {row['gap_pct']:.2f}%")
else:
    print("Cache is empty or None")
