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

# Get schema of daily_metrics
query = f"""
    DESCRIBE SELECT * FROM read_parquet('gs://{bucket}/cold_storage/daily_metrics/**/*.parquet', hive_partitioning=true) LIMIT 0
"""
try:
    df = con.execute(query).fetchdf()
    print("Columns in daily_metrics:")
    print(df['column_name'].tolist())
except Exception as e:
    print(f"Error: {e}")

con.close()
