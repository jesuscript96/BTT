import sys
import os
import pandas as pd
import numpy as np
import copy

# Set path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.strategy_engine import translate_strategy, compile_strategy_def
from app.services.backtest_service import run_backtest
from app.services.optimization_service import _set_nested_value

# Create a synthetic intraday dataframe
times = pd.date_range("2026-06-08 09:30:00", periods=10, freq="1min")
intraday_data = {
    "timestamp": times,
    "open":  [100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 102.0, 101.0, 102.5],
    "high":  [101.5, 102.5, 103.0, 102.0, 104.5, 105.0, 104.0, 102.5, 102.0, 103.0],
    "low":   [ 99.5, 100.5, 101.5, 101.0, 102.5, 103.5, 103.0, 101.5, 100.5, 101.5],
    "close": [101.0, 102.0, 101.5, 101.8, 104.0, 103.8, 102.5, 101.0, 102.0, 102.8],
    "volume": [1000, 1200, 1500, 1100, 2000, 1800, 1400, 900, 1100, 1300],
    "date": ["2026-06-08"] * 10,
    "ticker": ["AAPL"] * 10,
}
intraday_df = pd.DataFrame(intraday_data)

qualifying_data = {
    "ticker": ["AAPL"],
    "date": ["2026-06-08"],
    "gap_pct": [2.5],
    "pm_volume": [500000],
    "prev_close": [98.5],
    "rth_open": [100.0],
    "rth_close": [102.8],
    "rth_high": [105.0],
    "rth_low": [99.5],
    "rth_volume": [12000],
}
qualifying_df = pd.DataFrame(qualifying_data)

strategy_def = {
    "name": "Test Strategy",
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Close"},
                    "comparator": "GREATER_THAN",
                    "target": 101.5,
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
        "use_hard_stop": True,
        "use_take_profit": True,
        "take_profit_mode": "Full",
        "accept_reentries": False,
        "hard_stop": {"type": "Percentage", "value": 1.0}, # 1.0% Stop Loss
        "take_profit": {"type": "Percentage", "value": 2.0}, # 2.0% Take Profit
        "trailing_stop": {"active": False},
    }
}

# Run backtests for different stop loss / take profit values manually
# and print the exact trade details
precomputed_groups = list(intraday_df.groupby(["date", "ticker"]))

points = [
    {"sl": 0.5, "tp": 1.5},
    {"sl": 0.5, "tp": 2.5},
    {"sl": 1.5, "tp": 1.5},
    {"sl": 1.5, "tp": 2.5},
]

print("--- Running manual parameter variations ---")
for pt in points:
    # Mutate strategy definition
    modified_def = copy.deepcopy(strategy_def)
    _set_nested_value(modified_def, "risk_management.hard_stop.value", pt["sl"])
    _set_nested_value(modified_def, "risk_management.take_profit.value", pt["tp"])
    
    print(f"\nParameters: SL={pt['sl']}%, TP={pt['tp']}%")
    print(f"Mutated risk config: {modified_def['risk_management']}")
    
    bt_result = run_backtest(
        qualifying_df=qualifying_df,
        strategy_def=modified_def,
        init_cash=10000,
        risk_r=100,
        risk_type="FIXED",
        size_by_sl=False,
        fees=0,
        fee_type="PERCENT",
        slippage=0,
        day_group_iter=iter(precomputed_groups),
        n_groups_hint=len(precomputed_groups),
    )
    
    trades = bt_result.get("trades", [])
    if trades:
        for t in trades:
            print(f"  Trade: entry_price={t['entry_price']}, exit_price={t['exit_price']}, return_pct={t['return_pct']}%, exit_reason={t['exit_reason']}")
    else:
        print("  No trades generated!")
