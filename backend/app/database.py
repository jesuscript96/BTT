import duckdb
import os
from threading import Lock

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backtester.duckdb')

# Global connection and lock for thread safety
_con = None
_lock = Lock()

def get_db_connection(read_only=False):
    """
    Returns a DuckDB connection or cursor.
    For MVP simplicity in a single-process FastAPI app, we share one master connection.
    """
    global _con
    with _lock:
        if _con is None:
            # We open as read-write because the scheduler needs to write.
            # DuckDB allows concurrent reads from the same connection object.
            _con = duckdb.connect(DB_PATH, read_only=False)
        
        # Return a cursor to allow independent transactions/state if needed
        return _con.cursor()

def init_db():
    """
    Initialize the database with necessary tables.
    """
    # Use a direct connection for initialization
    con = duckdb.connect(DB_PATH)
    
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
    print(f"Database initialized at {DB_PATH}")
