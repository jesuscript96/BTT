import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.services.indicators import compute_indicator
from app.services.strategy_engine import translate_strategy

# Load the cached intraday file
cache_file = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\.cache\intraday\fc4ea94c2ef733c5e7c4ea38896da1c3.parquet'
df = pd.read_parquet(cache_file)

# Let's inspect unique tickers and dates
tickers = df['ticker'].unique()
dates = df['date'].unique()
print(f"Loaded dataset with {len(tickers)} tickers and {len(dates)} dates.")

# Pick the first ticker and first date
ticker = tickers[0]
date = dates[0]
print(f"Inspecting ticker: {ticker} on date: {date}")

day_df = df[(df['ticker'] == ticker) & (df['date'] == date)].copy()
day_df['timestamp'] = pd.to_datetime(day_df['timestamp'])
day_df = day_df.sort_values('timestamp').reset_index(drop=True)

# Calculate indicators
pm_low_series = compute_indicator("PM Low", day_df, daily_stats={})
rth_low_series = compute_indicator("RTH Low", day_df, daily_stats={})

pm_low_val = pm_low_series.iloc[0]
rth_low_val = rth_low_series.iloc[0]
print(f"Calculated PM Low: {pm_low_val:.4f}")
print(f"Calculated RTH Low: {rth_low_val:.4f}")

distance_pct = abs(rth_low_val - pm_low_val) / pm_low_val * 100
is_below = rth_low_val < pm_low_val
print(f"Distance %: {distance_pct:.2f}% | Is Below: {is_below}")

# Let's evaluate with DISTANCE_GT 20% below
strat_gt = {
    "name": "Test GT",
    "bias": "short",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "price_level_distance",
                    "source": {"name": "RTH Low"},
                    "level": {"name": "PM Low"},
                    "comparator": "DISTANCE_GT",
                    "value_pct": 2.0, # Let's use 2% as value_pct
                    "position": "below",
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
    "risk_management": {"use_hard_stop": False, "use_take_profit": False}
}

strat_lt = {
    "name": "Test LT",
    "bias": "short",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "price_level_distance",
                    "source": {"name": "RTH Low"},
                    "level": {"name": "PM Low"},
                    "comparator": "DISTANCE_LT",
                    "value_pct": 2.0, # Let's use 2% as value_pct
                    "position": "below",
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {"timeframe": "1m", "root_condition": {"type": "group", "operator": "AND", "conditions": []}},
    "risk_management": {"use_hard_stop": False, "use_take_profit": False}
}

res_gt = translate_strategy(day_df, strat_gt, daily_stats={})
res_lt = translate_strategy(day_df, strat_lt, daily_stats={})

print(f"GT (entries triggered): {res_gt['entries'].any()} (Sum: {res_gt['entries'].sum()})")
print(f"LT (entries triggered): {res_lt['entries'].any()} (Sum: {res_lt['entries'].sum()})")
