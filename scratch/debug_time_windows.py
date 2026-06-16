import os
import sys

sys.path.append(os.path.abspath('backend'))

from app.services.strategy_engine import compile_strategy_def, translate_strategy
import pandas as pd
import numpy as np

strategy_def = {
    "name": "Test Entry Time Windows",
    "bias": "long",
    "apply_day": "gap_day",
    "postgap_preconditions": [],
    "universe_filters": {
        "require_shortable": False,
        "exclude_dilution": False,
        "whitelist_sectors": []
    },
    "entry_logic": {
        "timeframe": "1m",
        "entry_time_windows": [
            {"from_time": "09:30", "to_time": "11:30"}
        ],
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 0.0
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
        "accept_reentries": True,
        "hard_stop": {"type": "Percentage", "value": 5.0},
        "take_profit": {"type": "Percentage", "value": 5.0},
        "partial_take_profits": [],
        "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5}
    }
}

compiled = compile_strategy_def(strategy_def)
print("Compiled entry_time_windows:", compiled.get("entry_time_windows"))

# Let's generate a sample DataFrame with datetime timestamps
times = pd.date_range("2024-01-02 04:00:00", "2024-01-02 20:00:00", freq="1min")
df = pd.DataFrame({
    "timestamp": times,
    "open": np.linspace(100, 102, len(times)),
    "high": np.linspace(100.5, 102.5, len(times)),
    "low": np.linspace(99.5, 101.5, len(times)),
    "close": np.linspace(100.1, 102.1, len(times)),
    "volume": [1000] * len(times),
})

res = translate_strategy(df, strategy_def, compiled=compiled)
entries = res["entries"]
print("Total entries:", entries.sum())
print("Entries at:", df["timestamp"][entries].tolist()[:5])
