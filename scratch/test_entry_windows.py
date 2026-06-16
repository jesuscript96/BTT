import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.abspath('backend'))

from app.services.strategy_engine import translate_strategy
from app.services.portfolio_sim import simulate

# Create 60 minutes of data from 09:20 to 10:20
times = pd.date_range("2026-06-08 09:20:00", "2026-06-08 10:20:00", freq="1min")
df = pd.DataFrame({
    "timestamp": times,
    "open": np.linspace(100, 102, len(times)),
    "high": np.linspace(100.5, 102.5, len(times)),
    "low": np.linspace(99.5, 101.5, len(times)),
    "close": np.linspace(100.1, 102.1, len(times)),
    "volume": [1000] * len(times),
})

# Define a strategy where we always want to enter and exit
# We use a dummy comparison: Close > 0 (always True)
strategy_def = {
    "bias": "long",
    "entry_logic": {
        "timeframe": "1m",
        "entry_time_windows": [
            {"from_time": "09:30", "to_time": "09:45"}
        ],
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 0,
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
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": 0,
                    "timeframe": "1m"
                }
            ]
        }
    },
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 2.0},
        "use_take_profit": True,
        "take_profit": {"type": "Percentage", "value": 6.0},
        "accept_reentries": True
    }
}

signals = translate_strategy(df, strategy_def)
entries = signals["entries"]
exits = signals["exits"]

print("Entries count:", entries.sum())
print("Exits count:", exits.sum())

print("\nEntries at:")
for idx, val in entries.items():
    if val:
        print(f"  {df.loc[idx, 'timestamp']}")

print("\nExits at:")
for idx, val in exits.items():
    if val:
        # Just print first 5 for brevity
        print(f"  {df.loc[idx, 'timestamp']}")
        break
print("  ...")

# Run simulation
sim_res = simulate(
    close=df["close"].values,
    open_=df["open"].values,
    high=df["high"].values,
    low=df["low"].values,
    entries=entries.values,
    exits=exits.values,
    direction=signals["direction"],
    init_cash=10000.0,
    risk_r=100.0,
    sl_stop=signals["sl_stop"],
    tp_stop=signals["tp_stop"]
)

print("\nSimulation trades:")
for t in sim_res["trades"]:
    print(f"Trade: Entry={df.loc[t['entry_idx'], 'timestamp']} ({t['entry_price']}), Exit={df.loc[t['exit_idx'], 'timestamp']} ({t['exit_price']}), Reason={t['exit_reason']}")
