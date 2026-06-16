import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

print("--- Checking GCS for any data in April or May 2026 ---")
try:
    con = duckdb.connect(':memory:')
    con.execute("INSTALL httpfs; LOAD httpfs;")
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute(f"SET s3_access_key_id='{access_key}';")
    con.execute(f"SET s3_secret_access_key='{secret}';")
    con.execute("SET s3_endpoint='storage.googleapis.com';")
    con.execute("SET s3_url_style='path';")
    
    # Try querying April
    try:
        max_date_apr = con.execute("""
            SELECT MAX(date) FROM read_parquet(
                'gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=4/*.parquet',
                hive_partitioning=true
            )
        """).fetchone()[0]
        print(f"Max date in April 2026: {max_date_apr}")
    except Exception as e:
        print(f"No data or error checking April: {e}")

    # Try querying May
    try:
        max_date_may = con.execute("""
            SELECT MAX(date) FROM read_parquet(
                'gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2026/month=5/*.parquet',
                hive_partitioning=true
            )
        """).fetchone()[0]
        print(f"Max date in May 2026: {max_date_may}")
    except Exception as e:
        print(f"No data or error checking May: {e}")
except Exception as e:
    print(f"Error: {e}")
