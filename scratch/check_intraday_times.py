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
    
    # Query unique hours in intraday_1m
    query = """
        SELECT DISTINCT strftime(timestamp, '%H') as hour
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)
        LIMIT 100
    """
    res = con.execute(query).fetchall()
    print("Unique hours in GCS intraday_1m database:", sorted([r[0] for r in res if r[0]]))
    
    con.close()
except Exception as e:
    print("Error:", e)
