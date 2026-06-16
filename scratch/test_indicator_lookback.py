import sys
import os
sys.path.append(os.path.abspath('backend'))

from app.database import get_db_connection
from app.init_db import init_db
import pandas as pd
import numpy as np

# Initialize GCS/Motherduck views
init_db()

_ticker_daily_ohlc_cache = {}

def get_lookback_value(ticker, target_date_str, lookback, mode):
    global _ticker_daily_ohlc_cache
    if ticker not in _ticker_daily_ohlc_cache:
        con = get_db_connection()
        try:
            df_daily = con.execute(f"""
                SELECT CAST("timestamp" AS DATE) as date, rth_high, rth_low 
                FROM daily_metrics 
                WHERE ticker = '{ticker}' 
                ORDER BY "timestamp"
            """).fetchdf()
            df_daily["date"] = pd.to_datetime(df_daily["date"]).dt.strftime("%Y-%m-%d")
            df_daily = df_daily.set_index("date")
            _ticker_daily_ohlc_cache[ticker] = df_daily
            print(f"Loaded {len(df_daily)} rows for {ticker}")
        except Exception as e:
            print(f"Error loading daily metrics: {e}")
            _ticker_daily_ohlc_cache[ticker] = pd.DataFrame(columns=["rth_high", "rth_low"])
            
    df_daily = _ticker_daily_ohlc_cache[ticker]
    if df_daily.empty or target_date_str not in df_daily.index:
        print(f"Date {target_date_str} not in index")
        return np.nan
        
    pos = df_daily.index.get_loc(target_date_str)
    start_pos = max(0, pos - lookback)
    
    if start_pos >= pos:
        print("Not enough history")
        return np.nan
        
    slice_data = df_daily["rth_high" if mode == "high" else "rth_low"].iloc[start_pos:pos]
    print(f"Slice from {df_daily.index[start_pos]} to {df_daily.index[pos-1]}:")
    print(slice_data)
    
    val = slice_data.max() if mode == "high" else slice_data.min()
    return val

# Test GFAI
ticker = 'GFAI'
target_date = '2022-03-10'
lookback = 5

print("--- Test HIGH ---")
max_val = get_lookback_value(ticker, target_date, lookback, "high")
print("Lookback Max:", max_val)

print("\n--- Test LOW ---")
min_val = get_lookback_value(ticker, target_date, lookback, "low")
print("Lookback Min:", min_val)
