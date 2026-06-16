import os
import duckdb
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
print(f"Loading env from {env_path}")
load_dotenv(env_path)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
print(f"Access key: {access_key}")
con.execute(f"CREATE SECRET gcs_sec (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

print("Executing query...")
df = con.execute("SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2024/month=10/*.parquet', hive_partitioning=true) LIMIT 5").fetchdf()
print(df)
print(df.columns)
