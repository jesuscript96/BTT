from app.database import get_db_connection, get_user_db_connection

def init_db():
    """Create strategies and saved_queries tables if they do not exist."""
    import os
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    # 1. Ensure market data views exist (mapping to massive shared db or GCS)
    cur = get_db_connection()
    print(f"Checking and creating tables for DB_PROVIDER={provider}...")
    
    try:
        if provider == "gcs":
            # Clean up old ambiguous schema if it exists in users.duckdb
            try:
                cur.execute("DROP SCHEMA IF EXISTS massive CASCADE;")
            except:
                pass

            # Attaching a virtual database named 'massive' to match hardcoded queries
            try:
                cur.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
            
            # In GCS mode, we create views pointing to the parquet files directly
            # Optimization: Using precise glob patterns to avoid recursive scanning overhead.
            # daily_metrics and intraday_1m are partitioned: year=*/month=*/data.parquet
            cur.execute("CREATE VIEW IF NOT EXISTS massive.daily_metrics AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.intraday_1m AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)")
            
            # tickers and splits are non-partitioned single files or flat directories
            cur.execute("CREATE VIEW IF NOT EXISTS massive.tickers AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/tickers/*.parquet')")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.splits AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/splits/*.parquet')")
            
            # Also create aliases in the main schema (of users.duckdb) for convenience
            cur.execute("CREATE VIEW IF NOT EXISTS daily_metrics AS SELECT * FROM massive.daily_metrics")
            cur.execute("CREATE VIEW IF NOT EXISTS intraday_1m AS SELECT * FROM massive.intraday_1m")
            cur.execute("CREATE VIEW IF NOT EXISTS tickers AS SELECT * FROM massive.tickers")
            cur.execute("CREATE VIEW IF NOT EXISTS splits AS SELECT * FROM massive.splits")
            
            print("[INFO] Optimized GCS views initialized (non-recursive globs)")
        elif provider == "local":
            # Local mode: create local empty tables if not exists, and create massive virtual database views
            # First, drop any existing views in main schema to avoid conflict with local tables and infinite recursion
            for table_name in ["tickers", "splits", "daily_metrics", "intraday_1m"]:
                try:
                    cur.execute(f"DROP VIEW IF EXISTS main.{table_name}")
                except Exception as e:
                    pass
            # 1. Create empty local tables in local_data.duckdb so they exist
            cur.execute("CREATE TABLE IF NOT EXISTS tickers (ticker VARCHAR PRIMARY KEY, name VARCHAR, type VARCHAR)")
            cur.execute("CREATE TABLE IF NOT EXISTS splits (ticker VARCHAR, execution_date DATE, PRIMARY KEY(ticker, execution_date))")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    ticker VARCHAR,
                    timestamp TIMESTAMP,
                    year INTEGER,
                    month INTEGER,
                    gap_pct DOUBLE,
                    open DOUBLE,
                    close DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    volume DOUBLE,
                    pm_volume DOUBLE,
                    pm_high DOUBLE,
                    pm_low DOUBLE,
                    pm_high_time VARCHAR,
                    pm_low_time VARCHAR,
                    rth_volume DOUBLE,
                    rth_open DOUBLE,
                    rth_high DOUBLE,
                    rth_low DOUBLE,
                    rth_close DOUBLE,
                    rth_run_pct DOUBLE,
                    day_return_pct DOUBLE,
                    rth_range_pct DOUBLE,
                    pmh_gap_pct DOUBLE,
                    pmh_fade_pct DOUBLE,
                    rth_fade_pct DOUBLE,
                    hod_time VARCHAR,
                    lod_time VARCHAR,
                    m15_return_pct DOUBLE,
                    m30_return_pct DOUBLE,
                    m60_return_pct DOUBLE,
                    m180_return_pct DOUBLE,
                    close_1559 DOUBLE,
                    last_close DOUBLE,
                    prev_close DOUBLE,
                    eod_volume DOUBLE,
                    transactions DOUBLE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intraday_1m (
                    ticker VARCHAR,
                    date DATE,
                    timestamp TIMESTAMP,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    PRIMARY KEY (ticker, timestamp)
                )
            """)
            
            # 2. Virtualize massive db schema pointing to local tables so hardcoded massive. queries work!
            try:
                cur.execute("DROP SCHEMA IF EXISTS massive CASCADE;")
            except:
                pass
            try:
                cur.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
                    
            cur.execute("CREATE VIEW IF NOT EXISTS massive.tickers AS SELECT * FROM main.tickers")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.splits AS SELECT * FROM main.splits")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.daily_metrics AS SELECT * FROM main.daily_metrics")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.intraday_1m AS SELECT * FROM main.intraday_1m")
            
            # In local mode, we do NOT create aliases in the main schema pointing to massive views,
            # because they are already tables in the main schema.
            print("[INFO] Local market data views virtualized in massive schema")
        else:
            cur.execute("CREATE VIEW IF NOT EXISTS daily_metrics AS SELECT * FROM massive.main.daily_metrics")
            cur.execute("CREATE VIEW IF NOT EXISTS intraday_1m AS SELECT * FROM massive.main.intraday_1m")
            cur.execute("CREATE VIEW IF NOT EXISTS tickers AS SELECT * FROM massive.main.tickers")
            cur.execute("CREATE VIEW IF NOT EXISTS splits AS SELECT * FROM massive.main.splits")
            print("[INFO] Market data views initialized from MotherDuck")
    except Exception as e:
        print(f"[WARN] Warning: Could not initialize market data views: {e}")

    # 2. Create user tables in the default writeable database AND users.duckdb
    db_connections = [get_db_connection(), get_user_db_connection()]
    
    # Remove duplicates if GCS mode where they are the same
    if provider == "gcs":
        db_connections = [db_connections[0]]

    for conn in db_connections:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_queries (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                filters JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                description VARCHAR,
                definition JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS dataset_pairs (
                dataset_id VARCHAR,
                ticker VARCHAR,
                date DATE,
                PRIMARY KEY (dataset_id, ticker, date)
            )
        """)

        # backtest_results table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                id VARCHAR PRIMARY KEY,
                strategy_ids JSON,
                results_json JSON,
                total_trades INTEGER,
                win_rate DOUBLE,
                profit_factor DOUBLE,
                avg_r_multiple DOUBLE,
                total_return_r DOUBLE,
                total_return_pct DOUBLE,
                max_drawdown_pct DOUBLE,
                sharpe_ratio DOUBLE,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_mode VARCHAR,
                search_space VARCHAR
            )
        """)

    print("[INFO] Local database tables initialized across connections")
    
    tables = cur.execute("SHOW TABLES").fetchall()
    print(f"Current tables in massive: {[t[0] for t in tables]}")

    # Seed mock data into users.duckdb when tables are empty (local dev)
    try:
        from app.seed_mock_data import seed_mock_data
        seed_mock_data()
    except Exception as e:
        print(f"[WARN] Could not seed mock data: {e}")

if __name__ == "__main__":
    init_db()

