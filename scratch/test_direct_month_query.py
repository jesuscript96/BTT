import os
import sys
import time
import duckdb
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"CREATE SECRET gcs_sec (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

print("Querying direct path year=2024, month=03 for AACG...")
t0 = time.time()
try:
    df = con.execute("""
        SELECT timestamp, open, close, high, low, volume, CAST(date AS VARCHAR) as date_str
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2024/month=3/*.parquet', hive_partitioning=true)
        WHERE ticker = 'AACG' AND date = DATE '2024-03-27'
        ORDER BY timestamp ASC
    """).fetchdf()
    print(f"Success! Time taken: {time.time() - t0:.2f}s, rows: {len(df)}")
    if not df.empty:
        print(df.head(2))
except Exception as e:
    print("Error:", e)

con.close()
