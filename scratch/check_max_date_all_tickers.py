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
    
    # Query max timestamp in daily_metrics
    query = """
        SELECT max(timestamp), count(distinct ticker), count(*) 
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
    """
    res = con.execute(query).fetchone()
    print("All daily_metrics on GCS summary:", res)
    
    con.close()
except Exception as e:
    print("Error:", e)
