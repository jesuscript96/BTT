"""
Debug script: test High/Low of last X days within actual backtest flow
Simulates the EXACT scenario: streaming intraday + indicator lookback on same connection
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

from app.database import get_db_connection
from app.init_db import init_db
import pandas as pd
import numpy as np
import time

init_db()

con = get_db_connection()

# 1. Get one qualifying row to simulate
print("\n=== Simulating backtest scenario ===")
qual = con.execute("""
    SELECT *, CAST("timestamp" AS DATE) AS date 
    FROM daily_metrics 
    WHERE ticker = 'AAPL' AND gap_pct >= 10
    ORDER BY "timestamp" 
    LIMIT 5
""").fetchdf()

if qual.empty:
    print("No qualifying rows found, trying with lower gap threshold...")
    qual = con.execute("""
        SELECT *, CAST("timestamp" AS DATE) AS date 
        FROM daily_metrics 
        WHERE ticker = 'AAPL' 
        ORDER BY "timestamp" 
        LIMIT 5
    """).fetchdf()

qual["date"] = pd.to_datetime(qual["date"]).dt.strftime("%Y-%m-%d")
print(f"Got {len(qual)} qualifying rows")

# 2. Now simulate what happens when we start an intraday stream AND THEN try lookback
print("\n=== Testing concurrent query scenario ===")

# Start a streaming query (like the intraday stream)
try:
    # This simulates the streaming iterator the backtest uses
    streaming_result = con.execute("""
        SELECT * FROM intraday_1m 
        WHERE ticker = 'AAPL' AND CAST("timestamp" AS DATE) = '2022-01-20'
        ORDER BY "timestamp"
        LIMIT 100
    """)
    
    # Fetch SOME rows from the stream (don't exhaust it)
    first_batch = streaming_result.fetchdf()
    print(f"Streaming query returned {len(first_batch)} rows")
    
    if not first_batch.empty:
        # NOW try the lookback query on the SAME connection
        print("Attempting lookback query on same connection...")
        try:
            df_daily = con.execute(f"""
                SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
                FROM daily_metrics 
                WHERE ticker = 'AAPL' 
                ORDER BY "timestamp"
            """).fetchdf()
            print(f"Lookback query succeeded: {len(df_daily)} rows")
        except Exception as e:
            print(f"LOOKBACK QUERY FAILED: {e}")
            import traceback
            traceback.print_exc()
    
except Exception as e:
    print(f"Streaming query failed: {e}")
    import traceback
    traceback.print_exc()

# 3. Test the actual compute_indicator with real intraday data
print("\n=== Testing compute_indicator with real intraday data ===")

from app.services.indicators import compute_indicator, _ticker_daily_ohlc_cache

# Clear cache to force re-query
_ticker_daily_ohlc_cache.clear()

daily_stats_dict = qual.iloc[0].to_dict()
target_date = daily_stats_dict["date"]
ticker = daily_stats_dict["ticker"]
print(f"Testing for ticker={ticker}, date={target_date}")

# Get real intraday data for this date
try:
    intraday = con.execute(f"""
        SELECT * FROM intraday_1m 
        WHERE ticker = '{ticker}' 
          AND CAST("timestamp" AS DATE) = '{target_date}'
        ORDER BY "timestamp"
    """).fetchdf()
    
    if intraday.empty:
        print(f"No intraday data for {ticker} on {target_date}")
    else:
        print(f"Got {len(intraday)} intraday bars")
        
        t0 = time.time()
        result = compute_indicator(
            "High of last X days",
            intraday,
            days_lookback=5,
            daily_stats=daily_stats_dict,
        )
        t1 = time.time()
        
        val = result.iloc[0]
        print(f"High of last 5 days = {val} (took {t1-t0:.2f}s)")
        print(f"Is NaN? {np.isnan(val) if isinstance(val, float) else pd.isna(val)}")
        
        # Test what the comparator would see
        close_series = intraday["close"].astype(float)
        print(f"Close range: {close_series.min():.2f} - {close_series.max():.2f}")
        
        # Check if crossing could be detected
        if not (np.isnan(val) if isinstance(val, float) else pd.isna(val)):
            crosses_above = (close_series.shift(1) <= val) & (close_series > val)
            crosses_below = (close_series.shift(1) >= val) & (close_series < val)
            print(f"Crosses above: {crosses_above.sum()}")
            print(f"Crosses below: {crosses_below.sum()}")
            print(f"Close > High_X: {(close_series > val).sum()}")
            print(f"Close < High_X: {(close_series < val).sum()}")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# 4. Performance test - how long does the GCS query take for a new ticker?
print("\n=== Performance test for new ticker lookback ===")
_ticker_daily_ohlc_cache.clear()

for test_ticker in ["TSLA", "NVDA"]:
    t0 = time.time()
    try:
        df_daily = con.execute(f"""
            SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
            FROM daily_metrics 
            WHERE ticker = '{test_ticker}' 
            ORDER BY "timestamp"
        """).fetchdf()
        t1 = time.time()
        print(f"{test_ticker}: {len(df_daily)} rows in {t1-t0:.2f}s")
    except Exception as e:
        print(f"{test_ticker} FAILED: {e}")

print("\n=== Done ===")
