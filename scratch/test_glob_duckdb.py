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

print("Globbing missing path...")
try:
    res = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=4/*.parquet')").fetchall()
    print("Success! Glob result size:", len(res))
except Exception as e:
    print("Error during glob:", e)

print("Globbing existing path...")
try:
    res = con.execute("SELECT * FROM glob('gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2024/month=3/*.parquet')").fetchall()
    print("Success! Glob result size:", len(res))
except Exception as e:
    print("Error during glob:", e)

con.close()
