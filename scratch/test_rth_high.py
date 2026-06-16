import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.schemas.strategy import Strategy, ConditionGroup, ComparisonCondition, IndicatorConfig, IndicatorType, Comparator
from app.backtester.engine import BacktestEngine
from app.services.strategy_engine import translate_strategy

# Create a mock df representing 1 day of intraday data (9:30 to 10:00)
timestamps = pd.date_range(start='2025-03-03 09:20:00', periods=15, freq='5min')
# RTH starts at 09:30, which is index 2.
# PM is before 09:30.
df = pd.DataFrame({
    'timestamp': timestamps,
    'open':  [10.0, 10.1, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 10.8, 10.7, 10.6, 10.5, 10.4, 10.3, 10.2],
    'high':  [10.2, 10.3, 10.8, 10.9, 11.1, 11.2, 11.3, 11.4, 11.0, 10.9, 10.8, 10.7, 10.6, 10.5, 10.4],
    'low':   [9.8,  9.9,  10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.7, 10.6, 10.5, 10.4, 10.3, 10.2, 10.1],
    'close': [10.1, 10.2, 10.6, 10.7, 10.8, 10.9, 11.0, 10.8, 10.7, 10.6, 10.5, 10.4, 10.3, 10.2, 10.1],
    'volume': [1000] * 15,
    'ticker': ['AAPL'] * 15,
    'date': ['2025-03-03'] * 15
})

# Let's check:
# PM High (04:00 - 09:30): Index 0 (09:20) and Index 1 (09:25) are premarket.
# PM High is max(10.2, 10.3) = 10.3.
# RTH High (09:30 - 16:00): Index 2 to 14.
# RTH High is max(highs[2:]) = 11.4.
# Condition: RTH High > PM High * 1.10
# PM High * 1.10 = 10.3 * 1.10 = 11.33.
# RTH High = 11.4 > 11.33 -> True!

# We define the strategy comparing RTH High vs PM High with multiplier 1.1
strat_dict = {
    "name": "Test RTH High vs PM High",
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {
                        "name": "RTH High",
                        "offset": 0
                    },
                    "comparator": "GREATER_THAN",
                    "target": {
                        "name": "PM High",
                        "offset": 0,
                        "multiplier": 1.1
                    },
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

print("--- Testing JIT Engine (Before Fix) ---")
try:
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df
    )
    entry_signals = engine.generate_boolean_signals("entry")
    print("Engine entry signals (first 5):")
    for t, sig in zip(df['timestamp'].head(5), entry_signals[:5]):
        print(f"{t}: {sig}")
except Exception as e:
    print(f"Engine failed: {e}")

print("\n--- Testing Non-JIT Strategy Engine (Before Fix) ---")
try:
    res = translate_strategy(df, strat_dict, daily_stats={})
    print("Strategy engine entry signals (first 5):")
    for t, sig in zip(df['timestamp'].head(5), res['entries'].head(5)):
        print(f"{t}: {sig}")
except Exception as e:
    print(f"Strategy engine failed: {e}")
