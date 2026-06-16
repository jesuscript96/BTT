import os
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
path = f"gs://{bucket}/cold_storage/daily_metrics/*/*/*.parquet"

print(f"Counting total daily_metrics rows from {path}...")
try:
    info = con.execute(f"""
        SELECT COUNT(*), MIN(gap_pct), MAX(gap_pct)
        FROM read_parquet('{path}', hive_partitioning=true)
    """).fetchone()
    print("Total rows in daily_metrics on GCS:", info[0])
    print("Min Gap:", info[1])
    print("Max Gap:", info[2])
except Exception as e:
    print("Error:", e)
con.close()
