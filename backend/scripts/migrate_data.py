
import duckdb
import os
import glob
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Source Directories
SOURCE_DIRS = [
    "/Users/jvch/Downloads/Small Caps",
    "/Users/jvch/Downloads/Small Caps 2"
]

def get_db_connection():
    """Establish connection to MotherDuck."""
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("MOTHERDUCK_TOKEN not set")
    
    print("Connecting to MotherDuck (btt_v2)...")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    return con

def truncate_tables(con):
    """Wipe existing data."""
    print("Cleaning up existing tables...")
    con.execute("TRUNCATE TABLE historical_data")
    con.execute("TRUNCATE TABLE daily_metrics")
    con.execute("TRUNCATE TABLE tickers")
    print("Tables truncated.")

def load_daily_data(con):
    """Load Daily Parquet files into daily_metrics (Base Layer) using Bulk Load."""
    print("\n--- Loading Daily Data (Base Layer) ---")
    
    for base_dir in SOURCE_DIRS:
        daily_path = os.path.join(base_dir, "Datos diarios")
        if not os.path.exists(daily_path):
            continue
            
        print(f"Bulk loading from {daily_path}/*.parquet...")
        
        # DuckDB can read all parquet files in a folder using a glob pattern directly
        # and filename=True adds the filename column.
        # Filename format: /path/to/AACB.parquet
        # We need to extract 'AACB' from the filename.
        # In SQL, we can use string functions.
        # split_part(filename, '/', -1) gets 'AACB.parquet'
        # replace(..., '.parquet', '') gets 'AACB'
        
        sql = f"""
        INSERT INTO daily_metrics (ticker, date, rth_open, rth_high, rth_low, rth_close, rth_volume)
        SELECT 
            replace(split_part(filename, '/', -1), '.parquet', '') as ticker,
            CAST(timestamp AS DATE) as date,
            open as rth_open,
            high as rth_high,
            low as rth_low,
            close as rth_close,
            volume as rth_volume
        FROM read_parquet('{daily_path}/*.parquet', filename=True)
        """
        con.execute(sql)
        print(f"Loaded files from {daily_path}")
                
    print(f"Finished loading daily files.")

def calculate_daily_derived_metrics(con):
    """Calculate Gaps and Runs on the newly loaded daily data."""
    print("\n--- Calculating Derived Daily Metrics (SQL) ---")
    
    update_sql = """
    WITH calcs AS (
        SELECT 
            ticker, 
            date,
            LAG(rth_close) OVER (PARTITION BY ticker ORDER BY date) as prev_close,
            ((rth_close - rth_open) / rth_open * 100) as calc_run_pct
        FROM daily_metrics
    )
    UPDATE daily_metrics
    SET 
        gap_at_open_pct = CASE 
            WHEN c.prev_close IS NOT NULL AND c.prev_close != 0 
            THEN ((daily_metrics.rth_open - c.prev_close) / c.prev_close * 100) 
            ELSE 0 
        END,
        rth_run_pct = c.calc_run_pct,
        day_return_pct = c.calc_run_pct
    FROM calcs c
    WHERE daily_metrics.ticker = c.ticker AND daily_metrics.date = c.date;
    """
    con.execute(update_sql)
    print("Daily metrics updated.")

def load_intraday_data(con):
    """Load Intraday (1m) Parquet files using Bulk Load."""
    print("\n--- Loading Intraday Data (High Res Layer) ---")
    
    # Create temp table
    con.execute("""
    CREATE OR REPLACE TEMPORARY TABLE raw_1m_import (
        timestamp TIMESTAMP,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume DOUBLE,
        vwap DOUBLE,
        transactions BIGINT,
        ticker VARCHAR
    )
    """)
    
    for base_dir in SOURCE_DIRS:
        intraday_path = os.path.join(base_dir, "Datos intradiarios/Datos descargados/1m")
        if not os.path.exists(intraday_path):
            continue
            
        print(f"Bulk loading from {intraday_path}/*.parquet...")
        
        # Filename format: TICKER_YYYY-MM-DD.parquet (e.g., IMPP_2022-01-28.parquet)
        # We need 'IMPP'. 
        # split_part(filename, '/', -1) -> IMPP_2022-01-28.parquet
        # split_part(..., '_', 1) -> IMPP
        
        sql = f"""
        INSERT INTO raw_1m_import (timestamp, open, high, low, close, volume, vwap, transactions, ticker)
        SELECT 
            timestamp, open, high, low, close, volume, vwap, transactions, 
            split_part(split_part(filename, '/', -1), '_', 1) as ticker
        FROM read_parquet('{intraday_path}/*.parquet', filename=True)
        """
        con.execute(sql)
        print(f"Buffered files from {intraday_path}")
    
    print(f"Flushing to historical_data...")
    con.execute("""
    INSERT INTO historical_data (ticker, timestamp, open, high, low, close, volume, vwap)
    SELECT ticker, timestamp, open, high, low, close, volume, vwap
    FROM raw_1m_import
    """)
    print("Intraday data loaded.")

def enrich_daily_from_intraday(con):
    """Update daily_metrics with PM Highs and other stats from 1m data."""
    print("\n--- Enriching Daily Metrics from Intraday ---")
    
    enrich_sql = """
    WITH intraday_stats AS (
        SELECT 
            ticker, 
            CAST(timestamp AS DATE) as date,
            MAX(CASE WHEN CAST(timestamp AS TIME) < '09:30:00' THEN high ELSE 0 END) as calc_pm_high,
            SUM(CASE WHEN CAST(timestamp AS TIME) < '09:30:00' THEN volume ELSE 0 END) as calc_pm_volume,
            MAX(CASE WHEN CAST(timestamp AS TIME) BETWEEN '09:30:00' AND '09:45:00' THEN high ELSE 0 END) as max_15m_high
        FROM historical_data
        GROUP BY ticker, CAST(timestamp AS DATE)
    )
    UPDATE daily_metrics
    SET 
        pm_high = s.calc_pm_high,
        pm_volume = s.calc_pm_volume,
        pm_high_break = (daily_metrics.rth_high > s.calc_pm_high AND s.calc_pm_high > 0),
        high_spike_pct = CASE 
            WHEN daily_metrics.rth_open > 0 
            THEN ((s.max_15m_high - daily_metrics.rth_open) / daily_metrics.rth_open * 100) 
            ELSE 0 
        END
    FROM intraday_stats s
    WHERE daily_metrics.ticker = s.ticker AND daily_metrics.date = s.date;
    """
    con.execute(enrich_sql)
    print("Daily metrics enriched.")

def populate_tickers(con):
    """Populate tickers table."""
    print("\n--- Populating Tickers Table ---")
    con.execute("""
    INSERT INTO tickers (ticker, name, active, last_updated)
    SELECT DISTINCT ticker, ticker as name, TRUE as active, NOW() as last_updated
    FROM daily_metrics
    ON CONFLICT (ticker) DO UPDATE SET last_updated = NOW();
    """)
    print("Tickers table updated.")

def main():
    start_time = time.time()
    try:
        con = get_db_connection()
        truncate_tables(con)
        load_daily_data(con)
        calculate_daily_derived_metrics(con)
        print(f"Daily Metrics Time: {time.time() - start_time:.2f}s")
        
        load_intraday_data(con)
        print(f"Intraday Load Time: {time.time() - start_time:.2f}s")
        
        enrich_daily_from_intraday(con)
        populate_tickers(con)
        
        con.close()
        elapsed = time.time() - start_time
        print(f"\nMigration completed successfully in {elapsed:.2f} seconds.")
        
    except Exception as e:
        print(f"\n❌ Migration Failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
