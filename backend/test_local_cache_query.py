from app.database import get_db_connection
import os
import time

con = get_db_connection()
try:
    print("Checking if .cache/intraday/*.parquet can be queried:")
    t0 = time.time()
    row = con.execute("SELECT COUNT(*) FROM read_parquet('.cache/intraday/*.parquet')").fetchone()
    print(f"Total rows in local parquet cache: {row[0]:,} (took {time.time()-t0:.2s}s)")
    
    t0 = time.time()
    ticker_count = con.execute("SELECT COUNT(DISTINCT ticker) FROM read_parquet('.cache/intraday/*.parquet')").fetchone()
    print(f"Distinct tickers in cache: {ticker_count[0]} (took {time.time()-t0:.2s}s)")
except Exception as e:
    print("Error:", e)
