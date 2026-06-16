"""
Debug script: test "High/Low of last X days" indicator logic.
Run from BTT/backend: python ../scratch/debug_lookback.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

from app.database import get_db_connection
from app.init_db import init_db
import pandas as pd

# Initialize views
init_db()

con = get_db_connection()

# 1. Check if daily_metrics table/view is accessible
print("\n=== Step 1: Check daily_metrics accessibility ===")
try:
    result = con.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()
    print(f"daily_metrics total rows: {result[0]}")
except Exception as e:
    print(f"ERROR accessing daily_metrics: {e}")

# 2. Check if we can get rth_high and rth_low columns
print("\n=== Step 2: Check rth_high/rth_low columns ===")
try:
    cols = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'daily_metrics'").fetchdf()
    print(f"Columns available: {cols['column_name'].tolist()}")
except Exception as e:
    print(f"ERROR getting columns: {e}")
    # Try alternative
    try:
        sample = con.execute("SELECT * FROM daily_metrics LIMIT 1").fetchdf()
        print(f"Columns from sample: {sample.columns.tolist()}")
    except Exception as e2:
        print(f"ERROR getting sample: {e2}")

# 3. Test the actual query used in indicators.py
print("\n=== Step 3: Test the query used in indicators.py ===")
ticker = "AAPL"
try:
    df_daily = con.execute(f"""
        SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
        FROM daily_metrics 
        WHERE ticker = '{ticker}' 
        ORDER BY "timestamp"
    """).fetchdf()
    print(f"Rows for {ticker}: {len(df_daily)}")
    if not df_daily.empty:
        df_daily["date"] = pd.to_datetime(df_daily["date"]).dt.strftime("%Y-%m-%d")
        df_daily = df_daily.set_index("date")
        print(f"Date range: {df_daily.index[0]} to {df_daily.index[-1]}")
        print(f"Sample:\n{df_daily.head()}")
        
        # Try lookback for a known date
        target = df_daily.index[-10] if len(df_daily) > 10 else df_daily.index[-1]
        lookback = 5
        pos = df_daily.index.get_loc(target)
        start_pos = max(0, pos - lookback)
        high_val = df_daily["rth_high"].iloc[start_pos:pos].max()
        low_val = df_daily["rth_low"].iloc[start_pos:pos].min()
        print(f"\nLookback test: target_date={target}, lookback={lookback}")
        print(f"  pos={pos}, start_pos={start_pos}")
        print(f"  High of last {lookback} days = {high_val}")
        print(f"  Low of last {lookback} days = {low_val}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# 4. Test with how daily_stats is actually passed (simulating backtest flow)
print("\n=== Step 4: Simulate how the indicator gets called ===")
try:
    # Get a qualifying row to see what daily_stats looks like
    sample_qual = con.execute("""
        SELECT *, CAST("timestamp" AS DATE) AS date 
        FROM daily_metrics 
        WHERE ticker = 'AAPL' 
        LIMIT 1
    """).fetchdf()
    
    if not sample_qual.empty:
        sample_qual["date"] = pd.to_datetime(sample_qual["date"]).dt.strftime("%Y-%m-%d")
        daily_stats_sim = sample_qual.iloc[0].to_dict()
        
        print(f"daily_stats keys: {list(daily_stats_sim.keys())}")
        print(f"  ticker: {daily_stats_sim.get('ticker')}")
        print(f"  date: {daily_stats_sim.get('date')}")
        print(f"  timestamp: {daily_stats_sim.get('timestamp')}")
        
        # Now test compute_indicator
        from app.services.indicators import compute_indicator, _ticker_daily_ohlc_cache
        
        # Create a mock intraday df
        mock_df = pd.DataFrame({
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1000] * 10,
            "timestamp": pd.date_range("2024-01-15 09:30", periods=10, freq="1min"),
        })
        
        result_high = compute_indicator(
            "High of last X days",
            mock_df,
            days_lookback=5,
            daily_stats=daily_stats_sim,
        )
        print(f"\nHigh of last 5 days result: {result_high.iloc[0]}")
        print(f"Cache state: {list(_ticker_daily_ohlc_cache.keys())}")
        
        result_low = compute_indicator(
            "Low of last X days",
            mock_df,
            days_lookback=5,
            daily_stats=daily_stats_sim,
        )
        print(f"Low of last 5 days result: {result_low.iloc[0]}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Done ===")
