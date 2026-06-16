"""
Debug: Test High/Low of last X days for multiple dates to see if results are consistently NaN
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

from app.database import get_db_connection
from app.init_db import init_db
import pandas as pd
import numpy as np

init_db()
con = get_db_connection()

from app.services.indicators import compute_indicator, _ticker_daily_ohlc_cache

# Clear cache
_ticker_daily_ohlc_cache.clear()

# Get 10 qualifying dates for AAPL spanning the middle of the dataset
qual = con.execute("""
    SELECT *, CAST("timestamp" AS DATE) AS date 
    FROM daily_metrics 
    WHERE ticker = 'AAPL' 
    ORDER BY "timestamp"
    LIMIT 20 OFFSET 100
""").fetchdf()

qual["date"] = pd.to_datetime(qual["date"]).dt.strftime("%Y-%m-%d")

print(f"Testing {len(qual)} dates for AAPL")
print(f"Date range: {qual['date'].iloc[0]} to {qual['date'].iloc[-1]}")

for idx, row in qual.iterrows():
    daily_stats_dict = row.to_dict()
    target_date = daily_stats_dict["date"]
    ticker = daily_stats_dict["ticker"]
    
    # Create mock intraday df
    mock_df = pd.DataFrame({
        "open": [100.0] * 5,
        "high": [101.0] * 5,
        "low": [99.0] * 5,
        "close": [100.5] * 5,
        "volume": [1000] * 5,
        "timestamp": pd.date_range(f"{target_date} 09:30", periods=5, freq="1min"),
    })
    
    result_high = compute_indicator(
        "High of last X days",
        mock_df,
        days_lookback=5,
        daily_stats=daily_stats_dict,
    )
    
    result_low = compute_indicator(
        "Low of last X days",
        mock_df,
        days_lookback=5,
        daily_stats=daily_stats_dict,
    )
    
    h_val = result_high.iloc[0]
    l_val = result_low.iloc[0]
    is_nan_h = np.isnan(h_val) if isinstance(h_val, float) else pd.isna(h_val)
    is_nan_l = np.isnan(l_val) if isinstance(l_val, float) else pd.isna(l_val)
    
    h_str = f"{h_val:.2f}" if not is_nan_h else "NaN"
    l_str = f"{l_val:.2f}" if not is_nan_l else "NaN"
    print(f"  {target_date}: High_5d={h_str}, Low_5d={l_str}, NaN?={is_nan_h}/{is_nan_l}")

print("\n=== Now test with hot cache scenario ===")
# Simulate what hot cache path produces for date
import datetime
_ticker_daily_ohlc_cache.clear()

# Hot cache produces datetime.date objects for date column
qual_hot = qual.copy()
qual_hot["date"] = pd.to_datetime(qual_hot["date"]).dt.date  # datetime.date objects!

row_hot = qual_hot.iloc[10].to_dict()
print(f"Hot cache date type: {type(row_hot['date'])}, value: {row_hot['date']}")

mock_df = pd.DataFrame({
    "open": [100.0] * 5,
    "high": [101.0] * 5,
    "low": [99.0] * 5,
    "close": [100.5] * 5,
    "volume": [1000] * 5,
    "timestamp": pd.date_range(f"2022-06-01 09:30", periods=5, freq="1min"),
})

result = compute_indicator(
    "High of last X days",
    mock_df,
    days_lookback=5,
    daily_stats=row_hot,
)
h_val = result.iloc[0]
is_nan = np.isnan(h_val) if isinstance(h_val, float) else pd.isna(h_val)
print(f"Hot cache result: {h_val}, NaN? {is_nan}")

# Now test what daily_stats["date"] looks like after hot cache
print(f"\nds.get('date'): {row_hot.get('date')}")
print(f"type: {type(row_hot.get('date'))}")
print(f"str(date): {str(row_hot.get('date'))}")

# Check if the date string matches the cache index
target_str = str(row_hot.get("date"))
print(f"target_date_str = '{target_str}'")
if "AAPL" in _ticker_daily_ohlc_cache:
    cache_df = _ticker_daily_ohlc_cache["AAPL"]
    print(f"Cache index sample: {cache_df.index[:3].tolist()}")
    print(f"Target in cache index? {target_str in cache_df.index}")

print("\n=== Done ===")
