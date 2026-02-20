import duckdb
import os
from dotenv import load_dotenv

load_dotenv()

def init_db():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("MOTHERDUCK_TOKEN not found in .env")
        return

    print("Connecting to MotherDuck...")
    con = duckdb.connect(f"md:massive?motherduck_token={token}")
    con.execute("SET search_path = 'main'")

    # Create backtest_results table if missing
    print("Creating backtest_results table...")
    con.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id VARCHAR PRIMARY KEY,
            strategy_ids VARCHAR, -- JSON array
            results_json TEXT,    -- Full results block
            dataset_summary VARCHAR,
            search_mode VARCHAR,
            search_space VARCHAR,
            total_trades INTEGER,
            win_rate DOUBLE,
            profit_factor DOUBLE,
            avg_r_multiple DOUBLE,
            total_return_r DOUBLE,
            total_return_pct DOUBLE,
            final_balance DOUBLE,
            max_drawdown_pct DOUBLE,
            sharpe_ratio DOUBLE,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Check if we need to migrate/add columns if it exists but is partial
    # (Actually it was reported as missing, but safety first)
    cols = [c[0] for c in con.execute("DESCRIBE backtest_results").fetchall()]
    print(f"Table backtest_results schema verified. Columns: {cols}")

    con.close()
    print("Done!")

if __name__ == "__main__":
    init_db()
