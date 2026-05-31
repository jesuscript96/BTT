import os
import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Connect in-memory to avoid locking users.duckdb
print("Connecting to in-memory DuckDB and configuring GCS credentials...")
con = duckdb.connect(':memory:')
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"SET s3_access_key_id='{access_key}';")
con.execute(f"SET s3_secret_access_key='{secret}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_url_style='path';")

# Create view locally in-memory
print("Creating in-memory daily_metrics view over GCS...")
con.execute("""
    CREATE OR REPLACE VIEW daily_metrics AS 
    SELECT * EXCLUDE (pmh_gap_pct), 
           ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
    FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
""")

print("Querying daily_metrics with gap_pct >= 5.0...")
df = con.execute("""
    SELECT *
    FROM daily_metrics
    WHERE gap_pct >= 5.0
    AND gap_pct <= 500.0
    AND open > 0.10
""").fetchdf()

print(f"Query completed. Rows fetched: {len(df):,}")

# Optimize types
for col in df.select_dtypes(include=['float64']).columns:
    df[col] = df[col].astype('float32')
df['ticker'] = df['ticker'].astype('category')

local_path = "hot_cache_daily_gaps.parquet"
df.to_parquet(local_path, index=False)
print(f"Saved local parquet file: {local_path}")

print("Uploading to GCS...")
from google.cloud import storage
key_file = os.getenv("GCS_KEY_FILE", "gcs-key.json")
bucket_name = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
client = storage.Client.from_service_account_json(key_file)
bucket = client.bucket(bucket_name)
blob = bucket.blob("cold_storage/hot_cache/daily_metrics_gaps.parquet")
blob.upload_from_filename(local_path)
print(f"Uploaded to gs://{bucket_name}/cold_storage/hot_cache/daily_metrics_gaps.parquet")
os.remove(local_path)
print("Done")
con.close()
