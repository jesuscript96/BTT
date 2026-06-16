import os
import duckdb
from dotenv import load_dotenv

# Load env variables from backend/.env
load_dotenv('backend/.env')

ticker = "KIDZ"

try:
    # Connect in-memory (writable, no file locks)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false;")
    
    # Configure GCS credentials
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE OR REPLACE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
        print("GCS HMAC credentials configured.")
    
    # Query daily_metrics on GCS directly
    print("--- Querying all daily_metrics rows for KIDZ (Direct GCS parquet scan) ---")
    query_gcs = """
        SELECT timestamp, open, close, gap_pct FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE ticker = ? ORDER BY timestamp ASC
    """
    df = con.execute(query_gcs, [ticker]).fetchdf()
    print("Total rows:", len(df))
    df_gaps = df[df['gap_pct'] >= 20.0]
    print(f"Gaps >= 20% in GCS daily_metrics ({len(df_gaps)}):")
    for idx, row in df_gaps.iterrows():
        print(f"  {row['timestamp']} | Gap: {row['gap_pct']:.2f}% | Open: {row['open']} | Close: {row['close']}")
        
    # Check the hot cache parquet file directly
    print("\n--- Querying GCS hot cache parquet directly ---")
    bucket = os.getenv("GCS_BUCKET", "strategybuilderbbdd")
    path = f"gs://{bucket}/cold_storage/hot_cache/daily_metrics_gaps.parquet"
    df_cache = con.execute(f"SELECT ticker, timestamp, gap_pct FROM read_parquet('{path}') WHERE ticker = ?", [ticker]).fetchdf()
    print("Total rows in hot cache for KIDZ:", len(df_cache))
    df_cache_gaps = df_cache[df_cache['gap_pct'] >= 20.0]
    print(f"Gaps >= 20% in hot cache ({len(df_cache_gaps)}):")
    for idx, row in df_cache_gaps.iterrows():
        print(f"  {row['timestamp']} | Gap: {row['gap_pct']:.2f}%")
        
    con.close()
except Exception as e:
    print("Error:", e)
