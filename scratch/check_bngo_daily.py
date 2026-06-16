import os
import duckdb
from dotenv import load_dotenv

# Load env variables from backend/.env
load_dotenv('backend/.env')

access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
if access_key and secret:
    con.execute(f"CREATE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
    print("GCS secret configured.")

query = f"""
    SELECT ticker, timestamp, open, close, high, low, pm_high, pm_low, rth_open, rth_high, rth_low, rth_close, gap_pct, pm_volume, prev_close
    FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/**/*.parquet', hive_partitioning=true)
    WHERE ticker = 'BNGO'
      AND timestamp >= '2025-01-01'
      AND timestamp <= '2025-03-03'
    ORDER BY timestamp DESC
"""
try:
    df = con.execute(query).fetchdf()
    print("Daily metrics for BNGO:")
    print(df.to_string())
except Exception as e:
    print(f"Error querying daily metrics: {e}")

con.close()
