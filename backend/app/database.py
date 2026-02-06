import duckdb
import os
from threading import Lock

# Global connection and lock for thread safety
_con = None
_lock = Lock()

def _establish_connection():
    """Establish connection to MotherDuck cloud database."""
    token = os.getenv("MOTHERDUCK_TOKEN")
    
    if not token:
        raise RuntimeError(
            "MOTHERDUCK_TOKEN environment variable is required. "
            "Please set it in your .env file."
        )
    
    # Step 1: Ensure btt database exists
    print("Connecting to MotherDuck...")
    temp_con = duckdb.connect(f"md:?motherduck_token={token}")
    temp_con.execute("CREATE DATABASE IF NOT EXISTS btt")
    temp_con.close()
    
    # Step 2: Connect directly to btt database
    print("Connected to MotherDuck catalog: btt")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    con.execute("SET search_path = 'main'")
    
    # Diagnostic: List tables
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables in btt.main: {[t[0] for t in tables]}")
    
    return con

def get_db_connection(read_only=False):
    """
    Returns a DuckDB connection cursor to MotherDuck cloud database.
    """
    global _con
    with _lock:
        if _con is None:
            _con = _establish_connection()
        return _con.cursor()

def init_db():
    """
    Initialize the MotherDuck database with necessary tables.
    """
    print("Database Initialization Started")
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
    
    # Strategies Table (JSON Storage for logic)
    con.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            definition JSON
        )
    """)

    # Backtest Results Table
    con.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id VARCHAR PRIMARY KEY,
            strategy_ids JSON,
            weights JSON,
            dataset_summary VARCHAR,
            commission_per_trade DOUBLE,
            initial_capital DOUBLE,
            final_balance DOUBLE,
            total_trades INTEGER,
            win_rate DOUBLE,
            avg_r_multiple DOUBLE,
            max_drawdown_pct DOUBLE,
            sharpe_ratio DOUBLE,
            profit_factor DOUBLE,
            total_return_pct DOUBLE,
            total_return_r DOUBLE,
            search_mode VARCHAR,
            search_space VARCHAR,
            partials_config JSON,
            trailing_stop_config JSON,
            results_json JSON,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Saved Queries (Datasets) Table
    con.execute("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            filters JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    con.close()
    print("Database initialization completed.")
