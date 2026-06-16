import os
import time
import duckdb
from dotenv import load_dotenv

load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

con = duckdb.connect(':memory:')
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"SET s3_access_key_id='{access_key}';")
con.execute(f"SET s3_secret_access_key='{secret}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_url_style='path';")

bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

print("1. Testing query with general wildcard + partition filters...")
t0 = time.time()
try:
    res = con.execute(f"""
        SELECT COUNT(*) 
        FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE year = 2026 AND month = 5 AND gap_pct >= 5.0
    """).fetchone()
    print(f"Result: {res[0]} rows, Time taken: {time.time() - t0:.2f}s")
except Exception as e:
    print("Error:", e)

print("\n2. Testing query with target partition wildcard...")
t0 = time.time()
try:
    res = con.execute(f"""
        SELECT COUNT(*) 
        FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/year=2026/month=5/*.parquet', hive_partitioning=true)
        WHERE gap_pct >= 5.0
    """).fetchone()
    print(f"Result: {res[0]} rows, Time taken: {time.time() - t0:.2f}s")
except Exception as e:
    print("Error:", e)

con.close()
