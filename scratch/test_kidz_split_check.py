import os
import duckdb
from dotenv import load_dotenv

load_dotenv('backend/.env')

ticker = "KIDZ"
date = "2026-02-11"

try:
    con = duckdb.connect()
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE OR REPLACE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
    
    # Query daily_metrics open
    open_val = con.execute("""
        SELECT open, prev_close 
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE ticker = ? AND CAST(timestamp AS DATE) = CAST(? AS DATE)
    """, [ticker, date]).fetchone()
    print("daily_metrics values for KIDZ on 2026-02-11:", open_val)
    
    # Query intraday_1m closes
    intra_vals = con.execute("""
        SELECT timestamp, close 
        FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)
        WHERE ticker = ? AND date = CAST(? AS DATE)
        ORDER BY timestamp ASC
        LIMIT 10
    """, [ticker, date]).fetchall()
    print("First 10 intraday_1m close values:")
    for row in intra_vals:
        print(f"  {row[0]} | Close: {row[1]}")
        
    con.close()
except Exception as e:
    print("Error:", e)
