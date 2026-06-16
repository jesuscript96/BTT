import sys
import os
import pandas as pd

sys.path.append(os.path.abspath('backend'))
from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.database import get_db_connection

# Get connection
conn = get_db_connection()

# Query first few rows of intraday data for a random ticker and date
try:
    # Let's see what tickers/dates are available in users.duckdb or daily_metrics
    # Since users.duckdb is locked, let's check daily_metrics in GCS
    print("Querying GCS daily_metrics for some ticker...")
    res = conn.execute("""
        SELECT ticker, "timestamp", pm_volume, rth_volume
        FROM read_parquet(
            'gs://strategybuilderbbdd/cold_storage/daily_metrics/year=2026/month=1/*.parquet',
            hive_partitioning=true
        ) LIMIT 5
    """).fetchdf()
    print(res)
    
    if not res.empty:
        ticker = 'HEPS'
        date_str = '2026-01-16'
        year = int(date_str[:4])
        month = int(date_str[5:7])
        
        print(f"\nQuerying intraday data for ticker={ticker}, date={date_str}...")
        path = f"gs://strategybuilderbbdd/cold_storage/intraday_1m_optimized/year={year}/month={month}/*.parquet"
        
        # Check if optimized exists
        try:
            cnt = conn.execute(f"SELECT count(*) FROM glob('{path}')").fetchall()[0][0]
            if cnt == 0:
                path = f"gs://strategybuilderbbdd/cold_storage/intraday_1m/year={year}/month={month}/*.parquet"
        except:
            path = f"gs://strategybuilderbbdd/cold_storage/intraday_1m/year={year}/month={month}/*.parquet"
            
        intraday = conn.execute(f"""
            SELECT "timestamp", volume, close
            FROM read_parquet('{path}', hive_partitioning=true)
            WHERE ticker = '{ticker}' AND date = DATE '{date_str}'
            ORDER BY "timestamp"
        """).fetchdf()
        
        print(f"Total bars found: {len(intraday)}")
        if not intraday.empty:
            print("First 10 bars:")
            print(intraday.head(10))
            print("Last 10 bars:")
            print(intraday.tail(10))
            print("Sum of volume:", intraday['volume'].sum())
except Exception as e:
    print("Error:", e)
