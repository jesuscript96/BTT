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

def run_test(pm_low_val, rth_low_val, pm_high_val, rth_high_val, source_name, level_name, comparator, value_pct, position):
    # Create a simple 1-day, 13-bar intraday dataframe
    timestamps = pd.date_range(start='2025-03-03 09:00:00', periods=13, freq='5min')
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open':  [10.0] * 13,
        'high':  [1.0] * 13,   # Default high to 1.0 so we can set higher test highs
        'low':   [100.0] * 13, # Default low to 100.0 so we can set lower test lows
        'close': [10.0] * 13,
        'volume': [1000] * 13,
        'ticker': ['AAPL'] * 13,
        'date': ['2025-03-03'] * 13
    })
    
    # Premarket: Index 0 to 5
    df.loc[0, 'low'] = pm_low_val
    df.loc[0, 'high'] = pm_high_val
    # RTH: Index 6 to 12
    df.loc[8, 'low'] = rth_low_val
    df.loc[8, 'high'] = rth_high_val
    
    strat_dict = {
        "name": "Test Distance Strategy",
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
                            "name": source_name,
                            "offset": 0
                        },
                        "level": {
                            "name": level_name,
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
    
    res = translate_strategy(df, strat_dict, daily_stats={})
    non_jit_triggered = res['entries'].any()
    
    strategy = Strategy(**strat_dict)
    engine = BacktestEngine(
        strategies=[strategy],
        weights={strategy.id: 1.0},
        market_data=df
    )
    jit_entries = engine.generate_boolean_signals("entry")
    jit_triggered = jit_entries.any()
    
    # Calculate expected values
    from app.services.indicators import compute_indicator
    resolved_source = compute_indicator(source_name, df, daily_stats={}).iloc[0]
    resolved_level = compute_indicator(level_name, df, daily_stats={}).iloc[0]
    
    diff_pct = (resolved_source - resolved_level) / resolved_level * 100
    abs_diff_pct = abs(diff_pct)
    
    print(f"Source ({source_name}): {resolved_source:.2f}, Level ({level_name}): {resolved_level:.2f}")
    print(f"Diff %: {diff_pct:.2f}%, Abs Diff %: {abs_diff_pct:.2f}%")
    print(f"Condition: {comparator} {value_pct}% ({position})")
    print(f"Non-JIT entries triggered: {non_jit_triggered}")
    print(f"JIT entries triggered: {jit_triggered}")
    print("-" * 60)

# 1. RTH Low vs PM Low (below)
print("1. Source = RTH Low (0.75), Level = PM Low (1.00), position = below")
run_test(pm_low_val=1.00, rth_low_val=0.75, pm_high_val=2.00, rth_high_val=2.00,
         source_name="RTH Low", level_name="PM Low", comparator="DISTANCE_GT", value_pct=20.0, position="below")

# 2. PM Low vs RTH Low (above)
print("2. Source = PM Low (1.00), Level = RTH Low (0.75), position = above")
run_test(pm_low_val=1.00, rth_low_val=0.75, pm_high_val=2.00, rth_high_val=2.00,
         source_name="PM Low", level_name="RTH Low", comparator="DISTANCE_GT", value_pct=20.0, position="above")

# 3. RTH High vs PM High (above)
print("3. Source = RTH High (1.20), Level = PM High (1.00), position = above")
run_test(pm_low_val=50.0, rth_low_val=50.0, pm_high_val=1.00, rth_high_val=1.20,
         source_name="RTH High", level_name="PM High", comparator="DISTANCE_GT", value_pct=10.0, position="above")

# 4. PM High vs RTH High (below)
print("4. Source = PM High (1.00), Level = RTH High (1.20), position = below")
run_test(pm_low_val=50.0, rth_low_val=50.0, pm_high_val=1.00, rth_high_val=1.20,
         source_name="PM High", level_name="RTH High", comparator="DISTANCE_GT", value_pct=10.0, position="below")
