import os
import duckdb
from dotenv import load_dotenv

load_dotenv('backend/.env')

try:
    con = duckdb.connect()
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE OR REPLACE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
    
    query = """
        SELECT min(timestamp), max(timestamp), count(*) FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE ticker = 'KIDZ'
    """
    res = con.execute(query).fetchone()
    print("KIDZ daily_metrics range on GCS:", res)
    
    con.close()
except Exception as e:
    print("Error:", e)
