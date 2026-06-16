import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.schemas.strategy import Strategy, ConditionGroup, PriceLevelDistanceCondition, IndicatorConfig, IndicatorType
from app.services.strategy_engine import translate_strategy
from app.backtester.engine import BacktestEngine

# Create a mock df representing 1 day of intraday data
# 09:00 to 10:00 (5m interval)
# Premarket is 09:00 to 09:30
# RTH is 09:30 to 10:00
timestamps = pd.date_range(start='2025-03-03 09:00:00', periods=13, freq='5min')
df = pd.DataFrame({
    'timestamp': timestamps,
    'open':  [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
    'high':  [10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2, 11.3, 11.4],
    'low':   [9.0,  9.1,  9.2,  9.3,  9.4,  9.5,  9.6,  9.7,  9.8,  9.9,  10.0, 10.1, 10.2], # PM low is 9.0 (at 09:00)
    'close': [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2, 11.3],
    'volume': [1000] * 13,
    'ticker': ['AAPL'] * 13,
    'date': ['2025-03-03'] * 13
})

# Let's override RTH lows to have a minimum low of 7.0
# Indices 7 to 12 are RTH (starts at 09:30, which is index 6)
# Let's set index 8 (09:40) low to 7.0 (RTH Low = 7.0)
df.loc[8, 'low'] = 7.0

# PM Low (04:00 - 09:30): indices 0 to 5 are PM.
# Lows are: 9.0, 9.1, 9.2, 9.3, 9.4, 9.5. Minimum PM Low is 9.0.
# RTH Low (09:30 - 16:00): indices 6 to 12 are RTH.
# Lows are: 9.6, 9.7, 7.0, 9.9, 10.0, 10.1, 10.2. Minimum RTH Low is 7.0.
# PM Low = 9.0
# 20% of PM Low = 1.8. 20% below PM Low is 9.0 - 1.8 = 7.2.
# So RTH Low (7.0) is below 7.2.
# Distance pct = abs(7.0 - 9.0) / 9.0 * 100 = 2 / 9 * 100 = 22.22%.
# If the distance condition is set to:
# source: RTH Low, level: PM Low, comparator: DISTANCE_GT, value_pct: 20, position: below.
# Distance (22.22%) > 20% and RTH Low (7.0) < PM Low (9.0) -> should be True!

strat_dict = {
    "name": "Test RTH Low vs PM Low Distance",
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "price_level_distance",
                    "source": {
                        "name": "RTH Low",
                        "offset": 0
                    },
                    "level": {
                        "name": "PM Low",
                        "offset": 0
                    },
                    "comparator": "DISTANCE_GT",
                    "value_pct": 20.0,
                    "position": "below",
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": []
        }
    },
    "risk_management": {
        "use_hard_stop": False,
        "use_take_profit": False,
        "take_profit_mode": "Full",
        "accept_reentries": True,
        "hard_stop": {"type": "Percentage", "value": 2.0},
        "take_profit": {"type": "Percentage", "value": 6.0}
    }
}

print("=== Running Strategy Engine (Non-JIT) ===")
res = translate_strategy(df, strat_dict, daily_stats={})
print("Entries series:")
print(res['entries'])

print("\n=== Running Backtest Engine (JIT) ===")
strategy = Strategy(**strat_dict)
engine = BacktestEngine(
    strategies=[strategy],
    weights={strategy.id: 1.0},
    market_data=df
)
jit_entries = engine.generate_boolean_signals("entry")
print("JIT Entries:")
print(jit_entries)
