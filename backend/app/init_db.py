from app.database import get_db_connection

def init_db():
    """Create strategies and saved_queries tables if they do not exist."""
    cur = get_db_connection()
    print("Checking and creating tables in massive...")
    
    # 1. Ensure market data views exist (mapping to massive shared db)
    try:
        cur.execute("CREATE VIEW IF NOT EXISTS daily_metrics AS SELECT * FROM massive.main.daily_metrics")
        cur.execute("CREATE VIEW IF NOT EXISTS intraday_1m AS SELECT * FROM massive.main.intraday_1m")
        cur.execute("CREATE VIEW IF NOT EXISTS tickers AS SELECT * FROM massive.main.tickers")
        cur.execute("CREATE VIEW IF NOT EXISTS splits AS SELECT * FROM massive.main.splits")
        print("✅ Market data views initialized")
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
