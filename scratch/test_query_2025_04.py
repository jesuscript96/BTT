import os
import sys
import time
import pandas as pd

os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from dotenv import load_dotenv
load_dotenv(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\.env')

print("GCS_HMAC_KEY:", os.getenv("GCS_HMAC_KEY"))
print("GCS_HMAC_SECRET:", os.getenv("GCS_HMAC_SECRET")[:10] + "..." if os.getenv("GCS_HMAC_SECRET") else "None")

from app.db.connection import get_connection
from app.db.gcs_cache import _select_intraday_glob_for_month, _tickers_sql_in_clause, _intraday_date_predicate_from_qualifying_dates, _hive_partition_year_month_sql

conn = get_connection()
y, m = 2025, 4
path = "gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/year=2025/month=4/*.parquet"

# We test with 5 sample tickers
tickers = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
ticker_filter = f"i.ticker IN ({_tickers_sql_in_clause(tickers)})"
date_filter = "1=1"
hive_f = _hive_partition_year_month_sql("i", y, m)

sql = f"""
SELECT i.ticker, i.date, i."timestamp",
       i.open, i.high, i.low, i."close", i.volume
FROM read_parquet('{path}', hive_partitioning=true) i
WHERE {ticker_filter} AND {date_filter} AND {hive_f}
LIMIT 100
"""

print("Running test SQL on GCS...")
t0 = time.time()
try:
    df = conn.execute(sql).fetchdf()
    print(f"Success! Rows fetched: {len(df)}")
    print(df.head())
except Exception as e:
    print(f"Error: {e}")
print(f"Time taken: {round(time.time() - t0, 2)}s")

conn.close()
