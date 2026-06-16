import os
import time
import duckdb
from dotenv import load_dotenv

load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

print("Starting simulation with month=1...")
con = duckdb.connect(':memory:')
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"SET s3_access_key_id='{os.getenv('GCS_HMAC_KEY')}';")
con.execute(f"SET s3_secret_access_key='{os.getenv('GCS_HMAC_SECRET')}';")
con.execute("SET s3_endpoint='storage.googleapis.com';")
con.execute("SET s3_region='us-east-1';")
con.execute("SET memory_limit='2GB';")
con.execute("SET threads=4;")
con.execute("SET http_keep_alive=true;")
con.execute("SET http_retries=2;")
con.execute("SET s3_url_style='path';")

path = "gs://strategybuilderbbdd/cold_storage/intraday_1m/year=2024/month=1/*.parquet"
opt_path = "gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/year=2024/month=1/*.parquet"

# Let's count files first to see what exists
try:
    t0 = time.time()
    n_opt = con.execute(f"SELECT count(*) FROM glob('{opt_path}')").fetchall()[0][0]
    print(f"Optimized files count: {n_opt} ({time.time() - t0:.2f}s)")
except Exception as e:
    print(f"Error checking optimized path: {e}")
    n_opt = 0

try:
    t0 = time.time()
    n_raw = con.execute(f"SELECT count(*) FROM glob('{path}')").fetchall()[0][0]
    print(f"Raw files count: {n_raw} ({time.time() - t0:.2f}s)")
except Exception as e:
    print(f"Error checking raw path: {e}")
    n_raw = 0

chosen_path = opt_path if n_opt > 0 else path
print(f"Chosen path: {chosen_path}")

# Load some tickers
tickers = ['VZ', 'PTON', 'XERS', 'ALIT', 'RVSN', 'ICCT', 'EDR']
ticker_filter = "i.ticker IN ('" + "', '".join(tickers) + "')"
hive_f = "CAST(i.year AS INTEGER) = 2024 AND CAST(i.month AS INTEGER) = 1"
date_filter = "CAST(i.date AS DATE) >= DATE '2024-01-01' AND CAST(i.date AS DATE) <= DATE '2024-02-01'"

sql = f"""
SELECT i.ticker, i.date, i."timestamp",
       i.open, i.high, i.low, i."close", i.volume
FROM read_parquet('{chosen_path}', hive_partitioning=true) i
WHERE {ticker_filter} AND {date_filter} AND {hive_f}
"""

print("Running test query on GCS...")
try:
    t0 = time.time()
    res = con.execute(sql).fetchdf()
    print(f"Query completed successfully! Fetched {len(res)} rows in {time.time() - t0:.2f}s")
    print(res.head(5))
except Exception as e:
    print(f"Query failed: {e}")

con.close()
