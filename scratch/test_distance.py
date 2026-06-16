import os
import sys
import pandas as pd
import numpy as np

# Change directory to backend/ so imports work correctly
os.chdir(r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')
sys.path.insert(0, r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend')

from app.schemas.strategy import PriceLevelDistanceCondition, IndicatorConfig, IndicatorType, Comparator
from app.backtester.engine import BacktestEngine

# Load some cached intraday data
cache_file = r'c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\.cache\intraday\fc4ea94c2ef733c5e7c4ea38896da1c3.parquet'
df = pd.read_parquet(cache_file)

# Pick a subset of 3 tickers and 3 dates to ensure multiple groups
tickers = df['ticker'].unique()[:3]
dates = df['date'].unique()[:3]
sub_df = df[df['ticker'].isin(tickers) & df['date'].isin(dates)].copy()
sub_df['timestamp'] = pd.to_datetime(sub_df['timestamp'])
sub_df = sub_df.sort_values('timestamp').reset_index(drop=True)

# Create a mock engine to run calculations
engine = BacktestEngine(
    strategies=[],
    weights={},
    market_data=sub_df
)

# 1. Resolve 'Bar Close' (source)
source_config = IndicatorConfig(name=IndicatorType.CLOSE)
s1 = engine._resolve_indicator(source_config, sub_df)

# 2. Resolve 'VWAP' (level)
level_config = IndicatorConfig(name=IndicatorType.VWAP)
s2 = engine._resolve_indicator(level_config, sub_df)

# Let's add columns to sub_df for inspection
sub_df['typical_price'] = (sub_df['high'] + sub_df['low'] + sub_df['close']) / 3.0
sub_df['midpoint_price'] = (sub_df['high'] + sub_df['low']) / 2.0
sub_df['body_midpoint'] = (sub_df['open'] + sub_df['close']) / 2.0
sub_df['s1_close_resolved'] = s1
sub_df['s2_vwap_resolved'] = s2
sub_df['distance_close_to_vwap_pct'] = ((s1 - s2) / s2) * 100.0
sub_df['distance_midpoint_to_vwap_pct'] = ((sub_df['midpoint_price'] - s2) / s2) * 100.0

# Extract a single ticker and date to print
t0 = tickers[0]
d0 = dates[0]
print(f"Inspection for Ticker: {t0} on Date: {d0}")
print("Columns printed: Close, Typical Price, VWAP, Distance Close->VWAP %, Distance Midpoint->VWAP %")

print_df = sub_df[(sub_df['ticker'] == t0) & (sub_df['date'] == d0)].copy()
cols_to_print = ['timestamp', 'open', 'high', 'low', 'close', 'typical_price', 'midpoint_price', 'body_midpoint', 's1_close_resolved', 's2_vwap_resolved', 'distance_close_to_vwap_pct', 'distance_midpoint_to_vwap_pct']
print(print_df[cols_to_print].head(10).to_string())
