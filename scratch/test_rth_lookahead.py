import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.schemas.strategy import Strategy, ConditionGroup, PriceLevelDistanceCondition, IndicatorConfig, IndicatorType
from app.services.strategy_engine import translate_strategy

# Create a mock df representing 1 day of intraday data (9:20 to 10:20, 5m interval)
# PM is before 09:30. RTH starts at 09:30.
# We set PM Low to 10.0 (lows at index 0..2 are 10.0).
# In RTH (index 3..12):
# - 09:30: close=10.0, low=10.0
# - 09:35: close=9.5,  low=9.5
# - 09:40: close=9.0,  low=9.0
# - 09:45: close=7.5,  low=7.5  <-- Here the price drops to 7.5 (which is 25% below PM Low of 10.0)
# - 09:50: close=8.0,  low=8.0
# - ...
timestamps = pd.date_range(start='2025-03-03 09:20:00', periods=13, freq='5min')
df = pd.DataFrame({
    'timestamp': timestamps,
    'open':  [10.0, 10.0, 10.0, 10.0, 9.8,  9.5,  9.0,  8.0,  8.2,  8.5,  8.7,  9.0,  9.2],
    'high':  [10.2, 10.2, 10.2, 10.1, 9.9,  9.6,  9.2,  8.1,  8.4,  8.7,  8.9,  9.2,  9.4],
    'low':   [10.0, 10.0, 10.0, 10.0, 9.5,  9.0,  7.5,  7.8,  8.0,  8.3,  8.5,  8.8,  9.0],
    'close': [10.1, 10.1, 10.1, 10.0, 9.6,  9.1,  7.8,  8.0,  8.3,  8.6,  8.8,  9.1,  9.3],
    'volume': [1000] * 13,
    'ticker': ['AAPL'] * 13,
    'date': ['2025-03-03'] * 13
})

# Let's check:
# PM Low (04:00 - 09:30): Index 0 (09:20) and Index 1 (09:25) are premarket.
# PM Low is min(10.0, 10.0) = 10.0.
# RTH Low (09:30 - 16:00): Index 2 to 12.
# RTH Low is min(lows[2:]) = 7.5.

# Scenario 1: Using 'RTH Low' as Source (Lookahead Bias!)
# We want RTH Low to be below PM Low by > 20%
strat_rth_low = {
    "name": "Using RTH Low",
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "price_level_distance",
                    "source": {"name": "RTH Low", "offset": 0},
                    "level": {"name": "PM Low", "offset": 0},
                    "comparator": "DISTANCE_GT",
                    "value_pct": 20.0,
                    "position": "below",
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
    "risk_management": {"use_hard_stop": False, "use_take_profit": False}
}

# Scenario 2: Using 'Low Bar' as Source (Real-time evaluation, NO Lookahead!)
# We want the current bar's Low to be below PM Low by > 20%
strat_low_bar = {
    "name": "Using Low Bar",
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "price_level_distance",
                    "source": {"name": "Low Bar", "offset": 0},
                    "level": {"name": "PM Low", "offset": 0},
                    "comparator": "DISTANCE_GT",
                    "value_pct": 20.0,
                    "position": "below",
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
    "risk_management": {"use_hard_stop": False, "use_take_profit": False}
}

print("=== Running Scenario 1 (Source = RTH Low) ===")
res1 = translate_strategy(df, strat_rth_low, daily_stats={})
for t, sig, low, close in zip(df['timestamp'], res1['entries'], df['low'], df['close']):
    # Only print starting from RTH (09:30)
    if t.time() >= pd.Timestamp('09:30:00').time():
        print(f"Time: {t.strftime('%H:%M')} | Low: {low:.2f} | Close: {close:.2f} | Entry Signal: {sig}")

print("\n=== Running Scenario 2 (Source = Low Bar) ===")
res2 = translate_strategy(df, strat_low_bar, daily_stats={})
for t, sig, low, close in zip(df['timestamp'], res2['entries'], df['low'], df['close']):
    if t.time() >= pd.Timestamp('09:30:00').time():
        print(f"Time: {t.strftime('%H:%M')} | Low: {low:.2f} | Close: {close:.2f} | Entry Signal: {sig}")
