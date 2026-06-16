import os
import sys
import pandas as pd
import numpy as np

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.strategy_engine import translate_strategy
from app.services.portfolio_sim import simulate

def run_test():
    # 1. Create a dummy DataFrame covering a typical day from 09:30 to 16:00 every minute
    times = pd.date_range(start="2026-06-08 09:30:00", end="2026-06-08 16:00:00", freq="1min")
    df = pd.DataFrame({
        "timestamp": times.strftime("%Y-%m-%d %H:%M:%S"),
        "open": [100.0] * len(times),
        "high": [101.0] * len(times),
        "low": [99.0] * len(times),
        "close": [100.0] * len(times),
        "volume": [1000] * len(times),
    })

    # 2. Define a strategy:
    # - Entry condition: Time is 09:45
    # - Exit condition: Time is 10:15
    # - Entry window: 09:45 - 10:00
    strategy_def = {
        "bias": "long",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Time of Day", "time_hour": 9, "time_minute": 45, "time_condition": "BEFORE"}, # custom indicator comparison dummy
                        "comparator": "GREATER_THAN",
                        "target": 0 # We will override entries/exits manually to test the engine/simulator purely
                    }
                ]
            },
            "entry_time_windows": [
                {"from_time": "09:45", "to_time": "10:00"}
            ]
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
            "accept_reentries": False
        }
    }

    # Let's call translate_strategy first
    # We want to see if translate_strategy handles the signals
    # To test the engine, we will mock the evaluate_condition_group to return signals at specific times:
    # We want entry at 09:45, exit at 10:15.
    
    # Let's inspect raw entries/exits from translate_strategy
    # We will build them manually to test the simulator behavior:
    entries = pd.Series(False, index=df.index)
    # 09:45 is index 15 (09:30 is 0, 09:45 is 15)
    entries.iloc[15] = True
    
    exits = pd.Series(False, index=df.index)
    # 10:15 is index 45 (09:30 is 0, 10:15 is 45)
    exits.iloc[45] = True

    # Now let's apply the entry time window mask like in translate_strategy
    ts = pd.to_datetime(df["timestamp"])
    minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
    time_mask = pd.Series(False, index=df.index)
    
    # Entry window: 09:45 - 10:00 (585 to 600 mins)
    window_mask = (minutes_since_midnight >= 585) & (minutes_since_midnight <= 600)
    time_mask = time_mask | window_mask
    
    entries_masked = entries & time_mask
    
    # Verify entries_masked is True at 09:45 (idx 15) and False at 10:15 (idx 45)
    print(f"Entry signal at 09:45: {entries_masked.iloc[15]}")
    print(f"Entry signal at 10:15: {entries_masked.iloc[45]}")
    
    # Run the simulator
    sim_result = simulate(
        close=df["close"].values,
        open_=df["open"].values,
        high=df["high"].values,
        low=df["low"].values,
        entries=entries_masked.values,
        exits=exits.values,
        direction="longonly",
        init_cash=10000.0,
        risk_r=100.0,
        look_ahead_prevention=True, # enter/exit on next open
    )
    
    trades = sim_result["trades"]
    print(f"Number of trades simulated: {len(trades)}")
    for t in trades:
        print(f"Trade: Entry Index: {t['entry_idx']} (Time: {df.iloc[t['entry_idx']]['timestamp']}), Exit Index: {t['exit_idx']} (Time: {df.iloc[t['exit_idx']]['timestamp']}), Reason: {t['exit_reason']}")

    assert len(trades) == 1, "Should simulate exactly one trade"
    trade = trades[0]
    assert trade["entry_idx"] == 16, "Entry should happen at idx 16 (09:46)"
    assert trade["exit_idx"] == 46, "Exit should happen at idx 46 (10:16)"
    assert trade["exit_reason"] == "Signal", "Exit reason should be Signal"
    print("SUCCESS: Exits outside entry windows work perfectly in the simulator!")

if __name__ == "__main__":
    run_test()
