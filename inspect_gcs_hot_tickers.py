import sys
import os
import time
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"

print(f"Loading hot cache from {path}...")
t0 = time.time()
try:
    df = con.execute(f"SELECT ticker, count(*) as count FROM read_parquet('{path}') GROUP BY ticker ORDER BY count DESC").fetchdf()
    print(f"Loaded hot cache stats: {len(df)} unique tickers in {time.time() - t0:.2f}s")
    print("Top 30 tickers in GCS hot cache by gapper row count:")
    print(df.head(30))
except Exception as e:
    print(f"Error: {e}")

con.close()
