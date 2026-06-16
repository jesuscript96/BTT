import os
import sys
sys.path.append('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend')

os.environ["DB_PROVIDER"] = "gcs"
os.environ["DISABLE_GCS_SYNC"] = "true"

from app.services.cache_service import get_hot_daily_cache
from app.database import get_db_connection

cache_df = get_hot_daily_cache()
ticker = "KIDZ"

print("--- HOT CACHE ROWS FOR KIDZ ---")
if cache_df is not None and not cache_df.empty:
    kidz_rows = cache_df[cache_df['ticker'] == ticker]
    print(f"Total rows in hot cache for KIDZ: {len(kidz_rows)}")
    for idx, r in kidz_rows.iterrows():
        print(f"  Date: {r['timestamp'].strftime('%Y-%m-%d')}, Gap: {r['gap_pct']:.2f}%, Open: {r['open']:.2f}")
    
    kidz_gaps_20 = kidz_rows[kidz_rows['gap_pct'] >= 20.0]
    print(f"\nNumber of gaps >= 20% in hot cache: {len(kidz_gaps_20)}")
    for idx, r in kidz_gaps_20.iterrows():
        print(f"  Date: {r['timestamp'].strftime('%Y-%m-%d')}, Gap: {r['gap_pct']:.2f}%")
else:
    print("Hot cache is empty.")

print("\n--- RAW DATABASE ROWS FOR KIDZ ---")
try:
    con = get_db_connection()
    db_df = con.execute("SELECT timestamp, open, prev_close, gap_pct FROM daily_metrics WHERE ticker = ? ORDER BY timestamp ASC", [ticker]).fetchdf()
    print(f"Total raw daily_metrics rows in database: {len(db_df)}")
    if not db_df.empty:
        db_gaps_20 = db_df[db_df['gap_pct'] >= 20.0]
        print(f"Total raw gaps >= 20% in database: {len(db_gaps_20)}")
        for idx, r in db_gaps_20.iterrows():
            print(f"  Date: {str(r['timestamp'])[:10]}, Gap: {r['gap_pct']:.2f}%")
except Exception as e:
    print("Database error:", e)
