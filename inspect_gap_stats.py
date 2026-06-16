import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.cache_service import get_hot_daily_cache

df = get_hot_daily_cache()
print("Hot daily cache shape:", df.shape)

# Let's inspect a few tickers like TSLA, NVDA, MULN
for t in ['TSLA', 'NVDA', 'MULN']:
    ticker_gcs = df[df['ticker'] == t]
    print(f"\n--- {t} (Count: {len(ticker_gcs)}) ---")
    if not ticker_gcs.empty:
        neg_close_cond = ticker_gcs['rth_close'] < ticker_gcs['rth_open']
        close_above_pmh_cond = ticker_gcs['rth_close'] > ticker_gcs['pm_high']
        mid_point = (ticker_gcs['rth_high'] + ticker_gcs['rth_low']) / 2.0
        close_below_vwap_cond = ticker_gcs['rth_close'] < mid_point
        
        print("neg_close_cond matches:")
        print(neg_close_cond.value_counts())
        print("close_above_pmh_cond matches:")
        print(close_above_pmh_cond.value_counts())
        print("close_below_vwap_cond matches:")
        print(close_below_vwap_cond.value_counts())
        
        # Calculate percentages
        print(f"neg_close_freq: {neg_close_cond.mean() * 100:.2f}%")
        print(f"close_above_pmh_freq: {close_above_pmh_cond.mean() * 100:.2f}%")
        print(f"close_below_vwap_freq: {close_below_vwap_cond.mean() * 100:.2f}%")
