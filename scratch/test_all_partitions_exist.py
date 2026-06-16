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

needed_partitions = {(2024, 4), (2025, 3), (2024, 7), (2022, 3), (2026, 2), (2024, 3), (2023, 12), (2025, 8), (2024, 1)}
bucket = "strategybuilderbbdd"

print("Checking which daily_metrics paths exist:")
valid_dm = []
for y, m in needed_partitions:
    path = f"gs://{bucket}/cold_storage/daily_metrics/year={y}/month={m}/*.parquet"
    try:
        con.execute(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()
        print(f"  {path} -> EXISTS")
        valid_dm.append(path)
    except Exception as e:
        print(f"  {path} -> MISSING or ERROR: {e}")

print("\nChecking which intraday_1m paths exist:")
valid_intra = []
for y, m in needed_partitions:
    path = f"gs://{bucket}/cold_storage/intraday_1m/year={y}/month={m}/*.parquet"
    try:
        con.execute(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()
        print(f"  {path} -> EXISTS")
        valid_intra.append(path)
    except Exception as e:
        print(f"  {path} -> MISSING or ERROR: {e}")

con.close()
