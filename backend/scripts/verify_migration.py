
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def get_db_connection():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        raise ValueError("MOTHERDUCK_TOKEN not set")
    print("Connecting to MotherDuck for Verification...")
    return duckdb.connect(f"md:btt?motherduck_token={token}")

def verify_migration():
    con = get_db_connection()
    
    print("\n--- Migration Verification Report ---")
    
    # 1. Row Counts
    print("\n[Row Counts]")
    hist_count = con.execute("SELECT COUNT(*) FROM historical_data").fetchone()[0]
    daily_count = con.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
    ticker_count = con.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    
    print(f"Historical Data (1m): {hist_count:,} rows")
    print(f"Daily Metrics:        {daily_count:,} rows")
    print(f"Unique Tickers:       {ticker_count} tickers")
    
    # 2. Daily Metrics Quality
    print("\n[Daily Metrics Quality]")
    pm_high_count = con.execute("SELECT COUNT(*) FROM daily_metrics WHERE pm_high > 0").fetchone()[0]
    gap_pct_count = con.execute("SELECT COUNT(*) FROM daily_metrics WHERE gap_at_open_pct != 0").fetchone()[0]
    
    print(f"Days with PM High > 0:   {pm_high_count:,} ({pm_high_count/daily_count:.1%} if >0)")
    print(f"Days with Gap % != 0:    {gap_pct_count:,} ({gap_pct_count/daily_count:.1%} if >0)")
    
    # 3. Sample Data Check
    print("\n[Sample Data - Ticker: IMPP]")
    sample = con.execute("""
        SELECT date, rth_open, rth_close, pm_high, pm_volume, gap_at_open_pct 
        FROM daily_metrics 
        WHERE ticker = 'IMPP' 
        ORDER BY date DESC 
        LIMIT 5
    """).fetchdf()
    print(sample)
    
    # 4. Logical Consistency Check
    print("\n[Consistency Check]")
    # Check if we have any days where 1m data exists but PM High is 0 (might indicate join failure or no PM trading)
    # This query might be slow on large data, so limit scope or skip if too heavy.
    # A quick check: do we have ANY historical data for a ticker but NO daily metrics?
    orphan_hist = con.execute("""
        SELECT COUNT(DISTINCT ticker) 
        FROM historical_data 
        WHERE ticker NOT IN (SELECT ticker FROM daily_metrics)
    """).fetchone()[0]
    print(f"Orphaned Tickers (in History but not Daily): {orphan_hist}")

    con.close()

if __name__ == "__main__":
    verify_migration()
