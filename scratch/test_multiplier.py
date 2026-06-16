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

# Create a mock df
df = pd.DataFrame({
    'timestamp': pd.date_range(start='2025-03-03 09:30:00', periods=5, freq='1min'),
    'open': [100.0, 101.0, 102.0, 103.0, 104.0],
    'high': [100.5, 101.5, 102.5, 103.5, 104.5],
    'low': [99.5, 100.5, 101.5, 102.5, 103.5],
    'close': [100.2, 101.2, 35.0, 103.2, 104.2],  # Note index 2 has close = 35.0
    'volume': [1000, 1100, 1200, 1300, 1400],
    'ticker': ['AAPL'] * 5,
    'date': ['2025-03-03'] * 5
})

# We want condition: Close > Prev Open * 0.3
# Source: Close (offset=0, multiplier=None)
# Target: Open (offset=1, multiplier=0.3)
# Let's check:
# Row 2 (timestamp 09:32:00): Close = 35.0. Prev Open (Row 1 open) = 101.0.
# If multiplier is applied: Target = 101.0 * 0.3 = 30.3.
# Condition: 35.0 > 30.3 -> True!
# If multiplier is ignored: Target = 101.0.
# Condition: 35.0 > 101.0 -> False.

# Let's define the strategy:
strat_dict = {
    "name": "Test Multiplier",
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
                        "name": "Bar Close",
                        "offset": 0
                    },
                    "comparator": "GREATER_THAN",
                    "target": {
                        "name": "Bar Open",
                        "offset": 1,
                        "multiplier": 0.3
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

print("--- Testing JIT Engine ---")
engine = BacktestEngine(
    strategies=[strategy],
    weights={strategy.id: 1.0},
    market_data=df
)

entry_signals = engine.generate_boolean_signals("entry")
print("Engine entry signals:")
for t, sig in zip(df['timestamp'], entry_signals):
    print(f"{t}: {sig}")

print("\n--- Testing Non-JIT Strategy Engine ---")
res = translate_strategy(df, strat_dict)
print("Strategy engine entry signals:")
for t, sig in zip(df['timestamp'], res['entries']):
    print(f"{t}: {sig}")
