import sys
import numpy as np
import pandas as pd

# Add backend directory to path
backend_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend"
sys.path.insert(0, backend_path)

from app.services.indicators import compute_indicator

def run_test():
    print("Generating synthetic multi-day intraday data...")
    # 2 days of 1-minute bars (9:30 to 16:00 is 390 minutes)
    # Day 1: 9:30 to 16:00
    # Day 2: 9:30 to 16:00
    rth_minutes = 390
    
    # Day 1 timestamps
    t1 = pd.date_range("2026-06-05 09:30:00", periods=rth_minutes, freq="1min")
    # Day 2 timestamps
    t2 = pd.date_range("2026-06-08 09:30:00", periods=rth_minutes, freq="1min")
    
    timestamps = t1.append(t2)
    n = len(timestamps)
    
    highs = np.zeros(n)
    lows = np.zeros(n)
    closes = np.zeros(n)
    opens = np.zeros(n)
    volumes = np.ones(n) * 1000
    
    # Day 1:
    # First 30 minutes (0 to 29):
    # High will be 100.0, Low will be 95.0
    for i in range(rth_minutes):
        highs[i] = 98.0
        lows[i] = 96.0
    # Specific highs and lows in the first 30 mins (0 to 29)
    highs[10] = 100.0
    lows[15] = 95.0
    # Rest of the day: Highs range between 95 and 99, except one breakout at index 50 (high = 101)
    highs[50] = 101.0
    closes[50] = 101.0
    
    # Day 2:
    # First 30 minutes (390 to 419):
    # High will be 200.0, Low will be 195.0
    for i in range(rth_minutes, n):
        highs[i] = 198.0
        lows[i] = 196.0
    highs[390 + 10] = 200.0
    lows[390 + 15] = 195.0
    # Rest of Day 2: breakout at index 390 + 100
    highs[390 + 100] = 202.0
    closes[390 + 100] = 202.0

    for i in range(n):
        if closes[i] == 0.0:
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
    
    print("\n--- COMPUTE OPENING RANGE + (30 mins) ---")
    or_plus = compute_indicator(
        name="Opening Range +",
        df=df,
        orb_minutes=30
    )
    
    print("\nChecking Day 1:")
    print(f"Value during ORB (t=10): {or_plus.iloc[10]}")
    print(f"Value after ORB completed (t=30): {or_plus.iloc[30]}")
    print(f"Value at breakout (t=50): {or_plus.iloc[50]}")
    print(f"Value at end of Day 1 (t=389): {or_plus.iloc[389]}")
    
    print("\nChecking Day 2:")
    print(f"Value during ORB (t=390 + 10): {or_plus.iloc[390 + 10]}")
    print(f"Value after ORB completed (t=390 + 30): {or_plus.iloc[390 + 30]}")
    print(f"Value at breakout (t=390 + 100): {or_plus.iloc[390 + 100]}")
    print(f"Value at end of Day 2 (t=n-1): {or_plus.iloc[-1]}")
    
    assert np.isnan(or_plus.iloc[10]), "Day 1 ORB should be NaN during first 30 mins"
    assert or_plus.iloc[30] == 100.0, f"Day 1 ORB high should be 100.0, got {or_plus.iloc[30]}"
    assert or_plus.iloc[50] == 100.0, "Day 1 ORB high should remain constant after completion"
    
    assert np.isnan(or_plus.iloc[390 + 10]), "Day 2 ORB should be NaN during first 30 mins"
    assert or_plus.iloc[390 + 30] == 200.0, f"Day 2 ORB high should be 200.0, got {or_plus.iloc[390 + 30]}"
    assert or_plus.iloc[390 + 100] == 200.0, "Day 2 ORB high should remain constant after completion"
    
    print("\n--- COMPUTE OPENING RANGE - (30 mins) ---")
    or_minus = compute_indicator(
        name="Opening Range -",
        df=df,
        orb_minutes=30
    )
    
    print(f"Day 1 Low value after ORB completed: {or_minus.iloc[30]}")
    print(f"Day 2 Low value after ORB completed: {or_minus.iloc[390 + 30]}")
    
    assert or_minus.iloc[30] == 95.0, f"Day 1 ORB low should be 95.0, got {or_minus.iloc[30]}"
    assert or_minus.iloc[390 + 30] == 195.0, f"Day 2 ORB low should be 195.0, got {or_minus.iloc[390 + 30]}"
    
    print("\nALL TESTS PASSED!")

if __name__ == "__main__":
    run_test()
