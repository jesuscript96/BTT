import os
import sys
import pandas as pd
import numpy as np

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.strategy_engine import translate_strategy

def run_test():
    # 1. Create a dummy DataFrame covering a typical day from 07:00 to 18:00 every minute
    times = pd.date_range(start="2026-06-08 07:00:00", end="2026-06-08 18:00:00", freq="1min")
    df = pd.DataFrame({
        "timestamp": times.strftime("%Y-%m-%d %H:%M:%S"),
        "open": np.linspace(100, 105, len(times)),
        "high": np.linspace(101, 106, len(times)),
        "low": np.linspace(99, 104, len(times)),
        "close": np.linspace(100.5, 105.5, len(times)),
        "volume": [1000] * len(times),
    })

    # 2. Define a strategy that has some simple indicator comparison which is always true
    # e.g., Close > 0 (always true)
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
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": 0
                    }
                ]
            },
            # Configured time windows: 08:00 - 09:00 and 11:30 - 12:30
            "entry_time_windows": [
                {"from_time": "08:00", "to_time": "09:00"},
                {"from_time": "11:30", "to_time": "12:30"}
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
        }
    }

    # 3. Call translate_strategy
    result = translate_strategy(df, strategy_def)
    entries = result["entries"]

    # 4. Check that entries only occur in 08:00-09:00 and 11:30-12:30
    # Let's verify each entry time
    entry_indices = np.where(entries)[0]
    entry_times = df.loc[entry_indices, "timestamp"]

    valid_count = 0
    invalid_count = 0

    print("Checking entries:")
    for t_str in entry_times:
        t = pd.to_datetime(t_str)
        hour = t.hour
        minute = t.minute
        mins = hour * 60 + minute

        in_window_1 = (8 * 60 <= mins <= 9 * 60)
        in_window_2 = (11 * 60 + 30 <= mins <= 12 * 60 + 30)

        if in_window_1 or in_window_2:
            valid_count += 1
        else:
            print(f"INVALID entry at {t_str}")
            invalid_count += 1

    print(f"Total entries: {len(entry_times)}")
    print(f"Valid entries: {valid_count}")
    print(f"Invalid entries: {invalid_count}")

    assert invalid_count == 0, "Found entries outside allowed windows!"
    assert valid_count > 0, "No entries found at all!"
    print("SUCCESS: All entries fall strictly within configured time windows!")

if __name__ == "__main__":
    run_test()
