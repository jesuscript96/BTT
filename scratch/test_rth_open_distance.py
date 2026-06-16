import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.schemas.strategy import Strategy, ConditionGroup, PriceLevelDistanceCondition, IndicatorConfig, IndicatorType, Comparator
from app.backtester.engine import BacktestEngine
from app.services.strategy_engine import translate_strategy

# Create a mock df representing 1 day of intraday data (9:30 to 10:00)
timestamps = pd.date_range(start='2025-03-03 09:30:00', periods=6, freq='5min')
df = pd.DataFrame({
    'timestamp': timestamps,
    'open':  [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
    'high':  [101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
    'low':   [99.0,  100.0, 101.0, 102.0, 103.0, 104.0],
    'close': [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
    'volume': [1000] * 6,
    'ticker': ['AAPL'] * 6,
    'date': ['2025-03-03'] * 6
})

# Let's inspect VWAP:
# Typical prices:
# 09:30: (101+99+100.5)/3 = 100.166. Vol = 1000. CumVal = 100166. CumVol = 1000. VWAP = 100.166.
# 09:35: (102+100+101.5)/3 = 101.166. Vol = 1000. CumVal = 100166 + 101166 = 201333. CumVol = 2000. VWAP = 100.666.
# 09:40: (103+101+102.5)/3 = 102.166. Vol = 1000. CumVal = 201333 + 102166 = 303500. CumVol = 3000. VWAP = 101.166.

# Let's inspect RTH Open:
# First open in RTH (at 09:30) is 100.0.
# So RTH Open is constant 100.0.

# Distance from RTH Open to VWAP:
# At 09:30: RTH Open = 100.0. VWAP = 100.166.
# Distance = abs(100.0 - 100.166) / 100.166 * 100 = 0.166%.
# At 09:40: RTH Open = 100.0. VWAP = 101.166.
# Distance = abs(100.0 - 101.166) / 101.166 * 100 = 1.15%.

# Let's test a PriceLevelDistanceCondition:
# Source: RTH Open, Level: VWAP
# Comparator: DISTANCE_GT
# Value_pct: 1.0 (1%)
# Position: any (or below, since RTH Open 100.0 < VWAP 101.166)
# Should be True at 09:40 (since 1.15% > 1%)

# We define the strategy
strat_dict = {
    "name": "Test RTH Open Distance to VWAP",
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
                        "name": "RTH Open",
                        "offset": 0
                    },
                    "level": {
                        "name": "VWAP",
                        "offset": 0
                    },
                    "comparator": "DISTANCE_GT",
                    "value_pct": 1.0,
                    "position": "any",
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

strategy = Strategy(**strat_dict)

print("--- JIT Engine ---")
engine = BacktestEngine(
    strategies=[strategy],
    weights={strategy.id: 1.0},
    market_data=df
)
entry_signals = engine.generate_boolean_signals("entry")
for t, sig in zip(df['timestamp'], entry_signals):
    print(f"{t}: {sig}")

print("\n--- Non-JIT Strategy Engine ---")
res = translate_strategy(df, strat_dict, daily_stats={})
for t, sig in zip(df['timestamp'], res['entries']):
    print(f"{t}: {sig}")
