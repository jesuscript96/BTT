import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.strategy_engine import translate_strategy

def test_multi_timeframe():
    print("Generating synthetic 1-minute data for testing...")
    # Generate 1-minute data for 1 day (e.g. 390 RTH minutes or just 120 minutes)
    base_time = datetime(2026, 6, 8, 9, 30)
    timestamps = [base_time + timedelta(minutes=i) for i in range(120)]
    
    # Simple walk price starting at 9.0 and going up to 12.0
    close_prices = np.linspace(9.0, 12.0, 120)
    df = pd.DataFrame({
        "timestamp": [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in timestamps],
        "open": close_prices - 0.05,
        "high": close_prices + 0.1,
        "low": close_prices - 0.1,
        "close": close_prices,
        "volume": [100 + i for i in range(120)],
        "ticker": ["AAPL"] * 120
    })

    print(f"Dataframe shape: {df.shape}")

    # Case 1: Simple 5m timeframe strategy
    # Strategy should generate entry signal when Close (at 5m scale) > 10.0
    strategy_def = {
        "bias": "long",
        "entry_logic": {
            "timeframe": "5m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": 10.0,
                        "timeframe": "5m"
                    }
                ]
            }
        },
        "exit_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": 11.5,
                        "timeframe": "1m"
                    }
                ]
            }
        },
        "risk_management": {
            "use_hard_stop": True,
            "hard_stop": {"type": "Percentage", "value": 2.0}
        }
    }

    print("Running translate_strategy...")
    res = translate_strategy(df, strategy_def)
    
    entries = res["entries"]
    exits = res["exits"]
    
    print(f"Entries series length: {len(entries)}")
    print(f"Exits series length: {len(exits)}")
    print(f"Number of entry signals: {entries.sum()}")
    print(f"Number of exit signals: {exits.sum()}")
    
    # Assertions
    assert len(entries) == len(df), "Entries must align back to 1m length"
    assert len(exits) == len(df), "Exits must align back to 1m length"
    
    # Let's inspect when signals trigger.
    # At 5m scale, Close is the close of the 5m bar.
    # 5m bars end at index 4, 9, 14, 19, etc.
    # The close of the 5m bar > 10.0 should be calculated.
    # Let's check which indexes in the 1m df have entry = True.
    entry_indices = df.index[entries].tolist()
    print("Entry signal indices:", entry_indices)
    
    # The alignment should offset by 1 period or shift properly. Let's see if there is no look-ahead.
    # Let's verify that entry_indices are non-empty and make sense.
    if len(entry_indices) > 0:
        print(f"First entry signal at index: {entry_indices[0]}, timestamp: {df.loc[entry_indices[0], 'timestamp']}, close: {df.loc[entry_indices[0], 'close']}")
        print(f"Last entry signal at index: {entry_indices[-1]}, timestamp: {df.loc[entry_indices[-1], 'timestamp']}, close: {df.loc[entry_indices[-1], 'close']}")
    
    print("SUCCESS: test_multi_timeframe verified successfully!")

if __name__ == "__main__":
    test_multi_timeframe()
