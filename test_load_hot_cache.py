import sys
import os
import time
sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

import duckdb
from app.db.connection import get_connection

con = get_connection()
bucket = os.getenv('GCS_BUCKET', 'strategybuilderbbdd')
path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"

print(f"Loading hot cache from {path}...")
t0 = time.time()
try:
    df = con.execute(f"SELECT * FROM read_parquet('{path}')").fetchdf()
    print(f"Loaded hot cache DataFrame: {len(df)} rows in {time.time() - t0:.2f}s")
    print("Columns:", list(df.columns))
    
    # Let's see if we have AAPL gap days in hot cache
    aapl_gaps = df[df['ticker'] == 'AAPL']
    print(f"AAPL gap days in hot cache: {len(aapl_gaps)}")
    if not aapl_gaps.empty:
        print(aapl_gaps[['timestamp', 'gap_pct', 'pm_high', 'rth_open', 'rth_close']].head(5))
        
except Exception as e:
    print(f"Error: {e}")

con.close()
