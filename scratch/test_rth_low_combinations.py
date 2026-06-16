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

def run_test(pm_low_val, rth_low_val, value_pct, position, comparator):
    # Create a simple 1-day, 13-bar intraday dataframe
    # 09:00 to 10:00 (5m interval)
    timestamps = pd.date_range(start='2025-03-03 09:00:00', periods=13, freq='5min')
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open':  [10.0] * 13,
        'high':  [11.0] * 13,
        'low':   [10.0] * 13,
        'close': [10.5] * 13,
        'volume': [1000] * 13,
        'ticker': ['AAPL'] * 13,
        'date': ['2025-03-03'] * 13
    })
    
    # Premarket is index 0 to 5 (09:00 to 09:25). Set low to pm_low_val at index 0.
    df.loc[0, 'low'] = pm_low_val
    # RTH is index 6 to 12. Set low to rth_low_val at index 8 (09:40).
    df.loc[8, 'low'] = rth_low_val
    
    # Strategy condition
    strat_dict = {
        "name": "Test Strategy",
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
                        "comparator": comparator,
                        "value_pct": value_pct,
                        "position": position,
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
    
    # 1. Non-JIT Strategy Engine
    res = translate_strategy(df, strat_dict, daily_stats={})
    non_jit_triggered = res['entries'].any()
    
    # 2. JIT Engine
    strategy = Strategy(**strat_dict)
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df
    )
    jit_entries = engine.generate_boolean_signals("entry")
    jit_triggered = jit_entries.any()
    
    # Check actual resolved values
    from app.services.indicators import compute_indicator
    resolved_pm_low = compute_indicator("PM Low", df, daily_stats={}).iloc[0]
    resolved_rth_low = compute_indicator("RTH Low", df, daily_stats={}).iloc[0]
    
    actual_diff_pct = abs(resolved_rth_low - resolved_pm_low) / resolved_pm_low * 100
    is_below = resolved_rth_low < resolved_pm_low
    
    print(f"PM Low: {resolved_pm_low:.2f}, RTH Low: {resolved_rth_low:.2f}")
    print(f"Diff %: {actual_diff_pct:.2f}%, Is Below: {is_below}")
    print(f"Condition: {comparator} {value_pct}% ({position})")
    print(f"Non-JIT result (entries triggered): {non_jit_triggered}")
    print(f"JIT result (entries triggered): {jit_triggered}")
    print("-" * 50)

# Scenario 1: PM Low = 1.0, RTH Low = 0.75 (25% below). Distance > 20% below.
print("Scenario 1: PM Low = 1.0, RTH Low = 0.75. Distance GT 20% below.")
run_test(pm_low_val=1.0, rth_low_val=0.75, value_pct=20.0, position="below", comparator="DISTANCE_GT")

# Scenario 2: PM Low = 1.0, RTH Low = 0.90 (10% below). Distance GT 20% below.
print("Scenario 2: PM Low = 1.0, RTH Low = 0.90. Distance GT 20% below.")
run_test(pm_low_val=1.0, rth_low_val=0.90, value_pct=20.0, position="below", comparator="DISTANCE_GT")

# Scenario 3: PM Low = 1.0, RTH Low = 0.75 (25% below). Distance LT 20% below.
print("Scenario 3: PM Low = 1.0, RTH Low = 0.75. Distance LT 20% below.")
run_test(pm_low_val=1.0, rth_low_val=0.75, value_pct=20.0, position="below", comparator="DISTANCE_LT")

# Scenario 4: PM Low = 1.0, RTH Low = 0.90 (10% below). Distance LT 20% below.
print("Scenario 4: PM Low = 1.0, RTH Low = 0.90. Distance LT 20% below.")
run_test(pm_low_val=1.0, rth_low_val=0.90, value_pct=20.0, position="below", comparator="DISTANCE_LT")
