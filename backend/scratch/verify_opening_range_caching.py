import sys
import numpy as np
import pandas as pd
import os

# Add backend directory to path
backend_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend"
sys.path.insert(0, backend_path)

from app.services.indicators import compute_indicator

def run_test():
    print("Generating synthetic multi-day intraday data...")
    rth_minutes = 390
    
    # Day 1 timestamps (9:30 to 16:00)
    t1 = pd.date_range("2026-06-05 09:30:00", periods=rth_minutes, freq="1min")
    
    timestamps = t1
    n = len(timestamps)
    
    highs = np.zeros(n)
    lows = np.zeros(n)
    closes = np.zeros(n)
    opens = np.zeros(n)
    volumes = np.ones(n) * 1000
    
    # Day 1:
    # Set base prices
    for i in range(rth_minutes):
        highs[i] = 100.0
        lows[i] = 90.0
        
    # We want different lows at 15 minutes and 30 minutes:
    # 0 to 14: minimum low is at index 5 (let's say 85.0)
    # 15 to 29: minimum low is at index 20 (let's say 80.0)
    lows[5] = 85.0
    lows[20] = 80.0
    
    for i in range(n):
        closes[i] = (highs[i] + lows[i]) / 2.0
        opens[i] = (highs[i] + lows[i]) / 2.0

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })

    print(f"Total rows in df: {len(df)}")
    
    # Shared cache dict (representing the backtest cache)
    test_cache = {}
    
    # 1. Compute 15-minute Opening Range -
    or_minus_15 = compute_indicator(
        name="Opening Range -",
        df=df,
        orb_minutes=15,
        cache=test_cache
    )
    
    # 2. Compute 30-minute Opening Range - (using the same cache)
    or_minus_30 = compute_indicator(
        name="Opening Range -",
        df=df,
        orb_minutes=30,
        cache=test_cache
    )
    
    print("\nChecking 15-minute Opening Range -:")
    print(f"Value during ORB (t=10): {or_minus_15.iloc[10]}")
    print(f"Value after ORB completed (t=20): {or_minus_15.iloc[20]}")
    print(f"Value at end of Day 1 (t=389): {or_minus_15.iloc[389]}")
    
    print("\nChecking 30-minute Opening Range -:")
    print(f"Value during ORB (t=20): {or_minus_30.iloc[20]}")
    print(f"Value after ORB completed (t=40): {or_minus_30.iloc[40]}")
    print(f"Value at end of Day 1 (t=389): {or_minus_30.iloc[389]}")
    
    # Assertions for 15-minute Opening Range -
    assert np.isnan(or_minus_15.iloc[10]), "15-minute ORB should be NaN during first 15 mins"
    # Low of first 15 mins should be 85.0 (since lows[5] = 85.0 is the minimum)
    assert or_minus_15.iloc[15] == 85.0, f"15-minute ORB low should be 85.0, got {or_minus_15.iloc[15]}"
    assert or_minus_15.iloc[20] == 85.0, f"15-minute ORB low should remain 85.0 after 15 mins, got {or_minus_15.iloc[20]}"
    
    # Assertions for 30-minute Opening Range -
    assert np.isnan(or_minus_30.iloc[20]), "30-minute ORB should be NaN during first 30 mins"
    # Low of first 30 mins should be 80.0 (since lows[20] = 80.0 is lower than lows[5] = 85.0)
    assert or_minus_30.iloc[30] == 80.0, f"30-minute ORB low should be 80.0, got {or_minus_30.iloc[30]}"
    
    # Make sure they are not identical series!
    assert not or_minus_15.equals(or_minus_30), "ERROR: Cache collision! 15-min and 30-min series are identical."
    
    print("\nALL CACHING AND PARAMETER TESTS PASSED!")

if __name__ == "__main__":
    run_test()
