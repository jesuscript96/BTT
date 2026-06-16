import os
import sys
import duckdb
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"CREATE SECRET gcs_sec (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

print("Checking structure of daily_metrics on GCS...")
try:
    res = con.execute("""
        SELECT DISTINCT year, month, input_file_name() 
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        LIMIT 5
    """).fetchall()
    print("Found:")
    for r in res:
        print(r)
except Exception as e:
    print("Error:", e)

con.close()
