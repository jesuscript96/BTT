import os
import sys
import pandas as pd

# Setup path
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from dotenv import load_dotenv
load_dotenv()

from app.db.gcs_cache import _select_intraday_glob_for_month, _get_cache_hash, LOCAL_CACHE_DIR
import duckdb

print("Current Cwd:", os.getcwd())
print("LOCAL_CACHE_DIR:", LOCAL_CACHE_DIR)
print("Resolved absolute LOCAL_CACHE_DIR:", os.path.abspath(LOCAL_CACHE_DIR))

dataset_id = "ac1ce7e3-0047-436f-b6a9-484463666de9"

con = duckdb.connect('users.duckdb', read_only=True)
try:
    qualifying_df = con.execute(
        "SELECT ticker, CAST(date AS VARCHAR) as date "
        "FROM dataset_pairs WHERE dataset_id = ?",
        [dataset_id],
    ).fetchdf()
finally:
    con.close()

dates_pd = pd.to_datetime(qualifying_df["date"])
ym_pairs = sorted(set(zip(dates_pd.dt.year, dates_pd.dt.month)))

conn = duckdb.connect(":memory:")
conn.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
if access_key and secret:
    conn.execute(f"SET s3_access_key_id='{access_key}';")
    conn.execute(f"SET s3_secret_access_key='{secret}';")
    conn.execute("SET s3_endpoint='storage.googleapis.com';")
    conn.execute("SET s3_url_style='path';")

for y, m in ym_pairs:
    path = _select_intraday_glob_for_month(conn, y, m)
    month_mask = (dates_pd.dt.year == y) & (dates_pd.dt.month == m)
    valid_pairs_month = qualifying_df.loc[month_mask, ["ticker", "date"]].drop_duplicates().copy()
    valid_pairs_month["date"] = pd.to_datetime(valid_pairs_month["date"]).dt.strftime("%Y-%m-%d")
    
    tickers_month = valid_pairs_month["ticker"].unique().tolist()
    valid_dates = valid_pairs_month["date"].unique().tolist()
    
    if path:
        cache_key = _get_cache_hash(y, m, path, tickers_month, valid_dates)
        cache_file = os.path.join(LOCAL_CACHE_DIR, f"{cache_key}.parquet")
        abs_cache_file = os.path.abspath(cache_file)
        exists = os.path.exists(cache_file)
        abs_exists = os.path.exists(abs_cache_file)
        print(f"Month {y}-{m:02d}: File={cache_key}.parquet | exists={exists} | abs_exists={abs_exists} | Path={abs_cache_file}")
    else:
        print(f"Month {y}-{m:02d}: No path resolved")

conn.close()
