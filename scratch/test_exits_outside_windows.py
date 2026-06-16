import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.abspath('backend'))

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

# Entries is only True at 09:35
entries = pd.Series(False, index=df.index)
# Find the index for 09:35
idx_935 = df[df["timestamp"] == "2026-06-08 09:35:00"].index[0]
entries.loc[idx_935] = True

# Exits is only True at 10:15
exits = pd.Series(False, index=df.index)
idx_1015 = df[df["timestamp"] == "2026-06-08 10:15:00"].index[0]
exits.loc[idx_1015] = True

# Run simulation
sim_res = simulate(
    close=df["close"].values,
    open_=df["open"].values,
    high=df["high"].values,
    low=df["low"].values,
    entries=entries.values,
    exits=exits.values,
    direction="longonly",
    init_cash=10000.0,
    risk_r=100.0
)

print("\nSimulation trades:")
for t in sim_res["trades"]:
    print(f"Trade: Entry={df.loc[t['entry_idx'], 'timestamp']} ({t['entry_price']}), Exit={df.loc[t['exit_idx'], 'timestamp']} ({t['exit_price']}), Reason={t['exit_reason']}")
