import duckdb
import os
from threading import Lock

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backtester.duckdb')

# Global connection and lock for thread safety
_con = None
_lock = Lock()

def _establish_connection():
    """Helper to create a connection with correct MotherDuck settings."""
    token = os.getenv("MOTHERDUCK_TOKEN")
    if token:
        # Step 1: Ensure btt database exists
        print("Ensuring MotherDuck 'btt' database exists...")
        temp_con = duckdb.connect(f"md:?motherduck_token={token}")
        temp_con.execute("CREATE DATABASE IF NOT EXISTS btt")
        temp_con.close()
        
        # Step 2: Connect directly to btt
        print("Connecting to MotherDuck catalog: btt")
        con = duckdb.connect(f"md:btt?motherduck_token={token}")
        con.execute("SET search_path = 'main'")
        return con
    else:
        print(f"Connecting to local DuckDB at {DB_PATH}...")
        return duckdb.connect(DB_PATH, read_only=False)

def get_db_connection(read_only=False):
    """
    Returns a DuckDB connection or cursor.
    Supports local DuckDB or MotherDuck (Cloud) if MOTHERDUCK_TOKEN is set.
    """
    global _con
    with _lock:
        if _con is None:
            _con = _establish_connection()
        return _con.cursor()

def init_db():
    """
    Initialize the database with necessary tables.
    """
    print("Database Initialization Started")
    # We use a separate connection for init to avoid interference with the global _con
    con = _establish_connection()
    
    # Tickers table
    con.execute("""
        CREATE TABLE IF NOT EXISTS tickers (
            ticker VARCHAR PRIMARY KEY,
            name VARCHAR,
            active BOOLEAN DEFAULT TRUE,
            last_updated TIMESTAMP
        )
    """)
    
    # Historical Data Table (1m OHLCV)
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
            PRIMARY KEY (ticker, timestamp)
        )
    """)

    # Daily Metrics Table (Aggregated from 1m bars)
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
            pm_high DOUBLE,
            pm_volume DOUBLE,
            high_spike_pct DOUBLE,
            low_spike_pct DOUBLE,
            pmh_fade_to_open_pct DOUBLE,
            rth_fade_to_close_pct DOUBLE,
            open_lt_vwap BOOLEAN,
            pm_high_break BOOLEAN,
            m15_return_pct DOUBLE,
            m30_return_pct DOUBLE,
            m60_return_pct DOUBLE,
            close_lt_m15 BOOLEAN,
            close_lt_m30 BOOLEAN,
            close_lt_m60 BOOLEAN,
            hod_time VARCHAR,
            lod_time VARCHAR,
            close_direction VARCHAR,
            PRIMARY KEY (ticker, date)
        )
    """)
    
    con.close()
    print("Database initialization completed.")
