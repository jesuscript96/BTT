import sys
import os
import time
import json
import logging
import pandas as pd
from datetime import datetime, timedelta
from uuid import uuid4

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import get_db_connection
from app.backtester.engine import BacktestEngine
from app.schemas.strategy import Strategy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def benchmark_backtest():
    """
    Benchmarks the backtester flow:
    1. Connect to DB
    2. Fetch Data (MotherDuck)
    3. Run Engine (Python)
    4. Save Results
    """
    logger.info("Starting Backtest Benchmark...")

    # 1. Connection
    start_time = time.time()
    try:
        con = get_db_connection()
        logger.info(f"✓ DB Connected in {time.time() - start_time:.2f}s")
    except Exception as e:
        logger.error(f"Failed to connect to DB: {e}")
        return

    # 2. Mock Data Setup (Ensure we have something to query)
    # We will try to use existing data if possible, otherwise rely on what's there.
    # For this benchmark, we'll try to fetch whatever is available for a recent date range.
    
    # Let's try to query 'NVDA' or 'SPY' or just get any available ticker
    # to avoid empty result errors.
    row = con.execute("SELECT DISTINCT ticker FROM historical_data LIMIT 1").fetchone()
    ticker = row[0] if row else "NVDA"
    logger.info(f"Using ticker: {ticker}")

    # 3. Fetch Market Data
    logger.info("Fetching market data (simulating backtest query)...")
    fetch_start = time.time()
    
    # Simulating the query from backtest.py
    # Fetching last 30 days of 1-minute data for the ticker
    query = """
        SELECT * 
        FROM historical_data 
        WHERE ticker = ? 
        ORDER BY timestamp ASC
        LIMIT 50000 
    """
    
    try:
        market_data = con.execute(query, (ticker,)).fetch_df()
        fetch_time = time.time() - fetch_start
        rows = len(market_data)
        logger.info(f"✓ Market Data Fetched in {fetch_time:.2f}s")
        logger.info(f"  - Rows: {rows}")
        logger.info(f"  - Throughput: {rows / fetch_time if fetch_time > 0 else 0:.0f} rows/s")
        
        if market_data.empty:
            logger.warning("No market data found! Cannot benchmark engine.")
            return

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return

    # 4. Mock Strategy
    strategy_mock = Strategy(
        name="Benchmark Strategy",
        filters={"require_shortable": True, "exclude_dilution": True},
        entry_logic=[], # Empty logic = no trades, but engine still loops
        exit_logic={
            "stop_loss_type": "Percent", 
            "stop_loss_value": 1.0, 
            "take_profit_type": "Percent", 
            "take_profit_value": 2.0
        }
    )
    
    # 5. Run Engine
    logger.info("Running Backtest Engine...")
    engine_start = time.time()
    
    engine = BacktestEngine(
        strategies=[strategy_mock],
        weights={strategy_mock.id: 100},
        market_data=market_data,
        commission_per_trade=1.0,
        initial_capital=100000
    )
    
    result = engine.run()
    
    engine_time = time.time() - engine_start
    logger.info(f"✓ Engine Execution in {engine_time:.2f}s")
    logger.info(f"  - Speed: {rows / engine_time if engine_time > 0 else 0:.0f} bars/s")

    # 6. Summary
    logger.info("=" * 30)
    logger.info("BENCHMARK RESULTS")
    logger.info("=" * 30)
    logger.info(f"DB Fetch Time:     {fetch_time:.4f}s")
    logger.info(f"Engine Run Time:   {engine_time:.4f}s")
    logger.info(f"Total Rows:        {rows}")
    logger.info("=" * 30)

if __name__ == "__main__":
    benchmark_backtest()
