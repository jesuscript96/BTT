import sys
import os
import time
import json
import pandas as pd
from uuid import uuid4
from datetime import datetime

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import get_db_connection
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy

def run_benchmark():
    print("=== STARTING PRODUCTION BENCHMARK ===")
    start_total = time.time()
    
    # 1. Connectivity
    t_conn = time.time()
    try:
        con = get_db_connection()
        print(f"✓ DB Connection: {time.time() - t_conn:.4f}s")
    except Exception as e:
        print(f"✗ DB Connection Failed: {e}")
        return

    # 2. Strategy Fetch (Simulate fetching all strategies)
    t_strat = time.time()
    strategies = []
    try:
        rows = con.execute("SELECT definition FROM strategies LIMIT 5").fetchall()
        for row in rows:
            strategies.append(Strategy(**json.loads(row[0])))
        print(f"✓ Strategy Fetch ({len(strategies)}): {time.time() - t_strat:.4f}s")
    except Exception as e:
        print(f"✗ Strategy Fetch Failed: {e}")
        return

    if not strategies:
        print("⚠ No strategies found. Creating dummy strategy.")
        # Create a dummy strategy if none exist
        # (Skipping for now, assuming DB has data as per previous checks)
        return

    # 3. Market Data Fetch (Real Query)
    # Fetching 3 months of data for a common ticker like 'AAPL' or 'TSLA' or just generic
    print("\nAttempting to fetch large market dataset (simulating 50k rows)...")
    t_fetch = time.time()
    try:
        # Fetching ~50k rows. 
        # Assuming we have data. If not, we fetch everything for a specific ticker.
        # Let's try to fetch all data for 'SPY' or just LIMIT 50000
        query = "SELECT * FROM historical_data ORDER BY timestamp DESC LIMIT 50000"
        market_data = con.execute(query).fetch_df()
        
        duration_fetch = time.time() - t_fetch
        rows = len(market_data)
        print(f"✓ Market Data Fetch ({rows} rows): {duration_fetch:.4f}s")
        print(f"  - Speed: {rows / duration_fetch:.0f} rows/s")
        
        if rows == 0:
            print("⚠ No market data found. Cannot benchmark engine.")
            return
            
    except Exception as e:
        print(f"✗ Market Data Fetch Failed: {e}")
        return

    # 4. Engine Execution
    print("\nRunning Backtest Engine...")
    t_engine = time.time()
    try:
        # Mock weights
        weights = {s.id: 100/len(strategies) for s in strategies}
        
        engine = BacktestEngine(
            strategies=strategies,
            weights=weights,
            market_data=market_data,
            commission_per_trade=1.0,
            initial_capital=100000
        )
        result = engine.run()
        duration_engine = time.time() - t_engine
        print(f"✓ Engine Execution: {duration_engine:.4f}s")
        print(f"  - Throughput: {rows / duration_engine:.0f} bars/s")
        print(f"  - Trades Generated: {result.total_trades}")
        print(f"  - Equity Curve Points: {len(result.equity_curve)}")
        
    except Exception as e:
        print(f"✗ Engine Execution Failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 5. Serialization & Save (Simulating overhead)
    print("\nSimulating Result Saving...")
    t_save = time.time()
    try:
        # Serialize to JSON (Standard Pydantic/JSON dump)
        json_str = json.dumps(result.trades, default=str)
        json_len_mb = len(json_str) / 1024 / 1024
        print(f"✓ JSON Serialization ({len(result.trades)} trades): {time.time() - t_save:.4f}s")
        print(f"  - Trades Payload Size: {json_len_mb:.2f} MB")
        
        # Simulate Insert
        # con.execute("INSERT ...") # Skipped to avoid cluttering DB
        print(f"✓ Save Simulation Complete")
        
    except Exception as e:
        print(f"✗ Save Failed: {e}")

    total_time = time.time() - start_total
    print(f"\n=== TOTAL TIME: {total_time:.4f}s ===")

if __name__ == "__main__":
    run_benchmark()
