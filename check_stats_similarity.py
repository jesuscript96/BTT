import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.cache_service import get_hot_daily_cache

df = get_hot_daily_cache()
tickers = df['ticker'].unique()

print(f"Total unique tickers in cache: {len(tickers)}")

matching_small = 0
non_matching_small = 0
matching_large = 0
non_matching_large = 0

for t in tickers:
    df_t = df[df['ticker'] == t]
    count = len(df_t)
    if count > 0:
        neg = (df_t['rth_close'] < df_t['rth_open']).mean()
        vwap = (df_t['rth_close'] < (df_t['rth_high'] + df_t['rth_low']) / 2).mean()
        is_match = abs(neg - vwap) < 1e-6
        if count <= 10:
            if is_match:
                matching_small += 1
            else:
                non_matching_small += 1
        else:
            if is_match:
                matching_large += 1
            else:
                non_matching_large += 1

print(f"Tickers with <= 10 gap days: {matching_small + non_matching_small}")
print(f"  Matching: {matching_small} ({matching_small/(matching_small+non_matching_small)*100:.1f}%)")
print(f"  Different: {non_matching_small} ({non_matching_small/(matching_small+non_matching_small)*100:.1f}%)")
print(f"Tickers with > 10 gap days: {matching_large + non_matching_large}")
print(f"  Matching: {matching_large} ({matching_large/(matching_large+non_matching_large)*100:.1f}%)")
print(f"  Different: {non_matching_large} ({non_matching_large/(matching_large+non_matching_large)*100:.1f}%)")
