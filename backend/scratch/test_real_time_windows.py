import os
import sys
import pandas as pd
import numpy as np
import duckdb

# Add backend directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.connection import get_connection
from app.services.strategy_engine import translate_strategy

def run_test():
    # 1. Get resolved parquet path for Jan 2024
    conn = get_connection()
    from app.db.gcs_cache import _select_intraday_glob_for_month
    path = _select_intraday_glob_for_month(conn, 2024, 1)
    
    print(f"Reading real intraday data from resolved path: {path}")
    sql = f"""
    SELECT ticker, date, timestamp, open, high, low, close, volume
    FROM read_parquet('{path}', hive_partitioning=true)
    WHERE ticker = 'SAVE' AND date = '2024-01-19'
    ORDER BY timestamp
    """
    df = conn.execute(sql).fetchdf()
    print(f"Loaded {len(df)} rows of real data.")
    
    if df.empty:
        print("Error: DataFrame is empty. Ensure you are connected to internet/GCS.")
        return

    # 2. Define a strategy with a simple condition (Close > 0)
    # and entry windows 07:00 - 08:00 (Pre-Market) and 10:00 - 11:00 (RTH)
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
            "entry_time_windows": [
                {"from_time": "07:00", "to_time": "08:00"},
                {"from_time": "10:00", "to_time": "11:00"}
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

    # 4. Analyze generated entries
    entry_indices = np.where(entries)[0]
    entry_times = df.loc[entry_indices, "timestamp"]

    valid_count = 0
    invalid_count = 0

    print("\nListing generated entry timestamps:")
    for t_val in entry_times:
        t = pd.to_datetime(t_val)
        hour = t.hour
        minute = t.minute
        mins = hour * 60 + minute

        in_window_1 = (7 * 60 <= mins <= 8 * 60)
        in_window_2 = (10 * 60 <= mins <= 11 * 60)

        status_str = "OK" if (in_window_1 or in_window_2) else "INVALID"
        print(f"Entry at {t} - {status_str}")
        if status_str == "OK":
            valid_count += 1
        else:
            invalid_count += 1

    print(f"\nSummary of real data test:")
    print(f"Total entries generated: {len(entry_times)}")
    print(f"Valid entries: {valid_count}")
    print(f"Invalid entries: {invalid_count}")
    
    assert invalid_count == 0, "Test failed: entries found outside configured time windows!"
    print("SUCCESS: real data test passed. Entry time windows work perfectly!")

if __name__ == "__main__":
    run_test()
