import duckdb
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')

GCS_ACCESS_KEY_ID = os.getenv("GCS_HMAC_KEY", "")
GCS_SECRET_ACCESS_KEY = os.getenv("GCS_HMAC_SECRET", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "strategybuilderbbdd")

conn = duckdb.connect(":memory:")
conn.execute("INSTALL httpfs; LOAD httpfs;")
conn.execute(f"SET s3_access_key_id='{GCS_ACCESS_KEY_ID}';")
conn.execute(f"SET s3_secret_access_key='{GCS_SECRET_ACCESS_KEY}';")
conn.execute("SET s3_endpoint='storage.googleapis.com';")
conn.execute("SET s3_region='us-east-1';")
conn.execute("SET s3_url_style='path';")

path = f"gs://{GCS_BUCKET}/cold_storage/daily_metrics/*/*/*.parquet"

try:
    cols = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}', hive_partitioning=true) LIMIT 0").fetchall()
    print("Columns in GCS daily_metrics:")
    for c in cols:
        print(f"  {c[0]}: {c[1]}")
except Exception as e:
    print(f"Error: {e}")

conn.close()
