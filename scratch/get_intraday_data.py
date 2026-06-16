import os
import duckdb
from dotenv import load_dotenv
import pandas as pd

env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
access_key = os.getenv("GCS_HMAC_KEY")
secret = os.getenv("GCS_HMAC_SECRET")
con.execute(f"CREATE SECRET gcs_sec (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")

# daily_metrics view
con.execute("""
    CREATE OR REPLACE VIEW daily_metrics AS 
    SELECT * EXCLUDE (pmh_gap_pct), 
           gap_pct AS gap_at_open_pct,
           ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
    FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
""")

# Let's search for gap days in 2024
tickers_with_gaps = con.execute("""
    SELECT ticker, CAST(timestamp AS DATE) as date, pmh_gap_pct, year, month
    FROM daily_metrics 
    WHERE pmh_gap_pct >= 20.0 AND year >= 2024
    LIMIT 20
""").fetchdf()
print(tickers_with_gaps)

if not tickers_with_gaps.empty:
    for idx, row in tickers_with_gaps.iterrows():
        target_ticker = row['ticker']
        target_date = row['date']
        year = row['year']
        month = row['month']
        print(f"Trying ticker={target_ticker} date={target_date} year={year} month={month}...")
        try:
            query = f"""
                SELECT timestamp, open, close, high, low, volume 
                FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/year={year}/month={month:02d}/*.parquet', hive_partitioning=true)
                WHERE ticker = '{target_ticker}' 
                  AND CAST(timestamp AS DATE) = DATE '{target_date.strftime("%Y-%m-%d")}'
                ORDER BY timestamp ASC
            """
            intraday_df = con.execute(query).fetchdf()
            if not intraday_df.empty:
                print(f"SUCCESS! Found {len(intraday_df)} rows of intraday data")
                print(intraday_df.head(5))
                break
        except Exception as e:
            print(f"Failed: {e}")
else:
    print("No tickers with gaps in 2024+ found.")
con.close()
