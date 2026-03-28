from app.database import get_db_connection

def init_db():
    """Create strategies and saved_queries tables if they do not exist."""
    cur = get_db_connection()
    print("Checking and creating tables in massive...")
    
    # 1. Ensure market data views exist (mapping to massive shared db or GCS)
    try:
        import os
        provider = os.getenv("DB_PROVIDER", "motherduck").lower()
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
                    print(f"⚠️ Warning attaching massive: {e}")
            
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
            
            print("✅ Optimized GCS views initialized (non-recursive globs)")
        else:
            cur.execute("CREATE VIEW IF NOT EXISTS daily_metrics AS SELECT * FROM massive.main.daily_metrics")
            cur.execute("CREATE VIEW IF NOT EXISTS intraday_1m AS SELECT * FROM massive.main.intraday_1m")
            cur.execute("CREATE VIEW IF NOT EXISTS tickers AS SELECT * FROM massive.main.tickers")
            cur.execute("CREATE VIEW IF NOT EXISTS splits AS SELECT * FROM massive.main.splits")
            print("✅ Market data views initialized from MotherDuck")
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize market data views: {e}")

    # 2. Create user tables in the default writeable database
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            filters JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            description VARCHAR,
            definition JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dataset_pairs (
            dataset_id VARCHAR,
            ticker VARCHAR,
            date DATE,
            PRIMARY KEY (dataset_id, ticker, date)
        )
    """)

    # backtest_results table
    cur.execute("""
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

    print("✅ Local database tables initialized")
    
    tables = cur.execute("SHOW TABLES").fetchall()
    print(f"Current tables in massive: {[t[0] for t in tables]}")

if __name__ == "__main__":
    init_db()
