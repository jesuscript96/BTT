
import duckdb
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

def create_btt_v2():
    token = os.getenv("MOTHERDUCK_TOKEN")
    try:
        print("Connecting to md: ...")
        con = duckdb.connect(f"md:?motherduck_token={token}")
        
        print("Creating btt_v2...")
        con.execute("CREATE DATABASE IF NOT EXISTS btt_v2")
        print("Success! Created btt_v2.")
        
        print("Switching to btt_v2...")
        con.execute("USE btt_v2")
        
        print("Initializing schema in btt_v2...")
        # Re-run init logic manually here to verify
        con.execute("""
            CREATE TABLE IF NOT EXISTS historical_data (
                ticker VARCHAR,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                vwap DOUBLE,
                pm_high DOUBLE,
                pm_volume DOUBLE,
                gap_percent DOUBLE,
                transactions BIGINT,
                pm_high_break BOOLEAN,
                high_spike_pct DOUBLE,
                PRIMARY KEY (ticker, timestamp)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                ticker VARCHAR,
                date DATE,
                rth_open DOUBLE,
                rth_high DOUBLE,
                rth_low DOUBLE,
                rth_close DOUBLE,
                rth_volume DOUBLE,
                gap_at_open_pct DOUBLE,
                rth_run_pct DOUBLE,
                day_return_pct DOUBLE,
                pm_high DOUBLE,
                pm_volume DOUBLE,
                pm_high_break BOOLEAN,
                high_spike_pct DOUBLE,
                PRIMARY KEY (ticker, date)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS tickers (
                ticker VARCHAR PRIMARY KEY,
                name VARCHAR,
                active BOOLEAN DEFAULT TRUE,
                last_updated TIMESTAMP
            )
        """)
        print("Schema initialized in btt_v2.")
        
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    create_btt_v2()
