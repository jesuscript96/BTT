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
path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"

print(f"Reading direct parquet from {path}...")
try:
    info = con.execute(f"""
        SELECT 
            MIN(gap_pct) as min_gap, 
            MAX(gap_pct) as max_gap, 
            COUNT(*) as total_rows,
            COUNT(CASE WHEN gap_pct >= 5.0 THEN 1 END) as rows_ge_5,
            COUNT(CASE WHEN gap_pct >= 10.0 THEN 1 END) as rows_ge_10
        FROM read_parquet('{path}')
    """).fetchone()
    print("Min Gap:", info[0])
    print("Max Gap:", info[1])
    print("Total Rows:", info[2])
    print("Rows >= 5.0:", info[3])
    print("Rows >= 10.0:", info[4])
except Exception as e:
    print("Error:", e)
con.close()
