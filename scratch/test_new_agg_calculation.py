import os
import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv('backend/.env')

target_date = "2026-02-11"
# Let's get tickers that qualified for the screener on this date
# To simulate, let's look at tickers in daily_metrics with gap_pct >= 20 on this date

try:
    con = duckdb.connect()
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE OR REPLACE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
        
    # Get tickers
    tickers_res = con.execute("""
        SELECT ticker FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE CAST(timestamp AS DATE) = CAST(? AS DATE) AND gap_pct >= 20.0
    """, [target_date]).fetchall()
    tickers = [t[0] for t in tickers_res]
    print(f"Qualified tickers on {target_date}: {tickers}")
    
    if not tickers:
        print("No tickers found")
        exit(0)
        
    placeholders = ','.join(['?'] * len(tickers))
    
    # 1. Old Query (using daily_metrics open and prev_close in denominator)
    old_query = f"""
        WITH daily_opens AS (
             SELECT ticker, open as day_open, prev_close as close_4am
             FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
             WHERE DATE_TRUNC('day', timestamp) = CAST(? AS DATE)
             AND ticker IN ({placeholders})
        ),
        joined_intraday AS (
            SELECT 
                i.timestamp, i.ticker, i.close, d.day_open, d.close_4am,
                ((i.close - d.day_open) / NULLIF(d.day_open, 0) * 100) as pct_change
            FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true) i
            JOIN daily_opens d ON i.ticker = d.ticker
            WHERE i.date = CAST(? AS DATE)
            AND i.ticker IN ({placeholders})
            AND d.close_4am > 0
        )
        SELECT 
            strftime(timestamp, '%H:%M') as minute,
            AVG(pct_change) as avg_change
        FROM joined_intraday
        WHERE minute >= '09:30' AND minute <= '16:00'
        GROUP BY 1 ORDER BY 1 LIMIT 5
    """
    
    params = [target_date] + tickers + [target_date] + tickers
    old_res = con.execute(old_query, params).fetchdf()
    print("\n--- Old Query Results (first 5 minutes RTH) ---")
    print(old_res)
    
    # 2. New Query (using intraday RTH open as day_open, and dividing by day_open)
    new_query = f"""
        WITH daily_opens AS (
            SELECT ticker, close as day_open
            FROM (
                SELECT ticker, close, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY timestamp ASC) as rn
                FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)
                WHERE date = CAST(? AS DATE)
                AND timestamp >= CAST(? || ' 09:30:00' AS TIMESTAMP)
                AND ticker IN ({placeholders})
            )
            WHERE rn = 1
        ),
        joined_intraday AS (
            SELECT 
                i.timestamp, i.ticker, i.close, d.day_open,
                ((i.close - d.day_open) / NULLIF(d.day_open, 0) * 100) as pct_change
            FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true) i
            JOIN daily_opens d ON i.ticker = d.ticker
            WHERE i.date = CAST(? AS DATE)
            AND i.ticker IN ({placeholders})
        )
        SELECT 
            strftime(timestamp, '%H:%M') as minute,
            AVG(pct_change) as avg_change,
            QUANTILE_CONT(pct_change, 0.5) as median_change
        FROM joined_intraday
        WHERE minute >= '09:30' AND minute <= '16:00'
        GROUP BY 1 ORDER BY 1 LIMIT 5
    """
    
    new_params = [target_date, target_date] + tickers + [target_date] + tickers
    new_res = con.execute(new_query, new_params).fetchdf()
    print("\n--- New Query Results (first 5 minutes RTH) ---")
    print(new_res)
    
    # Check the last RTH minute
    last_query = new_query.replace("LIMIT 5", "DESC LIMIT 1")
    last_res = con.execute(new_query.replace("LIMIT 5", ""), new_params).fetchdf()
    print("\n--- New Query Results (last RTH minute) ---")
    print(last_res.tail(1))
    
    con.close()
except Exception as e:
    print("Error:", e)
